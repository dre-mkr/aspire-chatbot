"""The turns answered before anything else runs."""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.escalation.contract import EscalationReason
from app.graph.nodes.intents import (
    asks_for_a_video,
    is_complaint,
    named_game,
    wants_account,
    wants_eligibility,
    wants_game,
    wants_human,
    wants_lesson,
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
from app.videos import by_id
from app.videos.catalog import all_videos, has_subtitle, requested

logger = logging.getLogger(__name__)

#: Locales the eligibility card has copy for.
_CARD_LOCALES = frozenset({"en", "es", "fr"})

#: Either of these means the caller has somewhere to register.
_REGISTRATION_AGENTS = frozenset({"register_agent", "register_agent_step1"})

#: The bands that may be told they can register their own account.
#:
#: Published, and in the corpus twice. ASP-049: "From age 12, an ASPIRE
#: participant can also register for their own account at aspire.gov.kn or at a
#: branch." ASP-050 says the same in the reader's own words.
_SELF_REGISTERING_BANDS = ("13-15", "16-18")

#: A child named in the third person. "Register my daughter" is a different
#: question from "register me", and a band cannot tell them apart.
_FOR_ANOTHER = re.compile(
    r"\b(?:my|our|the|she|he)\s+"
    r"(?:son|daughter|child|children|kid|kids|boy|girl|grandson|granddaughter|"
    r"grandchild|grandchildren|niece|nephew|godson|goddaughter|godchild)\b"
    r"|\bfor (?:him|her|them|the child|the children)\b",
    re.IGNORECASE,
)


#: Who is reading, for the purpose of answering "I want to register".
def _audience(persona: str, age_band: str, message: str = "") -> str:
    """`child`, `young_person`, `educator`, or `unaccompanied`.

    `young_person` is new, because the old three-way split told a
    seventeen-year-old to go and fetch a parent.

    Every minor band collapsed into `child`, whose copy says "ask your parent or
    guardian to sign in with their own ASPIRE account". Right for a
    seven-year-old. Wrong for a fourteen- or seventeen-year-old, against the
    programme's own published rule -- a participant may register their own
    account from age 12, at aspire.gov.kn or at a branch.

    The assistant was answering a question about the PROGRAMME with a fact about
    the ASSISTANT. Both true, not the same answer. Jayden Prentice, seventeen,
    does his own paperwork and his mother's; "ask a parent" is not merely
    unhelpful in that house, it is wrong with a published rule behind it.

    The oldest minors were worst served of all: `orion` is not `stella` and
    `16-18` was not in the band list, so a seventeen-year-old fell through to
    `unaccompanied` and was told to "create a guardian account" -- advice for an
    adult applying on somebody else's behalf, handed to a child applying for
    themselves.

    ORDER IS THE SAFETY PROPERTY. The youngest bands are settled before a single
    word of the message is read. A nine-year-old typing "register my child" is
    copying a phrase or testing the bot, not raising one, and reading intent out
    of a child's prose to widen what they are told is the mistake
    `_ANONYMOUS_DEFAULT` was moved twice to avoid.
    """
    if persona == "nova":
        return "educator"
    if persona == "stella" or age_band in ("5-8", "9-12"):
        return "child"
    # Above that, applying on somebody else's behalf is a guardian's question
    # whatever the reader's own age. A sixteen-year-old can be a parent -- an
    # existing test says so -- and a grandmother raising a grandchild must not be
    # answered as though she were the applicant.
    if _FOR_ANOTHER.search(message or ""):
        return "unaccompanied"
    if age_band in _SELF_REGISTERING_BANDS:
        return "young_person"
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
    #: 13-15 and 16-18: old enough to register themselves under the published
    #: rule, and told so -- while staying honest that THIS assistant takes the
    #: application from a guardian. Saying only the first half would send a
    #: fourteen-year-old round a loop.
    "young_person": {
        "en": (
            "You can register your own ASPIRE account from age 12 -- at "
            "aspire.gov.kn, or at any branch. An application through this "
            "assistant is completed by a parent or guardian, so if you would "
            "rather do it here, ask yours to start it from their own account."
        ),
        "es": (
            "Puedes registrar tu propia cuenta de ASPIRE desde los 12 años, en "
            "aspire.gov.kn o en cualquier sucursal. Una solicitud hecha con este "
            "asistente la completa un padre, madre o tutor, así que si prefieres "
            "hacerla aquí, pídele que la empiece desde su propia cuenta."
        ),
        "fr": (
            "Tu peux créer ton propre compte ASPIRE à partir de 12 ans, sur "
            "aspire.gov.kn ou dans une agence. Une demande faite avec cet "
            "assistant est remplie par un parent ou tuteur, donc si tu préfères "
            "la faire ici, demande-lui de la commencer depuis son compte."
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
    "young_person": {
        "en": ["Register at a branch", "What documents are needed?"],
        "es": ["Registrarme en una sucursal", "¿Qué documentos?"],
        "fr": ["M'inscrire en agence", "Quels documents ?"],
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

        # The learn-vs-teach clarifier, both halves. An educator or a parent
        # asking to be taught is ambiguous where a child is not: learning for
        # themselves, or preparing to teach it on. Like the story flow, the
        # second half returns a resumed request rather than a card.
        card = _learner_purpose_turn(state, message)
        if card is not None:
            return card

        # A savings goal said out loud becomes a signable pledge card, and the
        # signed pledge becomes a standing goal every later turn keeps in view.
        card = _pledge_turn(state, message)
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


#: "I want to save EC$200 a month for a bike" -- an amount, a period, and
#: maybe a named goal. The trigger for the pledge card.
_PLEDGE_INTENT = re.compile(
    r"\b(?:i (?:want|plan|am going|'m going|would like) to save|i will save|"
    r"quiero ahorrar|je veux (?:economiser|épargner))\b.{0,40}?"
    r"(?:ec\$?\s?|\$)(\d[\d,]*)"
    r"(?:.{0,30}?\b(a week|per week|each week|a month|per month|each month|al mes|a la semana|par mois|par semaine|"
    r"every (?:week|month|payday)|this (?:week|month|year)|a year)\b)?",
    re.IGNORECASE,
)

#: What the goal is for, trailing the amount: "for a bike", "towards CFBC".
_PLEDGE_GOAL = re.compile(
    r"\b(?:for|towards?|para|pour)\s+((?:my |a |an |the |mi |mon |ma )?[^.,!?]{2,40})",
    re.IGNORECASE,
)

#: What the sign button sends, per locale. Read back by `_pledge_turn`, which
#: accepts ANY of them -- a reader who switched language mid-conversation must
#: not have their earlier button refused.
_PLEDGE_PREFIXES = {"en": "I pledge: ", "es": "Me comprometo: ", "fr": "Je m'engage : "}
_PLEDGE_SEPARATORS = {"en": " towards ", "es": " para ", "fr": " pour "}
_PLEDGE_COPY = {
    "en": {
        "ask_young": "That is a real plan. Want to make it a promise?",
        "ask": "That is a real goal. Want to make it a pledge? Signing it means I keep it in view and ask how it is going.",
        "salute_young": "You made a promise to your tin! I will remember it.",
        "salute": "Signed. That pledge is yours now -- I will keep it in view.",
        "button_young": "I promise",
        "button": "Sign my pledge",
        "sealed": "Pledged",
    },
    "es": {
        "ask_young": "Ese es un buen plan. ¿Quieres convertirlo en una promesa?",
        "ask": "Esa es una meta de verdad. ¿Quieres convertirla en un compromiso? Si lo firmas, lo tendré presente y te preguntaré cómo va.",
        "salute_young": "¡Hiciste una promesa a tu alcancía! La recordaré.",
        "salute": "Firmado. Ese compromiso ya es tuyo -- lo tendré presente.",
        "button_young": "Lo prometo",
        "button": "Firmar mi compromiso",
        "sealed": "Comprometido",
    },
    "fr": {
        "ask_young": "C'est un vrai plan. Tu veux en faire une promesse ?",
        "ask": "C'est un vrai objectif. Tu veux en faire un engagement ? Si tu le signes, je le garde en vue et je te demanderai où tu en es.",
        "salute_young": "Tu as fait une promesse à ta tirelire ! Je m'en souviendrai.",
        "salute": "Signé. Cet engagement est à toi -- je le garde en vue.",
        "button_young": "Je promets",
        "button": "Signer mon engagement",
        "sealed": "Engagé",
    },
}


def _pledge_turn(state: AspireState, message: str) -> dict[str, Any] | None:
    """Offer a pledge card for a stated savings goal; store it when signed."""
    from app.schemas.directives import PledgeDirective

    band = str(state.get("age_band") or "adult")
    young = band == "5-8"

    locale = str(state.get("locale") or "en")
    copy = _PLEDGE_COPY.get(locale, _PLEDGE_COPY["en"])

    # ── the signed pledge coming back, in whichever language it was offered ──
    matched = next(
        (p for p in _PLEDGE_PREFIXES.values() if message.startswith(p)), None
    )
    if matched is not None:
        body = message[len(matched):].strip()
        amount_line, goal = body, ""
        for sep in _PLEDGE_SEPARATORS.values():
            if sep in body:
                amount_line, _, goal = body.partition(sep)
                break
        pledge = {"amount_line": amount_line.strip(), "goal": goal.strip()}
        salute = copy["salute_young"] if young else copy["salute"]
        return {
            "pledge": pledge,
            "messages": [AIMessage(content=salute)],
            "ui_directives": [
                PledgeDirective(
                    amount_line=pledge["amount_line"],
                    goal=pledge["goal"],
                    button_label=copy["sealed"],
                    button_value="",
                    pledged=True,
                )
            ],
            "active_agent": _holding_agent(state),
            "safety_flags": {"card": "pledge_signed"},
        }

    # ── a fresh goal worth offering a card for ──
    if state.get("pledge"):
        return None
    match = _PLEDGE_INTENT.search(message)
    if match is None:
        return None
    amount = match.group(1)
    period = (match.group(2) or "").strip()
    goal_match = _PLEDGE_GOAL.search(message[match.end():])
    goal = (goal_match.group(1).strip() if goal_match else "")

    amount_line = f"EC${amount}" + (f" {period}" if period else "")
    prefix = _PLEDGE_PREFIXES.get(locale, _PLEDGE_PREFIXES["en"])
    sep = _PLEDGE_SEPARATORS.get(locale, _PLEDGE_SEPARATORS["en"])
    value = prefix + amount_line + (f"{sep}{goal}" if goal else "")
    ask = copy["ask_young"] if young else copy["ask"]
    return {
        "messages": [AIMessage(content=ask)],
        "ui_directives": [
            PledgeDirective(
                amount_line=amount_line,
                goal=goal,
                button_label=copy["button_young"] if young else copy["button"],
                button_value=value,
            )
        ],
        "active_agent": _holding_agent(state),
        "safety_flags": {"card": "pledge_offer"},
    }


#: Which personas meet the learn-vs-teach clarifier, and how it is worded.
#:
#: `nova` is Azuri, the educator: for yourself, or to teach your students.
#: `aurora` is Imani, the parent: for yourself, or to help your child. Guest
#: is deliberately absent -- a signed-out adult has no third party to teach, so
#: their learning intent is taken at its word and answered as a learner.
#:
#: `second` is the ROLE the non-self answer resolves to: an educator teaching
#: is a `teacher`, a parent helping their child is a `parent`. `self` is always
#: `learner`. Those are the registers in `_ROLE_INSTRUCTION`.
_PURPOSE_PERSONAS: dict[str, dict[str, str]] = {
    "nova": {"second": "students", "role": "teacher"},
    "aurora": {"second": "child", "role": "parent"},
}

_PURPOSE_ASK: dict[str, dict[str, str]] = {
    "nova": {
        "en": "Quick check -- are you learning this for yourself, or planning to teach it to your students?",
        "es": "Una pregunta rapida: aprendes esto para ti, o quieres ensenarselo a tus estudiantes?",
        "fr": "Petite question : apprenez-vous ceci pour vous, ou pour l'enseigner a vos eleves ?",
    },
    "aurora": {
        "en": "Quick check -- are you learning this for yourself, or to help your child with it?",
        "es": "Una pregunta rapida: aprendes esto para ti, o para ayudar a tu hijo o hija?",
        "fr": "Petite question : apprenez-vous ceci pour vous, ou pour aider votre enfant ?",
    },
}

_PURPOSE_CHIPS: dict[str, dict[str, list[str]]] = {
    "nova": {
        "en": ["For myself", "To teach my students"],
        "es": ["Para mi", "Para ensenar a mis estudiantes"],
        "fr": ["Pour moi", "Pour enseigner a mes eleves"],
    },
    "aurora": {
        "en": ["For myself", "To help my child"],
        "es": ["Para mi", "Para ayudar a mi hijo o hija"],
        "fr": ["Pour moi", "Pour aider mon enfant"],
    },
}

#: What a "for myself" answer looks like, in the three languages.
_SELF_ANSWER = re.compile(
    r"\b(?:myself|for me|my own|just me|i want to learn|para m[ií]|pour moi|moi-?m[eê]me)\b",
    re.IGNORECASE,
)


def _purpose_from_answer(message: str, persona: str) -> str:
    """Read a clarifier answer into "self" or the persona's teaching role.

    A tap gives the chip text; a typed reply gives whatever they wrote. Default
    to `self` on anything unclear -- the learner register offers rather than
    gates, so it is the safe wrong guess. Only an explicit teaching answer wins.
    """
    second = _PURPOSE_PERSONAS[persona]["second"]
    folded = message.lower()
    teaching = {
        "students": ("student", "class", "pupil", "my form", "estudiante", "clase", "alumno", "eleve", "élève"),
        "child": ("my child", "my kid", "my son", "my daughter", "help my child", "mi hijo", "mi hija", "mon enfant"),
    }[second]
    if _SELF_ANSWER.search(message):
        return "self"
    if any(word in folded for word in teaching):
        return second
    return "self"


def _looks_like_a_purpose_answer(message: str, persona: str) -> bool:
    """Whether this reply is an answer to the clarifier, not a fresh question.

    A chip, a "for myself", a "for my students" -- or a short tap-length reply,
    which a hurried reader gives instead of the chip. A longer message with no
    purpose signal is treated as a change of subject.
    """
    second = _PURPOSE_PERSONAS[persona]["second"]
    folded = message.lower()
    teaching = {
        "students": ("student", "class", "pupil", "my form", "estudiante", "clase", "alumno", "eleve", "élève"),
        "child": ("my child", "my kid", "my son", "my daughter", "help my child", "mi hijo", "mi hija", "mon enfant"),
    }[second]
    if _SELF_ANSWER.search(message) or any(word in folded for word in teaching):
        return True
    return len(message.split()) <= 4


def _learner_purpose_turn(state: AspireState, message: str) -> dict[str, Any] | None:
    """Ask an educator or parent whether a lesson is for them or to teach on.

    Two halves, like the story flow. First half: an ambiguous lesson request
    from `nova` or `aurora`, with nothing remembered yet -- ask, and hold the
    request. Second half: the answer arrives, so record the purpose for the
    session and resume the held request as though they had just sent it.
    """
    persona = str(state.get("persona") or "")
    locale = str(state.get("locale") or "en")
    if locale not in _CARD_LOCALES:
        locale = "en"

    # ── second half: the answer to a question we asked last turn ──
    if state.get("awaiting_learner_purpose"):
        pending = state.get("pending_learning") or message
        # A persona we no longer recognise cannot resolve an answer; let go.
        if persona not in _PURPOSE_PERSONAS:
            return {"awaiting_learner_purpose": False, "pending_learning": None}
        # They may have ignored the question and asked something else. A real
        # answer looks like an answer -- a chip, a "for myself", "my students" --
        # or is a short tap-length reply. Anything longer and unrecognised is a
        # new intent, so drop the latch and let THIS message flow to the router
        # rather than resuming a lesson they have moved on from.
        if not _looks_like_a_purpose_answer(message, persona):
            return {"awaiting_learner_purpose": False, "pending_learning": None}
        purpose = _purpose_from_answer(message, persona)
        # Resume the original request as the effective message, so the router
        # and the tutor see "teach me about budgeting", not "for myself".
        return {
            "awaiting_learner_purpose": False,
            "learner_purpose": purpose,
            "pending_learning": None,
            "messages": [HumanMessage(content=pending)],
        }

    # ── first half: an ambiguous lesson request worth clarifying ──
    if persona not in _PURPOSE_PERSONAS:
        return None
    # Ask ONCE. Once the session has an answer, never interrupt again.
    if state.get("learner_purpose"):
        return None
    if not wants_lesson(message):
        return None
    # If the message already says which, there is nothing to ask.
    if _purpose_is_explicit(message, persona):
        return None

    return {
        "awaiting_learner_purpose": True,
        "pending_learning": message,
        "active_agent": _holding_agent(state),
        "messages": [AIMessage(content=_PURPOSE_ASK[persona].get(locale) or _PURPOSE_ASK[persona]["en"])],
        "quick_replies": _PURPOSE_CHIPS[persona].get(locale) or _PURPOSE_CHIPS[persona]["en"],
        "safety_flags": {"card": "learner_purpose"},
    }


def _purpose_is_explicit(message: str, persona: str) -> bool:
    """Whether the request already says who the learning is for."""
    return _purpose_from_answer(message, persona) != "self" or bool(_SELF_ANSWER.search(message))


#: A priced story choice: "Buy the rope (EC$30)" or "Walk on (free)".
_STORY_CHOICE = re.compile(
    r"^(.*?)\s*\((?:EC\$\s?(\d+)|free|gratis|gratuit)\)\s*$", re.IGNORECASE
)


def _story_choice(message: str) -> tuple[str, int] | None:
    """The (item, cost) a chip-shaped reply carries, or None."""
    m = _STORY_CHOICE.match(message.strip())
    if m is None:
        return None
    return (m.group(1).strip() or "that", int(m.group(2) or 0))


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

#: What is said when the reader ends the story themselves.
_STORY_CLOSED: dict[str, str] = {
    "en": "That's a good place to stop. Ask me for another whenever you like.",
    "es": "Es un buen momento para parar. Pídeme otra cuando quieras.",
    "fr": "C'est un bon endroit pour s'arrêter. Demande-m'en une autre quand tu veux.",
}

_STORY_ASK: dict[str, str] = {
    "en": "I can do that. What would you like the story to be about?",
    "es": "Claro. ¿Sobre qué te gustaría que fuera el cuento?",
    "fr": "Bien sûr. De quoi aimerais-tu que parle l'histoire ?",
}


#: How many beats a story may run to before it has to land.
#:
#: Not a limit on the reader's patience -- they end it whenever they like -- but
#: on the model's. A story with no last page stops being a story; by the sixth
#: beat there has to be an ending, or the arc is just a treadmill with a
#: character on it.
STORY_BEATS = 6

#: Carrying on, in the reader's own words. The chip sends the first of these.
_STORY_MORE = re.compile(
    r"\bwhat happens next\b|\bwhat next\b|\bkeep going\b|\bgo on\b|\bcontinue\b"
    r"|\bmore\b|\bthen what\b"
    r"|\bqu[eé] pasa despu[eé]s\b|\bsigue\b|\bcontin[uú]a\b|\bm[aá]s\b"
    r"|\bet apr[eè]s\b|\bla suite\b|\bcontinue[rz]?\b|\bencore\b",
    re.IGNORECASE,
)

#: Stopping, in the reader's own words. Checked BEFORE `_STORY_MORE`, because
#: "no more" contains "more" and means its opposite.
_STORY_ENOUGH = re.compile(
    r"\bthat\'?s enough\b|\benough\b|\bno more\b|\bstop\b|\bi\'?m done\b|\bdone\b"
    r"|\bya basta\b|\bbasta\b|\bsuficiente\b|\bno m[aá]s\b|\bpara\b"
    r"|\b[cç]a suffit\b|\bassez\b|\bstop\b|\bplus rien\b",
    re.IGNORECASE,
)


def story_continues(message: str) -> bool:
    """Whether this asks for the next beat of the story already running."""
    if _STORY_ENOUGH.search(message):
        return False
    return bool(_STORY_MORE.search(message))


def story_ends(message: str) -> bool:
    """Whether this asks for the story to stop."""
    return bool(_STORY_ENOUGH.search(message))


#: Thinking about the story rather than advancing or leaving it.
#:
#: The middle chip is the pedagogy -- "What would you do?" is the question the
#: whole story exists to provoke -- and without this it was the one chip that
#: broke the thread: not a continue, not a stop, so the arc was dropped as a
#: change of subject and the next "what happens next" had nothing to continue.
_STORY_REFLECT = re.compile(
    r"\bwhat would you do\b|\bwhat does it teach\b|\bwhat would i do\b"
    r"|\bqu[eé] har[ií]as\b|\bqu[eé] nos ense[nñ]a\b"
    r"|\bque ferais-tu\b|\bqu\'?est-ce que [cç]a apprend\b",
    re.IGNORECASE,
)


def story_reflects(message: str) -> bool:
    """Whether this thinks about the story without ending or advancing it."""
    return bool(_STORY_REFLECT.search(message))


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

    # ── a story already running ─────────────────────────────────────────────
    #
    # Checked before everything else, because while an arc is open the same
    # words mean something different: "more" is the next beat, not a new story.
    arc = state.get("story_arc")
    if arc:
        if story_ends(message):
            return {
                "story_arc": None,
                "active_agent": _holding_agent(state),
                "messages": [AIMessage(content=_STORY_CLOSED[locale])],
                "quick_replies": _STORY_TOPICS[locale],
                "safety_flags": {"card": "story_closed"},
            }
        choice = _story_choice(message)
        if choice is not None or story_continues(message):
            beat = int(arc.get("beat") or 1) + 1
            wallet = int(arc.get("wallet") or 0)
            inventory = list(arc.get("inventory") or [])
            last_choice, afforded = "", True
            if choice is not None:
                item, cost = choice
                last_choice = item
                # The wallet is the lesson: an unaffordable pick is not an
                # error, it is the consequence the next beat is built on.
                afforded = cost <= wallet
                if afforded:
                    wallet -= cost
                    if cost > 0:
                        inventory.append(item)
            # Not a card: the router runs and an agent writes the next beat,
            # with the story instruction and the story word cap applied.
            return {
                "story_topic": str(arc.get("topic") or ""),
                "story_arc": {
                    "topic": arc.get("topic"),
                    "beat": beat,
                    "wallet": wallet,
                    "inventory": inventory,
                    "last_choice": last_choice,
                    "afforded": afforded,
                },
                "awaiting_story_topic": False,
            }
        # Thinking about the story is not leaving it. Empty update, so the
        # router answers the question while the arc stays exactly where it was
        # -- the reader can still ask what happens next afterwards.
        if story_reflects(message):
            return {}

        # Anything else is a change of subject, and the arc is dropped rather
        # than left open to swallow the next unrelated "more". No `card` flag
        # and no message, so `_after_cards` sends this on to the router and the
        # question is answered normally -- the arc closing is not an event the
        # reader needs told about.
        #
        # A fresh "tell me a story" falls through instead, to the topic ask
        # below, which starts a new arc rather than continuing the old one.
        if not wants_story(message):
            return {"story_arc": None}

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
        # Beat one, and the arc opens here. `story_topic` is cleared by
        # `hydrate` next turn; `story_arc` is not, which is what lets the story
        # have a second page.
        return {
            "awaiting_story_topic": False,
            "story_topic": topic[:120],
            # The adventure state: an in-story wallet and inventory, so the
            # reader PLAYS the money idea instead of only hearing it. EC$100
            # of story-money, spent by picking choices priced "(EC$N)".
            "story_arc": {
                "topic": topic[:120],
                "beat": 1,
                "wallet": 100,
                "inventory": [],
            },
        }

    if not wants_story(message):
        return None

    return {
        "awaiting_story_topic": True,
        "active_agent": _holding_agent(state),
        "messages": [AIMessage(content=_STORY_ASK[locale])],
        "quick_replies": _STORY_TOPICS[locale],
        "safety_flags": {"card": "story_topic"},
    }


#: What to say when somebody asks for a video and names no subject.
_VIDEO_MENU: dict[str, str] = {
    "en": "Here are the ASPIRE videos. Which one would you like?",
    "es": "Estos son los videos de ASPIRE. ¿Cuál te gustaría ver?",
    "fr": "Voici les vidéos ASPIRE. Laquelle veux-tu regarder ?",
}


def _play(state: AspireState, video: Any) -> dict[str, Any]:
    """The turn that opens the player. One place, three callers."""
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


def _language_of(state: AspireState) -> Any:
    """The reader's language, from the state's locale.

    Imported inside the function on purpose: this module also imports an
    unrelated `Language` from `app.eligibility.models` further down, and the two
    enums are not the same. An unknown locale falls back to English rather than
    raising -- a bad locale must not take the turn down.
    """
    from app.domain import Language

    try:
        return Language(str(state.get("locale") or "en"))
    except ValueError:
        return Language.EN


def _video_choice(state: AspireState, videos: tuple[Any, ...]) -> dict[str, Any]:
    """Ask which one, with a chip per video.

    The chips are the same sentence `offer_for` builds, and that is not a
    coincidence -- a chip is also what gets SENT when it is tapped, so it has to
    come back through `asks_for_a_video` and resolve to exactly one video. Naming
    the topic does both: it is under the command-length ceiling and it carries
    the keyword that settles the next turn.
    """
    locale = str(state.get("locale") or "en")
    if locale not in _VIDEO_MENU:
        locale = "en"
    return {
        "offered_video": None,
        "active_agent": _holding_agent(state),
        "messages": [AIMessage(content=_VIDEO_MENU[locale])],
        "quick_replies": [
            f"Watch the ASPIRE video about {video.topic.lower()}" for video in videos
        ],
        "safety_flags": {"card": "video_menu"},
    }


def _open_video(state: AspireState, message: str) -> dict[str, Any] | None:
    """Play a video: the one offered last turn, or the one they just asked for.

    Both halves are here because they are one decision, and splitting them is
    how the second half came to be missing.

    **Accepting an offer.** Three things have to be true: an offer was made, this
    message accepts it, and the id still names something in the catalog. That
    last check is why the catalog is server-owned -- an id reaching here from a
    stale checkpoint, or from a client that made one up, resolves to nothing and
    the turn carries on as an ordinary question.

    **Asking outright**, which until now had no path at all. `_open_video` could
    only ever say yes to a question the assistant had asked first, so a reader
    typing "Do you have videos?" fell through this node, through the router, and
    into whichever agent held the session -- which, mid-lesson, is the tutor,
    which graded it as a wrong answer to the question on screen and spent a hint
    on it. That is a real transcript: six requests, one video, and the one that
    worked contained the word "scarcity", so it was matched on the TOPIC by the
    volunteering path in `safety_out` rather than on the request by anything.

    Being a card is the fix, not a detail of it. `_after_cards` routes a card
    straight to `safety_out`, so a turn answered here never reaches `classify`
    and never meets `apply_stickiness` -- and the tutor is never asked to grade
    a request for a video as an answer about coins.
    """
    offered = state.get("offered_video")

    if offered and wants_video(message):
        video = by_id(str(offered))
        if video is not None:
            # Unless they have named a DIFFERENT one. "Show me the saving video"
            # accepts an offer by the letter of `wants_video`, and playing the
            # scarcity film because that is what was on the table is the same
            # not-listening this whole node exists to stop.
            asked = requested(message)
            if len(asked) == 1 and asked[0].id != video.id:
                return _play(state, asked[0])
            return _play(state, video)
        logger.info("offered video %r is no longer in the catalog", offered)
        # Fall through: the offer is dead, but they may still be asking.

    if not asks_for_a_video(message):
        # They asked something else. Any offer has expired -- a "yes" three
        # turns later must not reach back and open a player.
        return {"offered_video": None} if offered else None

    # `requested` was taking a `language` nobody passed, so its caption gate
    # never ran and a French reader typing "montre-moi une vidéo" was handed a
    # menu of two films with no track they could follow. The locale is on the
    # state; pass it.
    language = _language_of(state)
    matches = requested(message, language=language)
    if len(matches) == 1:
        return _play(state, matches[0])
    # None named, or a tie. Both are the same answer: show what there is rather
    # than the silence a tie used to produce. `relevant_to` returns None in both
    # cases, correctly, because it is deciding whether to interrupt -- and that
    # is exactly why this path does not use it.
    shelf = matches or tuple(v for v in all_videos() if has_subtitle(v, language))
    if not shelf:
        # Nothing in this language has a caption track. Let the turn be answered
        # normally rather than offering a shelf they cannot watch.
        return {"offered_video": None} if offered else None
    return _video_choice(state, shelf)


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
    audience = _audience(persona, age_band, message)

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
    audience = _audience(persona, age_band, message)

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


