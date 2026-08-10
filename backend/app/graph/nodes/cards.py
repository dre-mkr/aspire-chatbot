"""The turns answered before anything else runs.

Three cards -- two of them the ones v1 handled with tools -- and one plain
sentence:

    eligibility  -- the audited six-question flow, `app/eligibility`
    game         -- one of the real game components, `app/games`
    signup       -- the account wizard, for somebody who needs an account
                    before they can have an application; see `_open_signup`
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
    wants_account,
    wants_eligibility,
    wants_game,
    wants_human,
    wants_registration,
)
from app.graph.state import AspireState
from app.schemas.directives import (
    EligibilityDirective,
    SignupDirective,
    directive_payload,
)

logger = logging.getLogger(__name__)

#: Locales the eligibility card has copy for. Anything else opens in English,
#: which is what the card itself falls back to.
_CARD_LOCALES = frozenset({"en", "es", "fr"})

#: Either of these means the caller has somewhere to register.
_REGISTRATION_AGENTS = frozenset({"register_agent", "register_agent_step1"})

#: Who is reading, for the purpose of answering "I want to register".
#:
#: Not the persona and not the band, but the one distinction the ANSWER turns
#: on: whether the reader should be fetching an adult, or is one.
def _audience(persona: str, age_band: str) -> str:
    """`child`, `educator`, or `unaccompanied`.

    `stella` and Orion's younger band are children and are told to ask a
    grown-up. `nova` is a teacher, who is not going to fetch one. Orion 16-18 is
    neither: old enough that "ask your parent" is the wrong sentence, not
    granted registration on their own account.

    Falls to `unaccompanied` for anything unrecognised, which is the reading
    that assumes least about the person: it explains the situation and names
    routes outside this chat, rather than instructing them to go and find an
    adult.
    """
    if persona == "nova":
        return "educator"
    if persona == "stella" or age_band in ("5-8", "9-12", "13-15"):
        return "child"
    return "unaccompanied"


#: What somebody who cannot register is told, by audience and locale.
#:
#: Says who does it and what to do next. It does NOT say "you are not allowed",
#: because the reader is usually a parent who picked the wrong assistant from a
#: menu, and a refusal is a worse answer than a direction.
#:
#: ## Why this is keyed on the reader and not only on the locale
#:
#: It used to be one paragraph for everybody, addressed to a child: "Ask YOURS
#: to open ASPIRE and choose Aurora." Two things were wrong with sending that to
#: everyone who lacks a registration agent, and the second is the serious one.
#:
#: It was addressed to the wrong person. The message a 16-18 account most often
#: triggers it with is "i want to register my daughter" -- somebody speaking as
#: a parent, told to go and ask their parent.
#:
#: And it instructed the reader to do something the server refuses. Aurora
#: carries `register_agent`, so `account._narrowing` rejects a request for it
#: from any child or teen band; the picker then silently keeps showing Aurora
#: while the session runs as Orion. Observed:
#:
#:     WARNING app.api.stream: Refused a request for persona 'aurora'
#:     on a 16-18 band session.
#:
#: So the reader followed the instruction, watched nothing happen, and got the
#: same paragraph again. NOTHING here may name a persona the reader cannot
#: select -- the only audience that could act on "choose Aurora" is one that
#: already has `register_agent` and therefore never reaches this node.
_REGISTRATION_HELP: dict[str, dict[str, str]] = {
    "child": {
        "en": (
            "An ASPIRE application is filled in by a parent or guardian. Ask "
            "yours to sign in with their own ASPIRE account and start it there "
            "-- or they can go to aspire.gov.kn or any branch."
        ),
        "es": (
            "La solicitud de ASPIRE la completa un padre, madre o tutor. Pídele "
            "que inicie sesión con su propia cuenta de ASPIRE y la empiece ahí, "
            "o que vaya a aspire.gov.kn o a una sucursal."
        ),
        "fr": (
            "Une demande ASPIRE est remplie par un parent ou tuteur. Demande-lui "
            "de se connecter avec son propre compte ASPIRE et de la commencer "
            "là, ou d'aller sur aspire.gov.kn ou dans une agence."
        ),
    },
    "unaccompanied": {
        "en": (
            "An application through this assistant is completed on a parent or "
            "guardian's own account, and this one is not registered as one. If "
            "you are applying for a child, create a guardian account and start "
            "there. You can also apply at aspire.gov.kn or any branch."
        ),
        "es": (
            "Una solicitud hecha con este asistente se completa desde la cuenta "
            "de un padre, madre o tutor, y esta no lo es. Si solicitas para un "
            "menor, crea una cuenta de tutor y empieza ahí. También puedes "
            "solicitar en aspire.gov.kn o en una sucursal."
        ),
        "fr": (
            "Une demande faite avec cet assistant se remplit depuis le compte "
            "d'un parent ou tuteur, et celui-ci n'en est pas un. Si vous "
            "postulez pour un enfant, créez un compte tuteur et commencez là. "
            "Vous pouvez aussi postuler sur aspire.gov.kn ou dans une agence."
        ),
    },
    "educator": {
        "en": (
            "A child is enrolled by their own parent or guardian rather than by "
            "a school, so this cannot be completed from a teacher account. Point "
            "the family at aspire.gov.kn or any branch, or ask them to start it "
            "from their own ASPIRE account."
        ),
        "es": (
            "A un menor lo inscribe su padre, madre o tutor, no la escuela, así "
            "que esto no se puede completar desde una cuenta docente. Indica a "
            "la familia aspire.gov.kn o una sucursal, o pídeles que la empiecen "
            "desde su propia cuenta de ASPIRE."
        ),
        "fr": (
            "Un enfant est inscrit par son parent ou tuteur et non par l'école, "
            "donc cela ne peut pas se faire depuis un compte enseignant. "
            "Orientez la famille vers aspire.gov.kn ou une agence, ou demandez-"
            "leur de commencer depuis leur propre compte ASPIRE."
        ),
    },
}

#: Chips that lead somewhere the reader can actually get to.
#:
#: "Who registers a child?" is the highest-scoring registration question in the
#: corpus at 0.759 cosine, which is the point: a chip that lands back on the
#: grounding floor would send the reader round the same loop that brought them
#: here.
#:
#: The adult audiences get "Create a guardian account" in its place, and that
#: one is not a retrieval question at all -- `intents.wants_account` matches it
#: in this same node and opens the sign-up flow, so it never reaches the
#: grounding floor to be judged by it. It is offered ONLY to the audiences the
#: copy above tells to create an account; a child tapping it would be starting
#: an account this product will not give them.
_REGISTRATION_CHIPS: dict[str, dict[str, list[str]]] = {
    "child": {
        "en": ["Who registers a child?", "What documents are needed?"],
        "es": ["¿Quién registra?", "¿Qué documentos?"],
        "fr": ["Qui inscrit l'enfant ?", "Quels documents ?"],
    },
    "unaccompanied": {
        "en": ["Create a guardian account", "What documents are needed?"],
        "es": ["Crear una cuenta de tutor", "¿Qué documentos?"],
        "fr": ["Créer un compte tuteur", "Quels documents ?"],
    },
    "educator": {
        "en": ["Who registers a child?", "What documents are needed?"],
        "es": ["¿Quién registra?", "¿Qué documentos?"],
        "fr": ["Qui inscrit l'enfant ?", "Quels documents ?"],
    },
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

        # Before the registration help, because it is the more specific of the
        # two: "create a guardian account" is an account request that also reads
        # as registration intent, and the account is the step that comes first.
        card = _open_signup(state, message)
        if card is not None:
            return card

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


def _open_signup(state: AspireState, message: str) -> dict[str, Any] | None:
    """"Create a guardian account" -- open the sign-up wizard.

    Unlike `_registration_help` this is offered to EVERY audience, including the
    ones that can already register. An account request is not a registration
    request and having `register_agent` does not answer it: an adult with a
    participant account who wants a guardian one is asking a real question, and
    routing them into the application flow would answer a different one.

    ## The role is derived here, not asked for and not inferred by a model

    From the reader's audience, which is itself derived from claims the server
    minted. A teacher gets the educator branch, everybody else the guardian one
    -- because the reason a chat produces this request is almost always the
    sentence that could not be completed, and that sentence is "I want to
    register my child".

    A child asking to create an account gets the wizard with NO role
    pre-selected, so they land on the ordinary participant branch and the
    under-13 rules apply. Opening the guardian branch for them would be
    suggesting a shape of account they cannot hold.

    ## Prose, unlike the eligibility card

    One short sentence, because unlike the eligibility card this directive
    navigates away from the conversation. A card that silently replaces what
    somebody was reading needs to have said why.
    """
    if not wants_account(message):
        return None

    persona = str(state.get("persona") or "")
    age_band = str(state.get("age_band") or "")
    audience = _audience(persona, age_band)

    locale = str(state.get("locale") or "en")
    if locale not in _SIGNUP_INTRO:
        locale = "en"

    role: str | None
    if audience == "child":
        role = None
    elif audience == "educator":
        role = "educator"
    else:
        role = "guardian"

    logger.info(
        "signup card opened persona=%s band=%s audience=%s role=%s",
        persona,
        age_band,
        audience,
        role,
    )
    return {
        "messages": [AIMessage(content=_SIGNUP_INTRO[locale])],
        "ui_directives": [
            directive_payload(SignupDirective(role=role))  # type: ignore[arg-type]
        ],
        "active_agent": state.get("active_agent") or "qa_agent",
        "safety_flags": {"card": "signup"},
    }


#: The one sentence that goes with the sign-up card.
#:
#: Under the 5-8 band's 35-word cap, so `safety_out` never re-prompts on it.
_SIGNUP_INTRO: dict[str, str] = {
    "en": "Let's set that up — the form is on screen.",
    "es": "Vamos a crearla: el formulario está en pantalla.",
    "fr": "Créons-le : le formulaire est à l'écran.",
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

    persona = str(state.get("persona") or "")
    age_band = str(state.get("age_band") or "")
    audience = _audience(persona, age_band)

    locale = str(state.get("locale") or "en")
    if locale not in _REGISTRATION_HELP[audience]:
        locale = "en"

    logger.info(
        "Registration intent from persona=%s band=%s, which cannot register; "
        "answering the %s audience directly rather than escalating.",
        persona,
        age_band,
        audience,
    )
    return {
        "messages": [AIMessage(content=_REGISTRATION_HELP[audience][locale])],
        "quick_replies": list(_REGISTRATION_CHIPS[audience][locale]),
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


