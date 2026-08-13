"""The eligibility engine: the flow, the verdict, and the personalised result."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from app.eligibility import content as copy
from app.eligibility.config import EligibilitySettings, get_eligibility_settings
from app.eligibility.models import (
    ChecklistItem,
    Language,
    Option,
    Outcome,
    Question,
    Result,
    Session,
    Step,
    Verdict,
)
from app.eligibility.rules import (
    ALTERNATIVES,
    COUNTED,
    OPTIONS,
    counted_position,
    decide,
    documents_for,
    plan,
    reminder_year,
    steps_for,
)
from app.eligibility.store import SessionStore, get_store

logger = logging.getLogger(__name__)


class EligibilityError(Exception):
    """Base for conditions the tools and the router turn into a declined response."""

    reason = "eligibility_error"


class CheckNotRunning(EligibilityError):
    reason = "no_check_running"


class CheckAlreadyRunning(EligibilityError):
    reason = "already_running"


class UnknownAnswer(EligibilityError):
    """A token that is not an option on the question being asked."""

    reason = "unknown_answer"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The whole flow as the card draws it: one question, or the result."""

    language: Language
    question: Question | None
    result: Result | None
    answered: int
    total: int

    @property
    def finished(self) -> bool:
        return self.result is not None


class EligibilityEngine:
    def __init__(
        self,
        store: SessionStore | None = None,
        settings: EligibilitySettings | None = None,
        today: date | None = None,
    ) -> None:
        self._store = store or get_store()
        self._settings = settings or get_eligibility_settings()
        # Injectable so the reminder-year test does not have to wait a year.
        self._today = today

    # --- helpers ----------------------------------------------------------

    def _session(self, session_id: str) -> Session:
        session = self._store.get(session_id)
        if session is None:
            raise CheckNotRunning("No eligibility check is running in this conversation.")
        return session

    def _question(self, session: Session, question_id: str) -> Question:
        strings = copy.QUESTIONS[question_id][session.language]
        return Question(
            id=question_id,
            text=strings["text"],
            help=strings.get("help"),
            options=tuple(
                Option(value=value, label=strings[value]) for value in OPTIONS[question_id]
            ),
            position=counted_position(question_id),
            total=len(COUNTED),
            answered_with=session.answers.get(question_id),
            # Offered on every step but the first thing shown.
            can_go_back=session.index > 0,
        )

    def _snapshot(self, session: Session) -> Snapshot:
        questions = plan(session.answers)

        if session.index >= len(questions):
            return self._finish(session)

        return Snapshot(
            language=session.language,
            question=self._question(session, questions[session.index]),
            result=None,
            answered=session.index,
            total=len(COUNTED),
        )

    # --- result assembly --------------------------------------------------

    def _checklist(self, answers: dict[str, str], language: Language) -> tuple[ChecklistItem, ...]:
        items = []
        for document_id in documents_for(answers):
            strings = copy.DOCUMENTS[document_id][language]
            items.append(
                ChecklistItem(
                    id=document_id,
                    title=strings["title"],
                    detail=strings["detail"],
                    where=strings["where"],
                    signed_by=strings.get("signed_by"),
                    caveat=strings.get("caveat"),
                    alternative=document_id in ALTERNATIVES,
                )
            )
        return tuple(items)

    def _steps(self, answers: dict[str, str], language: Language) -> tuple[Step, ...]:
        steps = []
        for number, step_id in enumerate(steps_for(answers), start=1):
            strings = copy.STEPS[step_id][language]
            steps.append(
                Step(
                    number=number,
                    title=strings["title"],
                    detail=strings["detail"],
                    link=copy.PORTAL_URL if step_id == "portal" else None,
                    link_label=strings.get("link_label"),
                )
            )
        return tuple(steps)

    def _result(self, session: Session) -> Result:
        """Assemble the verdict, its words, and everything shown beside it."""
        language = session.language
        decision = decide(session.answers)
        strings = copy.RESULTS[decision.copy_key][language]

        body = list(strings["body"])  # type: ignore[arg-type]
        year = reminder_year(session.answers, self._today or date.today())
        if decision.copy_key == "age_minimum" and year is not None:
            body.append(str(strings["year"]).format(year=year))
        # The "meanwhile" line stops a not-yet reading as a door closing, so it goes last.
        if "meanwhile" in strings:
            body.append(str(strings["meanwhile"]))

        unresolved = tuple(
            copy.UNRESOLVED_LABELS[name][language] for name in decision.unresolved
        )
        mentor = (
            copy.MENTOR_QUESTIONS[decision.unresolved[0]][language]
            if decision.unresolved
            else None
        )

        # The checklist and the walkthrough are for people who have somewhere to go.
        actionable = decision.verdict in (Verdict.LIKELY_ELIGIBLE, Verdict.NEEDS_CONFIRMATION)

        return Result(
            verdict=decision.verdict,
            criterion=decision.criterion,
            headline=str(strings["headline"]),
            body=tuple(body),
            disclaimer=copy.DISCLAIMER[language],
            unresolved=unresolved,
            mentor_question=mentor,
            checklist=self._checklist(session.answers, language) if actionable else (),
            steps=self._steps(session.answers, language) if actionable else (),
            notices=(
                (copy.NOTICES["no_deadline"][language], copy.NOTICES["free"][language])
                if actionable or decision.copy_key == "age_minimum"
                else ()
            ),
            contacts=copy.contacts(language),
            reminder_year=year,
        )

    def _finish(self, session: Session) -> Snapshot:
        """Produce the result and discard the answers, in one step."""
        result = self._result(session)
        self._store.delete(session.session_id)
        return Snapshot(
            language=session.language,
            question=None,
            result=result,
            answered=len(COUNTED),
            total=len(COUNTED),
        )

    # --- operations -------------------------------------------------------

    def start(self, session_id: str, language: Language = Language.EN) -> Snapshot:
        if self._store.get(session_id) is not None:
            raise CheckAlreadyRunning("An eligibility check is already running here.")
        session = Session(session_id=session_id, language=language)
        self._store.put(session)
        return self._snapshot(session)

    def answer(self, session_id: str, value: str) -> Snapshot:
        """Record one answer and move on."""
        session = self._session(session_id)
        questions = plan(session.answers)
        if session.index >= len(questions):
            return self._finish(session)

        question_id = questions[session.index]
        if value not in OPTIONS[question_id]:
            raise UnknownAnswer(f"{value!r} is not an option on this question.")

        session.answers[question_id] = value

        # Answering `age` reshapes the plan, so re-derive the index from the new question list.
        questions = plan(session.answers)
        session.index = questions.index(question_id) + 1

        # Leaving the under-5 branch strands an `age_exact` answer that is no longer asked.
        if "age_exact" not in questions:
            session.answers.pop("age_exact", None)

        self._store.put(session)
        return self._snapshot(session)

    def back(self, session_id: str) -> Snapshot:
        """Step back one question, keeping every answer."""
        session = self._session(session_id)
        session.index = max(0, session.index - 1)
        self._store.put(session)
        return self._snapshot(session)

    def restart(self, session_id: str, language: Language | None = None) -> Snapshot:
        """Throw the answers away and begin again."""
        existing = self._store.get(session_id)
        chosen = language or (existing.language if existing else Language.EN)
        self._store.delete(session_id)
        return self.start(session_id, chosen)

    def quit(self, session_id: str) -> None:
        """Leave without finishing."""
        self._store.delete(session_id)

    def state(self, session_id: str) -> Snapshot | None:
        """The flow in progress, or None."""
        session = self._store.get(session_id)
        if session is None:
            return None
        questions = plan(session.answers)
        if session.index >= len(questions):
            # Unreachable in practice: answering the last question finishes and deletes.
            return None
        return Snapshot(
            language=session.language,
            question=self._question(session, questions[session.index]),
            result=None,
            answered=session.index,
            total=len(COUNTED),
        )

    @staticmethod
    def outcome_of(result: Result, language: Language) -> Outcome:
        """The anonymised row for the insight view."""
        return Outcome(
            verdict=result.verdict,
            criterion=result.criterion,
            language=language,
        )


_engine: EligibilityEngine | None = None


def get_engine() -> EligibilityEngine:
    global _engine
    if _engine is None:
        _engine = EligibilityEngine()
    return _engine


def set_engine(engine: EligibilityEngine | None) -> None:
    """Swap the engine. Used by tests."""
    global _engine
    _engine = engine
