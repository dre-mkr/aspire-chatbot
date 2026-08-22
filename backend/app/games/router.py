"""HTTP surface for the games layer."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.games.engine import (
    GameAlreadyRunning,
    GameError,
    GameNotRunning,
    HintsNotAvailable,
    NoContentAvailable,
    PersonaNotEligible,
    UnknownGameType,
    get_engine,
)
from app.games.models import GameState, Language, Persona, Reveal, Summary
from app.games.schemas import (
    BulletOut,
    ClosingOut,
    GameInfoOut,
    PromptOut,
    GameListOut,
    GameStateEnvelope,
    GameStateOut,
    HintOut,
    RevealOut,
    SkipOut,
    StartBody,
    SubmitBody,
    SubmitOut,
    SummaryOut,
    ThreadBody,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/games", tags=["games"])

# Expected conditions, mapped to the status code that actually means them.
_STATUS = {
    GameNotRunning: 404,
    GameAlreadyRunning: 409,
    PersonaNotEligible: 403,
    NoContentAvailable: 422,
    UnknownGameType: 422,
    # The request is well formed and the game is running; this game simply has no hints to give.
    HintsNotAvailable: 422,
}


def _fail(error: GameError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(type(error), 400),
        detail={"reason": error.reason, "message": str(error)},
    )


def _language(raw: str) -> Language:
    try:
        return Language(raw.lower())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"reason": "unknown_language", "message": f"No language {raw!r}."},
        ) from None


def _persona(raw: str | None) -> Persona | None:
    """Unknown personas are ignored, not rejected."""
    if not raw:
        return None
    try:
        return Persona(raw.lower())
    except ValueError:
        logger.warning("Ignoring unknown persona %r.", raw)
        return None


def _state_out(state: GameState | None) -> GameStateOut | None:
    if state is None:
        return None
    return GameStateOut(
        game_type=state.game_type,
        display_name=state.display_name,
        prompt=PromptOut(
            kind=state.prompt.kind.value,
            text=state.prompt.text,
            position=state.prompt.position,
            total=state.prompt.total,
            choices=list(state.prompt.choices),
        ),
        supports_hints=state.supports_hints,
        hint_level=state.hint_level,
        max_hint_level=state.max_hint_level,
        hints=list(state.hints),
        attempts=state.attempts,
        solved=state.solved,
        skipped=state.skipped,
        language=state.language.value,
        persona=state.persona.value if state.persona else None,
    )


def _reveal_out(reveal: Reveal | None) -> RevealOut | None:
    if reveal is None:
        return None
    return RevealOut(
        answer=reveal.answer,
        explanation=reveal.explanation,
        takeaway=reveal.takeaway,
        paragraphs=list(reveal.paragraphs),
        bullets=[
            BulletOut(marker=b.marker, label=b.label, text=b.text)
            for b in reveal.bullets
        ],
        after=reveal.after,
        topic=reveal.topic,
        topic_line=reveal.topic_line,
    )


def _summary_out(summary: Summary | None) -> SummaryOut | None:
    if summary is None:
        return None
    return SummaryOut(
        solved=summary.solved,
        missed=summary.missed,
        skipped=summary.skipped,
        total=summary.total,
        hints_used=summary.hints_used,
        duration_seconds=summary.duration_seconds,
        closing=(
            ClosingOut(lead=summary.closing.lead, text=summary.closing.text)
            if summary.closing
            else None
        ),
    )


@router.get("", response_model=GameListOut)
def list_games(language: str = Query(default="en")) -> GameListOut:
    infos = get_engine().list_games(_language(language))
    return GameListOut(
        games=[
            GameInfoOut(
                id=i.game_type,
                name=i.display_name,
                items=i.items,
                supports_hints=i.supports_hints,
                languages=i.languages,
            )
            for i in infos
        ]
    )


@router.get("/state", response_model=GameStateEnvelope)
def game_state(thread_id: str = Query(min_length=1, max_length=128)) -> GameStateEnvelope:
    """The running game, if any."""
    state = _state_out(get_engine().state(thread_id))
    return GameStateEnvelope(active=state is not None, game=state)


@router.post("/start", response_model=GameStateEnvelope)
def start_game(body: StartBody) -> GameStateEnvelope:
    engine = get_engine()
    try:
        engine.start(
            session_id=body.thread_id,
            game_type=body.game_type,
            language=_language(body.language),
            persona=_persona(body.persona),
            age_band=body.age_band,
        )
    except GameError as error:
        raise _fail(error) from None

    state = _state_out(engine.state(body.thread_id))
    return GameStateEnvelope(active=state is not None, game=state)


@router.post("/submit", response_model=SubmitOut)
def submit_answer(body: SubmitBody) -> SubmitOut:
    engine = get_engine()
    try:
        result = engine.submit(body.thread_id, body.answer)
    except GameError as error:
        raise _fail(error) from None

    return SubmitOut(
        correct=result.correct,
        attempts=result.attempts,
        teaching_note=result.teaching_note,
        reveal=_reveal_out(result.reveal),
        unreadable=result.unreadable,
        finished=result.finished,
        game=_state_out(engine.state(body.thread_id)),
        summary=_summary_out(result.summary),
    )


@router.post("/hint", response_model=HintOut)
def get_hint(body: ThreadBody) -> HintOut:
    engine = get_engine()
    try:
        result = engine.hint(body.thread_id)
    except GameError as error:
        raise _fail(error) from None

    reveal = _reveal_out(result.reveal)
    return HintOut(
        revealed=reveal is not None,
        hint=result.text or None,
        level=result.level,
        reveal=reveal,
        finished=result.finished,
        game=_state_out(engine.state(body.thread_id)),
        summary=_summary_out(result.summary),
    )


@router.post("/skip", response_model=SkipOut)
def skip_word(body: ThreadBody) -> SkipOut:
    engine = get_engine()
    try:
        result = engine.skip(body.thread_id)
    except GameError as error:
        raise _fail(error) from None

    return SkipOut(
        reveal=_reveal_out(result.reveal),
        finished=result.finished,
        game=_state_out(engine.state(body.thread_id)),
        summary=_summary_out(result.summary),
    )


@router.post("/quit", response_model=SummaryOut)
def quit_game(body: ThreadBody) -> SummaryOut:
    try:
        summary = get_engine().quit(body.thread_id)
    except GameError as error:
        raise _fail(error) from None
    out = _summary_out(summary)
    assert out is not None
    return out
