"""The turns answered before anything else runs."""

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
    wants_story,
    wants_video,
)
from app.graph.state import AspireState
from app.schemas.directives import (
    EligibilityDirective,
    SignupDirective,
    VideoDirective,
    directive_payload,
)
from app.videos import by_id, requested

logger = logging.getLogger(__name__)

#: Locales the eligibility card has copy for.
_CARD_LOCALES = frozenset({"en", "es", "fr"})

#: Either of these means the caller has somewhere to register.
_REGISTRATION_AGENTS = frozenset({"register_agent", "register_agent_step1"})

#: Who is reading, for the purpose of answering "I want to register".
def _audience(persona: str, age_band: str) -> str:
    """`child`, `educator`, or `unaccompanied`."""
    if persona == "nova":
        return "educator"
    if persona == "stella" or age_band in ("5-8", "9-12", "13-15"):
        return "child"
    return "unaccompanied"


#: What somebody who cannot register is told, by audience and locale.
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


def _holding_agent(state: AspireState) -> str | None:
    """Who the turn is recorded against when a card answers instead of an agent.

    A card is claimed before the router runs, so nothing has chosen an agent this
    turn. Defaulting to the literal "qa_agent" stamped readers with an agent their
    row never granted -- a 9-12 reader was recorded as `qa_agent` when only
    `qa_agent_limited` is theirs -- and, because stickiness ignores an active agent
    outside the allowed list, silently dropped stickiness on the following turn.

    The access matrix orders every row with that reader's default agent first, which
    is exactly the fallback wanted here.
    """
    active = state.get("active_agent")
    if active:
        return str(active)
    allowed = state.get("allowed_agents") or []
    return str(allowed[0]) if allowed else None


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
    """The node that decides whether this turn is a card."""

    async def intent_gate(state: AspireState) -> dict[str, Any]:
        # A continuation turn has no new message; `_last_human` would re-open the previous card.
        flags = state.get("safety_flags") or {}
        if any(flags.get(name) for name in ("widget_interaction", "game_result")):
            return {}

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

        # After the game claim, before the router: taking up an offer made last
        # turn is not a new question, and answering it as one loses the video.
        card = _open_video(state, message)
        if card is not None:
            return card

        # The story flow, both halves. The second half does NOT return a card:
        # it records the topic and lets an agent do the telling, because a story
        # is prose a model writes and not a form this node can fill in.
        card = _story_turn(state, message)
        if card is not None:
            return card

        # Before registration help and the router: asking for a person is not a question to answer.
        asked = _asked_for_a_person(message)
        if asked is not None:
            return asked

        # Before registration help: "create a guardian account" is the more specific intent.
        card = _open_signup(state, message)
        if card is not None:
            return card

        reply = _registration_help(state, message)
        if reply is not None:
            return reply

        return {}

    return intent_gate


#: Suggested subjects, offered as chips when a reader asks for a story.
#:
#: Every one is something the corpus can actually ground a story in, so the
#: topic a tapped chip produces is never one the assistant then has nothing to
#: say about.
_STORY_TOPICS: dict[str, list[str]] = {
    "en": ["Saving up for something", "Needs and wants", "Earning your own money"],
    "es": ["Ahorrar para algo", "Necesidades y deseos", "Ganar tu propio dinero"],
    "fr": ["Économiser pour quelque chose", "Besoins et envies", "Gagner son argent"],
}

_STORY_ASK: dict[str, str] = {
    "en": "I can do that. What would you like the story to be about?",
    "es": "Claro. ¿Sobre qué te gustaría que fuera el cuento?",
    "fr": "Bien sûr. De quoi aimerais-tu que parle l'histoire ?",
}


def _story_turn(state: AspireState, message: str) -> dict[str, Any] | None:
    """Ask what the story should be about, or record the answer.

    Two turns, and the split is what makes the feature safe. Turn one is a card
    -- a question and three chips -- so nothing is generated before the reader
    has said what they want. Turn two is NOT a card: it records the topic and
    returns None, so the router runs and an agent writes the story with the
    story instruction and the story word cap applied.

    A reader who asks for a story and then says something else has changed the
    subject, and the latch is dropped rather than treating their next question
    as a title.
    """
    locale = str(state.get("locale") or "en")
    if locale not in _STORY_ASK:
        locale = "en"

    if state.get("awaiting_story_topic"):
        topic = message.strip()
        # Asking for a story again is not a topic; ask once more rather than
        # writing a story called "tell me a story".
        if not topic or wants_story(message):
            # Still a card: without the flag this falls through to the router
            # and an agent answers "tell me a story" as though it were a
            # question, with the latch still set.
            return {
                "awaiting_story_topic": True,
                "active_agent": _holding_agent(state),
                "messages": [AIMessage(content=_STORY_ASK[locale])],
                "quick_replies": _STORY_TOPICS[locale],
                "safety_flags": {"card": "story_topic"},
            }
        return {"awaiting_story_topic": False, "story_topic": topic[:120]}

    if not wants_story(message):
        return None

    return {
        "awaiting_story_topic": True,
        "active_agent": _holding_agent(state),
        "messages": [AIMessage(content=_STORY_ASK[locale])],
        "quick_replies": _STORY_TOPICS[locale],
        "safety_flags": {"card": "story_topic"},
    }


#: What the reader is asked when they request "a video" without saying which.
#:
#: Titles come from the catalog, never from the model, for the same reason the
#: catalog is server-owned at all: a name invented here is a promise of
#: something that does not exist.
_VIDEO_WHICH: dict[str, str] = {
    "en": "We have two. Which one?",
    "es": "Tenemos dos. ¿Cuál quieres?",
    "fr": "Nous en avons deux. Laquelle ?",
}


def _play(state: AspireState, video: Any) -> dict[str, Any]:
    """The turn that opens the player. One place, so both routes match."""
    return {
        "offered_video": None,
        "active_agent": _holding_agent(state),
        "ui_directives": [
            directive_payload(
                VideoDirective(
                    video_id=video.id,
                    title=video.title,
                    topic=video.topic,
                )
            )
        ],
        "messages": [AIMessage(content=f"Here it is — {video.title}.")],
        "safety_flags": {"card": "video"},
    }


def _open_video(state: AspireState, message: str) -> dict[str, Any] | None:
    """Play a video: the one just offered, or the one just asked for.

    TWO routes reach a player, and until now only the first existed.

    **Accepting an offer.** Three things have to be true, and the last is the
    one that matters: an offer was actually made, this message accepts it, and
    the id still names something in the catalog. That last check is why the
    catalog is server-owned -- an id reaching here from a stale checkpoint, or
    from a client that made one up, resolves to nothing and the turn carries on
    as an ordinary question.

    The offer is cleared either way. A reader who says yes gets the video once;
    a reader who asks something else has moved on, and a "yes" three turns later
    should not reach back and open a player.

    **Asking outright.** `_WATCH` has always matched "show me the video" -- its
    own comment says "accepting an offer, or asking for one outright" -- but
    with no standing offer this function returned None and the request fell
    through to the model, which cannot open a player. That is the measured
    defect: a reader asked six times and got one video, on the single turn an
    offer happened to be standing.

    The request route is NOT filtered by persona. `for_persona` decides what is
    pushed at someone who did not ask; it has nothing to say about someone who
    did. In practice that is the difference between a parent who reads with
    difficulty being able to reach the only non-text thing here, and not.
    """
    offered = state.get("offered_video")
    asking = wants_video(message)

    if offered:
        if not asking:
            # They asked something else. The offer has expired.
            return {"offered_video": None}
        video = by_id(str(offered))
        if video is None:
            logger.info("offered video %r is no longer in the catalog", offered)
            return {"offered_video": None}
        return _play(state, video)

    if not asking:
        return None

    # Local, and from `app.domain`: this module also imports an unrelated
    # `Language` from `app.eligibility.models` further down, and the two are
    # not the same enum.
    from app.domain import Language

    locale = str(state.get("locale") or "en")
    try:
        language = Language(locale)
    except ValueError:
        language = Language.EN
    matches = requested(message, language=language)

    if not matches:
        # Outside English there is nothing to play. Let the turn be answered
        # normally rather than apologising for a library they cannot use.
        return None
    if len(matches) == 1:
        return _play(state, matches[0])

    # They asked for "a video" without saying which. Offering the choice is
    # the only honest move; picking one for them is a guess wearing an answer's
    # clothes. Their reply names a subject and comes straight back here.
    titles = [video.title for video in matches]
    return {
        "active_agent": _holding_agent(state),
        "messages": [
            AIMessage(content=_VIDEO_WHICH.get(locale, _VIDEO_WHICH["en"]))
        ],
        "quick_replies": titles,
        "safety_flags": {"card": "video_choice"},
    }


def _asked_for_a_person(message: str) -> dict[str, Any] | None:
    """An explicit request for a human, recognised without a model."""
    # Complaint first.
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
    """"Create a guardian account" -- open the sign-up wizard."""
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
        "active_agent": _holding_agent(state),
        "safety_flags": {"card": "signup"},
    }


#: The one sentence that goes with the sign-up card.
_SIGNUP_INTRO: dict[str, str] = {
    "en": "Let's set that up — the form is on screen.",
    "es": "Vamos a crearla: el formulario está en pantalla.",
    "fr": "Créons-le : le formulaire est à l'écran.",
}


def _registration_help(state: AspireState, message: str) -> dict[str, Any] | None:
    """"I want to register my child", from somebody who cannot."""
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
    """Start the flow and emit the card, or None to answer normally."""
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
        "active_agent": _holding_agent(state),
        "safety_flags": {"card": "eligibility"},
    }


def _open_game(state: AspireState, message: str) -> dict[str, Any] | None:
    """Emit a game directive, ask which game, or decline to the band."""
    from app.agents.learn.tools.games import available_for, launch_game

    band = str(state.get("age_band") or "adult")
    persona = state.get("persona")
    playable = available_for(band, persona)
    if not playable:
        # Both halves matter. The band bars a game that is too old for a reader;
        # the persona bars the whole activity for a guardian or a teacher, who
        # came for the programme rather than for a quiz.
        logger.info(
            "No games are offered to band=%s persona=%s; answering normally.",
            band,
            persona,
        )
        return None

    chosen = named_game(message)
    if chosen is None:
        return {
            "quick_replies": [_GAME_LABELS.get(name, name) for name in playable],
            "messages": [_ask_which(band)],
            "active_agent": _holding_agent(state),
        }

    learning = state.get("learning") or {}
    concept = str(learning.get("concept_id") or "saving_basics")
    directive = launch_game(chosen, concept, 1, age_band=band, persona=persona)  # type: ignore[arg-type]
    if directive is None:
        # The band bars the one they named.
        return {
            "quick_replies": [_GAME_LABELS.get(name, name) for name in playable],
            "messages": [_ask_which(band)],
            "active_agent": _holding_agent(state),
        }

    logger.info("game card opened game=%s concept=%s band=%s", chosen, concept, band)
    return {
        "ui_directives": [directive],
        "active_agent": _holding_agent(state),
        "safety_flags": {"card": "game"},
    }


#: What each game is called to a reader.
#:
#: A game missing from here is offered by its wire id -- "hangman" beside
#: "True or false" -- so this table has to gain a row whenever `BAND_MIN` does.
_GAME_LABELS: dict[str, str] = {
    "true_false": "True or false",
    "scramble": "Word scramble",
    "millionaire": "Millionaire",
    "hangman": "Hangman",
}


def _ask_which(band: str):
    """Ask which game, in the band's voice."""
    from langchain_core.messages import AIMessage

    if band == "5-8":
        return AIMessage(content="Yes! Which one do you want to play?")
    return AIMessage(content="Sure — which one would you like to play?")


