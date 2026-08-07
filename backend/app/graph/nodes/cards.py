"""The turns answered before anything else runs.

Two cards, which are the two v1 handled with tools, and one plain sentence:

    eligibility  -- the audited six-question flow, `app/eligibility`
    game         -- one of the real game components, `app/games`
    registration -- for the personas that have no registration agent to route
                    to. Prose rather than a card, because there is nothing to
                    hand over to; see `_registration_help`.

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

from langchain_core.messages import AIMessage

from app.agents.escalation.contract import EscalationReason
from app.graph.nodes.intents import (
    is_complaint,
    named_game,
    wants_eligibility,
    wants_game,
    wants_human,
    wants_registration,
)
from app.graph.state import AspireState
from app.schemas.directives import EligibilityDirective, directive_payload

logger = logging.getLogger(__name__)

#: Locales the eligibility card has copy for. Anything else opens in English,
#: which is what the card itself falls back to.
_CARD_LOCALES = frozenset({"en", "es", "fr"})

#: Either of these means the caller has somewhere to register.
_REGISTRATION_AGENTS = frozenset({"register_agent", "register_agent_step1"})

#: What somebody who cannot register is told, by locale.
#:
#: Says who does it and what to do next, in two sentences. It does NOT say
#: "you are not allowed", because the reader is usually a parent who picked the
#: wrong assistant from a menu, and a refusal is a worse answer than a direction.
_REGISTRATION_HELP: dict[str, str] = {
    "en": (
        "An ASPIRE application is completed by a parent or guardian. Ask yours "
        "to open ASPIRE and choose Aurora, the assistant for parents and "
        "guardians -- or start at aspire.gov.kn or any branch."
    ),
    "es": (
        "La solicitud de ASPIRE la completa un padre, madre o tutor. Pide que "
        "abran ASPIRE y elijan Aurora, el asistente para familias, o empiecen "
        "en aspire.gov.kn o en una sucursal."
    ),
    "fr": (
        "Une demande ASPIRE est remplie par un parent ou tuteur. Demande-lui "
        "d'ouvrir ASPIRE et de choisir Aurora, l'assistant des familles, ou de "
        "commencer sur aspire.gov.kn ou dans une agence."
    ),
}

#: Chips that lead somewhere the knowledge base can actually answer.
#:
#: "Who registers a child?" is the highest-scoring registration question in the
#: corpus at 0.759 cosine, which is the point: a chip that lands back on the
#: grounding floor would send the reader round the same loop that brought them
#: here.
_REGISTRATION_CHIPS: dict[str, list[str]] = {
    "en": ["Who registers a child?", "What documents are needed?"],
    "es": ["¿Quién registra?", "¿Qué documentos?"],
    "fr": ["Qui inscrit l'enfant ?", "Quels documents ?"],
}


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

        # Before the registration help and before the router: somebody who has
        # asked for a person is not asking anything else.
        asked = _asked_for_a_person(message)
        if asked is not None:
            return asked

        reply = _registration_help(state, message)
        if reply is not None:
            return reply

        return {}

    return intent_gate


def _asked_for_a_person(message: str) -> dict[str, Any] | None:
    """An explicit request for a human, recognised without a model.

    ## Why this is a matcher and not a router destination

    `escalate_agent` used to be one of the options the classifier chose between,
    described as "they asked for one, they are upset or in difficulty, or the
    question is outside what this assistant can answer". One line, three
    situations, the last of which is a catch-all -- and a small model handed a
    catch-all next to five topic-shaped agents uses it as one. Track E.2 removes
    that option. This recovers the half of it that was a real signal.

    ## Why a matcher rather than a tool the agents call

    Because of who has to be able to reach it. Stella's whole agent set is
    `learn_agent` and `escalate_agent` (`graph/access.py:120`), and the lesson
    machine makes no tool calls at all -- every node in it is deterministic. A
    tool-only design would mean a five-year-old's request for a person depends
    on a model choosing to call a function, in an agent that never calls one.
    Agents that DO make model calls get the tool as well; this is the floor
    under them, not a replacement for them.

    Returns no `AIMessage`. `escalate_agent` writes the reply, because it is the
    node that knows the ticket reference and the ETA.
    """
    # Complaint first. The two overlap -- "wrong for three weeks and i want a
    # manager" is both -- and a complaint triages high in its own queue while a
    # request for a person triages normal in the general one. Checking the
    # request first would downgrade every complaint that names a human, which is
    # most of them.
    if is_complaint(message):
        reason = EscalationReason.COMPLAINT
    elif wants_human(message):
        reason = EscalationReason.USER_REQUESTED_HUMAN
    else:
        return None

    logger.info("Escalating as %s without the router.", reason.value)
    return {
        "escalation_reason": reason.value,
        "safety_flags": {"asked_for_human": True},
    }


def _registration_help(state: AspireState, message: str) -> dict[str, Any] | None:
    """"I want to register my child", from somebody who cannot.

    Returns None -- and costs nothing -- for everybody who CAN reach a
    registration agent, which is the common case and the one that must be
    untouched: a guardian saying this still routes to `register_agent` exactly
    as before. `allowed_agents` is already in state; `guard` runs two nodes
    upstream.

    ## Why this is here rather than in the knowledge base

    Registration is guardian-only, so `orion` 16-18 and `nova` can express the
    intent and have no handler for it. The classifier does the sensible thing
    with what it is offered and picks `qa_agent`, which is the wrong shape of
    agent for the input: Q&A answers questions by attributing them to a corpus
    row, and "I want to register my child" is not a question. Nothing scores
    above the grounding floor, `ground_check` hands off to `escalate_agent`, and
    the reader gets a reference number and a promise of a call back.

    Measured, from the ticket that prompted this:

        i want to register my child -- The closest chunk scored 0.519,
        below the 0.550 floor.

    Answering it here costs no model call, no retrieval and no ticket, and it
    reaches every persona that cannot register rather than one row of the table.

    ## Why it produces prose, unlike the two cards above

    Those hand over to a component that speaks for itself. This has nothing to
    hand over to -- the whole point is that there is no agent for it -- so the
    node says the sentence. `_after_cards` already routes a `cards` turn that
    produced a message and chips straight to `safety_out`, which is where the
    band cap and the link stripper get their say, so no routing changes.
    """
    allowed = set(state.get("allowed_agents") or [])
    if allowed & _REGISTRATION_AGENTS:
        return None
    if not wants_registration(message):
        return None

    locale = str(state.get("locale") or "en")
    if locale not in _REGISTRATION_HELP:
        locale = "en"

    logger.info(
        "Registration intent from %s, which cannot register; answering directly "
        "rather than escalating.",
        state.get("persona"),
    )
    return {
        "messages": [AIMessage(content=_REGISTRATION_HELP[locale])],
        "quick_replies": list(_REGISTRATION_CHIPS[locale]),
    }


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


