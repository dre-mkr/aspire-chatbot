"""What a lesson in progress is made of."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

#: Every phase the lesson machine can be in.
Phase = Literal[
    "placing",
    "teaching",
    "checking",
    "hinting",
    "reteaching",
    "explaining_back",
    "playing",
    "updating_mastery",
    "wrapping",
    "done",
]

#: Hard caps.
MAX_ATTEMPTS = 3
MAX_DIGRESSIONS = 2
MAX_HINT_RUNG = 3


class LearningState(TypedDict, total=False):
    """One lesson in progress."""

    module_id: str | None
    lesson_id: str | None
    #: Which check question within the lesson.
    question_id: str | None
    phase: Phase
    #: Wrong answers on the CURRENT question.
    attempts: int
    #: Which rung of the hint ladder was last given, 0 meaning none.
    hint_rung: int
    #: CONSECUTIVE off-curriculum turns.
    digression_count: int
    session_started_at: str
    #: Concepts this session has touched, for the wrap-up summary.
    concepts_touched: list[str]
    #: Which widget kinds have been shown recently, so the planner varies the primitive.
    last_widget_kinds: list[str]
    #: The primitive `plan_widget` chose for the teaching turn about to run, or None.
    pending_widget: str | None
    #: How each recent teaching turn began, so the next one can begin differently.
    recent_openings: list[str]
    #: Whether this learner has a mastery row for the concept being taught.
    concept_seen_before: bool
    #: How many times each lesson id has been taught in this thread.
    teach_count: dict[str, int]
    #: Concepts due for review, folded into this lesson's checks.
    review_concepts: list[str]
    #: The learner row this session writes mastery against.
    learner_id: str | None
    #: Set once `wrap_session` emitted its progress directive, so a resume emits no second one.
    wrapped: bool

    # ── topic resolution ──────────────────────────────────────────────────

    #: The concept this turn is about, from `resolve_concept`.
    active_concept_id: str | None
    #: How it was resolved: continuation | semantic | disambiguated | rag | none.
    resolution_source: str
    #: The cosine similarity behind that decision, for threshold calibration.
    resolution_similarity: float
    #: Which move `plan_move` chose.
    move: str
    #: A check question is outstanding and the next message is its answer.
    awaiting_check_answer: bool
    #: Which item from the concept's bank is outstanding.
    pending_check_id: str | None
    #: Check ids this learner has already seen, so the bank is not repeated before it is exhausted.
    seen_check_ids: list[str]
    #: Consecutive wrong answers on the current concept.
    consecutive_wrong: int
    #: The wrong answers themselves, so a later turn can address the mistake, not just repeat.
    prior_wrong_answers: list[str]
    #: Turns spent on each concept this session. Drives the switch to a game.
    turns_on_concept: dict[str, int]
    #: Turns since a check question was last asked.
    turns_since_check: int


def new_session(*, learner_id: str | None = None, now: datetime | None = None) -> LearningState:
    """A fresh lesson state. Every field populated, none left to a `.get` default."""
    moment = now or datetime.now(timezone.utc)
    return LearningState(
        module_id=None,
        lesson_id=None,
        question_id=None,
        phase="placing",
        attempts=0,
        hint_rung=0,
        digression_count=0,
        session_started_at=moment.isoformat(),
        concepts_touched=[],
        last_widget_kinds=[],
        pending_widget=None,
        recent_openings=[],
        concept_seen_before=False,
        teach_count={},
        review_concepts=[],
        learner_id=learner_id,
        wrapped=False,
        active_concept_id=None,
        resolution_source="none",
        resolution_similarity=0.0,
        move="",
        awaiting_check_answer=False,
        pending_check_id=None,
        seen_check_ids=[],
        consecutive_wrong=0,
        prior_wrong_answers=[],
        turns_on_concept={},
        turns_since_check=0,
    )


def on_concept(state: LearningState, concept_id: str | None) -> dict[str, int]:
    """The per-concept turn counter, incremented for this one."""
    counts = dict(state.get("turns_on_concept") or {})
    if concept_id:
        counts[concept_id] = counts.get(concept_id, 0) + 1
    return counts


def seen_check(state: LearningState, check_id: str | None, *, keep: int = 40) -> list[str]:
    """Check ids this learner has met, most recent last."""
    seen = [item for item in (state.get("seen_check_ids") or []) if item]
    if check_id and check_id not in seen:
        seen.append(check_id)
    return seen[-keep:]


#: The band used when neither the resolved context nor the turn state has one.
FALLBACK_BAND = "9-12"


def band_of(state: Any) -> str:
    """This learner's age band: the resolved context first, then turn state."""
    context = state.get("context")
    band = getattr(context, "age_band", None) if context is not None else None
    return str(band or state.get("age_band") or FALLBACK_BAND)


def started_at(state: LearningState) -> datetime:
    """When this session began, as an aware datetime."""
    raw = state.get("session_started_at")
    if not raw:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def touched(state: LearningState, concept_id: str) -> list[str]:
    """`concepts_touched` with `concept_id` added once."""
    seen = list(state.get("concepts_touched") or [])
    if concept_id and concept_id not in seen:
        seen.append(concept_id)
    return seen


def remember_widget(state: LearningState, kind: str | None, *, keep: int = 3) -> list[str]:
    """The recent widget kinds, newest last, capped."""
    recent = list(state.get("last_widget_kinds") or [])
    if kind:
        recent.append(kind)
    return recent[-keep:]


#: How many words of a teaching turn count as its opening.
OPENING_WORDS = 8


def remember_opening(state: LearningState, text: str, *, keep: int = 3) -> list[str]:
    """The recent teaching openings, newest last, capped."""
    recent = list(state.get("recent_openings") or [])
    opening = " ".join((text or "").split()[:OPENING_WORDS]).strip()
    if opening and opening not in recent:
        recent.append(opening)
    return recent[-keep:]


def taught_again(state: LearningState, lesson_id: str) -> dict[str, int]:
    """`teach_count` with this lesson's tally incremented."""
    counts = dict(state.get("teach_count") or {})
    if lesson_id:
        counts[lesson_id] = counts.get(lesson_id, 0) + 1
    return counts


def merge(state: Any, **changes: Any) -> LearningState:
    """A learning state with `changes` applied, tolerating None."""
    base: LearningState = dict(state) if state else new_session()  # type: ignore[assignment]
    base.update(changes)
    return base
