"""The turns where the answer is a card, decided before anything else runs.

Two of them, and they are the two v1 handled with tools:

    eligibility  -- the audited six-question flow, `app/eligibility`
    game         -- one of the real game components, `app/games`

## Ahead of the classifier, not inside an agent

This node sits between `safety_in` and `classify`, and that position is
load-bearing rather than tidy. It lived inside the Q&A subgraph first, which
looked reasonable and did not work: the classifier is free to route "let's play
a game" to `learn_agent` or `escalate_agent`, and a matcher living downstream of
it simply never runs on the turns it exists for. Measured against the live
service -- "let's play a game" escalated to a human, and "can we play true or
false" started a lesson instead.

Recognising a card turn is a ROUTING decision. It belongs where routing happens.

## The prose is not dropped. It is never produced.

v1 called the model, let it decide to call a card tool, and then *discarded* the
sentences it had written alongside the card -- `app/streaming.py`'s `TurnBuffer`
exists almost entirely for that, and it is the half of the design that does not
depend on the model complying with a prompt.

That whole apparatus is unnecessary here. The card is decided by
`intents.wants_eligibility` / `intents.wants_game` before retrieval, this node
returns a directive and NO `AIMessage`, and `safety_out` sees a turn with
nothing outbound to gate. There is no narration to suppress because no model was
asked to write any, and no `SILENT_TOOLS` list to keep in agreement with the
tool registry.

## What a card turn leaves in the transcript

Nothing, in `state.messages`. The history line that stops the model reading a
question followed by silence is written by the persistence layer
(`app/turn.py`), from the directive -- same text v1 wrote, same reasons, and
still carrying no puzzle, no answer, no verdict and no rule.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.nodes.intents import named_game, wants_eligibility, wants_game
from app.graph.state import AspireState
from app.schemas.directives import EligibilityDirective, directive_payload

logger = logging.getLogger(__name__)

#: Locales the eligibility card has copy for. Anything else opens in English,
#: which is what the card itself falls back to.
_CARD_LOCALES = frozenset({"en", "es", "fr"})


def _last_human(state: AspireState) -> str:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) == "human":
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
    return ""


def make_intent_gate(
    *,
    start_check=None,
    check_running=None,
    eligibility_on=None,
    games_on=None,
):
    """The node that decides whether this turn is a card.

    Every dependency is injected and every one of them has a real default, for
    the same reason the retrieval dependencies are: the eligibility engine and
    the games engine are separately switchable modules, and a subgraph that
    reached into them directly could not be built in a deployment that has
    either turned off.
    """

    async def intent_gate(state: AspireState) -> dict[str, Any]:
        message = _last_human(state)
        if not message.strip():
            return {}

        if _eligibility_available(eligibility_on) and wants_eligibility(message):
            card = _open_eligibility(state, start_check, check_running)
            if card is not None:
                return card

        if _games_available(games_on) and wants_game(message):
            card = _open_game(state, message)
            if card is not None:
                return card

        return {}

    return intent_gate


def _eligibility_available(override) -> bool:
    if override is not None:
        return bool(override())
    try:
        from app.eligibility import eligibility_enabled

        return eligibility_enabled()
    except Exception:  # pragma: no cover - module absent in a trimmed build
        return False


def _games_available(override) -> bool:
    if override is not None:
        return bool(override())
    try:
        from app.games import games_enabled

        return games_enabled()
    except Exception:  # pragma: no cover
        return False


def _open_eligibility(
    state: AspireState, start_check, check_running
) -> dict[str, Any] | None:
    """Start the flow and emit the card, or None to answer normally.

    None on `already_running` rather than an error, and that matters: somebody
    who asks "so can I join?" while the card is already on screen has asked a
    real question, and restarting the flow they are half-way through would throw
    away the four answers they have already tapped.
    """
    session_id = str(state.get("session_id") or "")
    if not session_id:
        logger.warning("An eligibility card was wanted but the turn has no session id.")
        return None

    locale = str(state.get("locale") or "en")
    if locale not in _CARD_LOCALES:
        locale = "en"

    if check_running is None or start_check is None:
        from app.eligibility.engine import EligibilityError, get_engine
        from app.eligibility.models import Language

        engine = get_engine()
        try:
            if engine.state(session_id) is not None:
                logger.info(
                    "A check is already open for %s; answering the question instead.",
                    session_id,
                )
                return None
            engine.start(session_id, Language(locale))
        except EligibilityError as error:
            logger.info("The eligibility check declined to start: %s", error)
            return None
        except Exception:
            # A card that cannot open must not take the answer down with it.
            logger.warning("Could not open the eligibility check.", exc_info=True)
            return None
    else:
        if check_running(session_id):
            return None
        start_check(session_id, locale)

    logger.info("eligibility card opened for session=%s locale=%s", session_id, locale)
    return {
        # No message. See the module docstring: the card is the whole turn.
        "ui_directives": [
            directive_payload(EligibilityDirective(language=locale))  # type: ignore[arg-type]
        ],
        "active_agent": state.get("active_agent") or "qa_agent",
        "safety_flags": {"card": "eligibility"},
    }


def _open_game(state: AspireState, message: str) -> dict[str, Any] | None:
    """Emit a game directive, ask which game, or decline to the band.

    Three outcomes and all three are turns:

      * they named a game their band may play  → the card
      * they asked to play without choosing    → chips listing what they may play
      * their band may play nothing            → None, and the question is
                                                 answered from the corpus

    The band gate is `learn.tools.games.available_for`, which is the same
    function the learning agent uses. Two band tables would be two band tables
    to keep in agreement, and the one that drifted would be the one offering a
    spelling game to a five-year-old.
    """
    from app.agents.learn.tools.games import available_for, launch_game

    band = str(state.get("age_band") or "adult")
    playable = available_for(band)
    if not playable:
        logger.info("No games are offered to the %s band; answering normally.", band)
        return None

    chosen = named_game(message)
    if chosen is None:
        return {
            "quick_replies": [_GAME_LABELS.get(name, name) for name in playable],
            "messages": [_ask_which(band)],
            "active_agent": state.get("active_agent") or "qa_agent",
        }

    learning = state.get("learning") or {}
    concept = str(learning.get("concept_id") or "saving_basics")
    directive = launch_game(chosen, concept, 1, age_band=band)  # type: ignore[arg-type]
    if directive is None:
        # The band bars the one they named. Offer what they can play rather than
        # saying no and stopping.
        return {
            "quick_replies": [_GAME_LABELS.get(name, name) for name in playable],
            "messages": [_ask_which(band)],
            "active_agent": state.get("active_agent") or "qa_agent",
        }

    logger.info("game card opened game=%s concept=%s band=%s", chosen, concept, band)
    return {
        "ui_directives": [directive],
        "active_agent": state.get("active_agent") or "qa_agent",
        "safety_flags": {"card": "game"},
    }


#: What each game is called to a reader. The engine's own identifiers
#: (`word_scramble`) are not copy.
_GAME_LABELS: dict[str, str] = {
    "true_false": "True or false",
    "scramble": "Word scramble",
    "millionaire": "Millionaire",
}


def _ask_which(band: str):
    """Ask which game, in the band's voice. Never picks one on their behalf.

    Under the 5-8 word cap (35 words) by a wide margin, so this sentence is
    never the thing that triggers a re-prompt.
    """
    from langchain_core.messages import AIMessage

    if band == "5-8":
        return AIMessage(content="Yes! Which one do you want to play?")
    return AIMessage(content="Sure — which one would you like to play?")


