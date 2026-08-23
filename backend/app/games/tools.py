"""The agent's only route into the games."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.games.engine import GameError, get_engine
from app.games.models import Language, Persona

logger = logging.getLogger(__name__)


def _configurable(config: RunnableConfig) -> dict[str, Any]:
    return dict(config.get("configurable") or {})


def _session_id(config: RunnableConfig) -> str:
    """The conversation's thread id, set by /chat. Never model-supplied."""
    session_id = _configurable(config).get("thread_id")
    if not session_id:
        # Should be impossible: main.py always sets a thread_id before invoking.
        raise GameError("This conversation has no session to attach a game to.")
    return str(session_id)


def _persona(config: RunnableConfig) -> Persona | None:
    raw = _configurable(config).get("persona")
    if not raw:
        return None
    try:
        return Persona(str(raw))
    except ValueError:
        logger.warning("Ignoring unknown persona %r from request config.", raw)
        return None


def _language(value: str | None, config: RunnableConfig) -> Language:
    raw = value or _configurable(config).get("language") or "en"
    try:
        return Language(str(raw).lower())
    except ValueError:
        return Language.EN


def _declined(error: GameError) -> dict[str, Any]:
    return {"ok": False, "reason": error.reason, "detail": str(error)}


def _prompt_out(prompt: Any) -> dict[str, Any]:
    """The next item, flattened onto the response the model reads."""
    if prompt is None:
        return {}
    out: dict[str, Any] = {
        "next_kind": prompt.kind.value,
        "next_text": prompt.text,
        "position": prompt.position,
        "total": prompt.total,
    }
    if prompt.choices:
        out["choices"] = list(prompt.choices)
    return out


@tool
def list_games(config: RunnableConfig, language: str | None = None) -> dict[str, Any]:
    """List the learning games available in this chat.

    Use when someone asks what games there are, or whether games exist. Report
    only what this returns; never describe a game that is not in the list, and
    never promise a feature it does not report (`supports_hints` is the only one
    that varies).
    """
    engine = get_engine()
    infos = engine.list_games(_language(language, config))
    return {
        "ok": True,
        "games": [
            {
                "id": info.game_type,
                "name": info.display_name,
                "items": info.items,
                "supports_hints": info.supports_hints,
                "languages": info.languages,
            }
            for info in infos
        ],
    }


@tool
def start_game(
    config: RunnableConfig,
    game_type: str = "word_scramble",
    language: str | None = None,
) -> dict[str, Any]:
    """Start a learning game. Call this ONLY when the user has asked to play.

    Never offer a game unprompted and never start one to fill a pause. Answering
    a question is not an invitation to play.

    `game_type` is "word_scramble" (unscramble a word, clues available) or
    "true_false" (judge a statement, then read why). Call `list_games` first if
    you are unsure what exists. If the user just says "a game" without choosing,
    ask which they would like rather than picking for them.

    ON SUCCESS, REPLY WITH NOTHING. The card that appears already shows the
    item, its instructions and its controls, so any sentence you add puts the
    same puzzle on screen a second time. Do not greet, do not introduce, and do
    not repeat `text`. An empty reply is the correct reply.

    `kind` says whether the item is scrambled letters or a statement, and `text`
    is the item itself -- both are for the card, not for you to read out. Never
    reorder a scramble's letters, reword a statement, correct either, or answer
    it yourself.

    If it DECLINES there is no card, so tell the user plainly why:
      not_available_for_persona - the games are for ASPIRE account holders
      no_set_for_language       - the games are not in that language YET. The
                                  `message` is already written for the reader and
                                  already in their language: pass it on as it is,
                                  do not translate it, do not soften it, and do
                                  not turn it into an apology. It tells them the
                                  games are coming and that English works now.
      already_running           - a game is already in progress here
    """
    try:
        result = get_engine().start(
            session_id=_session_id(config),
            game_type=game_type,
            language=_language(language, config),
            persona=_persona(config),
        )
    except GameError as error:
        return _declined(error)

    return {
        "ok": True,
        "started": True,
        "game": result.game_type,
        "name": result.display_name,
        "kind": result.prompt.kind.value,
        "text": result.prompt.text,
        "position": result.prompt.position,
        "total": result.prompt.total,
        **({"choices": list(result.prompt.choices)} if result.prompt.choices else {}),
    }


@tool
def submit_answer(answer: str, config: RunnableConfig) -> dict[str, Any]:
    """Check the user's answer to the current item.

    Pass exactly what they said. The engine handles case, spacing, punctuation,
    accents and small typos on a scramble, and reads true/false/T/F on a
    statement. You do not decide whether an answer is right, and you must not
    judge it yourself before or after calling this.

    Three outcomes:

    - `correct` true. You also get `teaching_note` â€” for a scramble the word's
      meaning, for true/false ECCB's own explanation. Deliver it in your own
      voice as what the idea means inside ASPIRE, not a dictionary definition.
      Never rewrite or shorten an explanation you are given; it is the point of
      the game.
    - `correct` false with a `reveal`. The item is finished and the answer is in
      `reveal.answer`. Say so kindly, teach from the explanation, move on. Never
      frame it as failing.
    - `correct` false with NO `reveal`. The item is still open â€” a scramble they
      can retry. You do not know the answer, so do not guess at it, hint at its
      letters, or say how close they were. Encourage another go, or offer a clue.

    If `unreadable` comes back, the answer could not be read at all â€” say what
    it says and ask again. That is not a wrong answer and nothing was spent.
    """
    try:
        result = get_engine().submit(_session_id(config), answer)
    except GameError as error:
        return _declined(error)

    if result.unreadable:
        return {"ok": True, "unreadable": result.unreadable, "correct": False}

    payload: dict[str, Any] = {
        "ok": True,
        "correct": result.correct,
        "attempts": result.attempts,
    }
    if result.reveal is None:
        # Item still live. Nothing about it may go back to the model.
        return payload

    payload["teaching_note"] = result.teaching_note
    payload["revealed_answer"] = result.reveal.answer
    payload["finished"] = result.finished
    payload.update(_prompt_out(result.next_prompt))
    if result.summary is not None:
        payload["summary"] = {
            "solved": result.summary.solved,
            "missed": result.summary.missed,
            "skipped": result.summary.skipped,
            "total": result.summary.total,
        }
    return payload


@tool
def get_hint(config: RunnableConfig) -> dict[str, Any]:
    """Get the next clue for the current item.

    Only some games have clues. True or false does not â€” a clue on a
    true-or-false statement would be the answer, so this declines with
    `hints_not_available`. Say that plainly and offer `skip_word` instead; do
    not invent a clue of your own, and do not hint at the verdict.

    Where clues exist they step up: the first letter, then the length and a
    category, then the word's meaning. Pass the clue on warmly in your own
    words. Never add a stronger one and never name the answer â€” you are not
    told it.

    Asking again past the last clue gives up on the item: you will get
    `revealed` with the answer and its meaning, and the game moves on. Frame
    that as learning something new, never as failing.
    """
    try:
        result = get_engine().hint(_session_id(config))
    except GameError as error:
        return _declined(error)

    if result.reveal is None:
        return {
            "ok": True,
            "revealed": False,
            "hint": result.text,
            "level": result.level,
        }

    payload: dict[str, Any] = {
        "ok": True,
        "revealed": True,
        "answer": result.reveal.answer,
        "explanation": result.reveal.explanation,
        "finished": result.finished,
    }
    payload.update(_prompt_out(result.next_prompt))
    return payload


@tool
def skip_word(config: RunnableConfig) -> dict[str, Any]:
    """Give up on the current item and move to the next one.

    Call this when the user asks to skip, to pass, or to move on. You get the
    answer and its explanation: teach it briefly and kindly, then present the
    next item. Skipping is a normal move, not a failure, and must never be
    discouraged or made to feel counted.
    """
    try:
        result = get_engine().skip(_session_id(config))
    except GameError as error:
        return _declined(error)

    payload: dict[str, Any] = {
        "ok": True,
        "revealed": True,
        "answer": result.reveal.answer,
        "explanation": result.reveal.explanation,
        "finished": result.finished,
    }
    payload.update(_prompt_out(result.next_prompt))
    if result.summary is not None:
        payload["summary"] = {
            "solved": result.summary.solved,
            "missed": result.summary.missed,
            "skipped": result.summary.skipped,
            "total": result.summary.total,
        }
    return payload


@tool
def quit_game(config: RunnableConfig) -> dict[str, Any]:
    """End the game now.

    Call this on ANY clear signal the user is done - "stop", "I'm bored", "this
    is too hard", or plain frustration. Never require a particular word to leave
    and never ask them to confirm twice. Close warmly, mention what they got, and
    make it obvious they can play again whenever they like.
    """
    try:
        summary = get_engine().quit(_session_id(config))
    except GameError as error:
        return _declined(error)

    return {
        "ok": True,
        "ended": True,
        "solved": summary.solved,
        "missed": summary.missed,
        "skipped": summary.skipped,
        "total": summary.total,
        "hints_used": summary.hints_used,
        "duration_seconds": summary.duration_seconds,
    }


GAME_TOOLS = [
    list_games,
    start_game,
    submit_answer,
    get_hint,
    skip_word,
    quit_game,
]
