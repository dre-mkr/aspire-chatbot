"""HTTP surface for the eligibility pre-check.

Why this exists alongside the agent tool, and it is the same reason the games
card has one: this is direct manipulation. Someone taps an option and the next
question has to appear now, not after a model round trip — for a decision the
model is deliberately not allowed to make.

The agent's only route in is `start_eligibility_check`. Everything after the
first question happens here, which is also what keeps the answers away from the
model entirely: an age band tapped into this card never enters a prompt.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.eligibility import content as copy
from app.eligibility import outcomes
from app.eligibility.engine import (
    CheckAlreadyRunning,
    CheckNotRunning,
    EligibilityEngine,
    EligibilityError,
    Snapshot,
    UnknownAnswer,
    get_engine,
)
from app.eligibility.models import Language
from app.eligibility.schemas import (
    AnswerBody,
    ChecklistItemOut,
    LabelsOut,
    OptionOut,
    QuestionOut,
    RestartBody,
    ResultOut,
    StartBody,
    StateEnvelope,
    StepOut,
    ThreadBody,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])

_STATUS = {
    CheckNotRunning: 404,
    CheckAlreadyRunning: 409,
    UnknownAnswer: 422,
}


def _fail(error: EligibilityError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(type(error), 400),
        detail={"reason": error.reason, "message": str(error)},
    )


def _language(raw: str | None) -> Language:
    """Unknown languages fall back to English rather than 400.

    A flow that refuses to start because a client sent a locale we do not author
    is worse than one that starts in English. The three we do author are the
    three the rest of the product speaks.
    """
    if not raw:
        return Language.EN
    try:
        return Language(raw.lower())
    except ValueError:
        logger.warning("Unknown eligibility language %r; using English.", raw)
        return Language.EN


def _labels(language: Language) -> LabelsOut:
    return LabelsOut(**copy.UI[language])


def _envelope(snapshot: Snapshot | None, language: Language) -> StateEnvelope:
    if snapshot is None:
        return StateEnvelope(
            active=False, language=language.value, labels=_labels(language)
        )

    question = None
    if snapshot.question is not None:
        q = snapshot.question
        question = QuestionOut(
            id=q.id,
            text=q.text,
            help=q.help,
            options=[OptionOut(value=o.value, label=o.label) for o in q.options],
            position=q.position,
            total=q.total,
            answered_with=q.answered_with,
            can_go_back=q.can_go_back,
        )

    result = None
    if snapshot.result is not None:
        r = snapshot.result
        result = ResultOut(
            verdict=r.verdict.value,
            criterion=r.criterion.value,
            headline=r.headline,
            body=list(r.body),
            disclaimer=r.disclaimer,
            unresolved=list(r.unresolved),
            mentor_question=r.mentor_question,
            checklist=[
                ChecklistItemOut(
                    id=item.id,
                    title=item.title,
                    detail=item.detail,
                    where=item.where,
                    signed_by=item.signed_by,
                    caveat=item.caveat,
                    alternative=item.alternative,
                )
                for item in r.checklist
            ],
            steps=[
                StepOut(
                    number=step.number,
                    title=step.title,
                    detail=step.detail,
                    link=step.link,
                    link_label=step.link_label,
                )
                for step in r.steps
            ],
            notices=list(r.notices),
            contacts=list(r.contacts),
            reminder_year=r.reminder_year,
        )

    return StateEnvelope(
        # A finished flow has no session left, so it is not "active" -- but the
        # result travels in this same response and the client keeps it.
        active=snapshot.question is not None,
        language=snapshot.language.value,
        question=question,
        result=result,
        answered=snapshot.answered,
        total=snapshot.total,
        labels=_labels(snapshot.language),
    )


async def _record(snapshot: Snapshot) -> None:
    """Write the anonymised outcome, exactly once, when a flow completes.

    Once because `_finish` deletes the session in the same call that produces
    the result, so no later request can produce a second one for the same flow.
    Awaited rather than backgrounded only because it is a single INSERT that
    swallows its own failures; nothing here can delay or break the response.
    """
    if snapshot.result is None:
        return
    await outcomes.record(
        EligibilityEngine.outcome_of(snapshot.result, snapshot.language)
    )


@router.get("/state", response_model=StateEnvelope)
def check_state(
    thread_id: str = Query(min_length=1, max_length=128),
    language: str = Query(default="en"),
) -> StateEnvelope:
    """The flow in progress, if any.

    Called on load, which is what makes a refresh mid-flow a non-event. Returns
    `active: false` with no result for a flow that has finished: the result
    lives in the client's own storage from then on, the same place the
    transcript does.

    `language` is only used to label an inactive envelope; a running flow
    answers in the language it was started in.
    """
    snapshot = get_engine().state(thread_id)
    return _envelope(snapshot, _language(language))


@router.post("/start", response_model=StateEnvelope)
def start_check(body: StartBody) -> StateEnvelope:
    language = _language(body.language)
    try:
        snapshot = get_engine().start(body.thread_id, language)
    except EligibilityError as error:
        raise _fail(error) from None
    return _envelope(snapshot, language)


@router.post("/answer", response_model=StateEnvelope)
async def answer(body: AnswerBody) -> StateEnvelope:
    engine = get_engine()
    try:
        snapshot = engine.answer(body.thread_id, body.value)
    except EligibilityError as error:
        raise _fail(error) from None

    await _record(snapshot)
    return _envelope(snapshot, snapshot.language)


@router.post("/back", response_model=StateEnvelope)
def back(body: ThreadBody) -> StateEnvelope:
    try:
        snapshot = get_engine().back(body.thread_id)
    except EligibilityError as error:
        raise _fail(error) from None
    return _envelope(snapshot, snapshot.language)


@router.post("/restart", response_model=StateEnvelope)
def restart(body: RestartBody) -> StateEnvelope:
    language = _language(body.language) if body.language else None
    try:
        snapshot = get_engine().restart(body.thread_id, language)
    except EligibilityError as error:
        raise _fail(error) from None
    return _envelope(snapshot, snapshot.language)


@router.post("/quit", response_model=StateEnvelope)
def quit_check(body: ThreadBody) -> StateEnvelope:
    """Leave without finishing.

    Always succeeds, including when nothing is running: "stop this" must never
    be able to fail. No outcome is recorded — an abandoned flow has no verdict.
    """
    get_engine().quit(body.thread_id)
    return _envelope(None, Language.EN)
