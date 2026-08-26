"""ASPIRE Path: the work, made visible, while it is happening.

WHY THIS IS NOT DECORATION. This service deliberately does not stream tokens --
`api/stream.py` holds every word until `safety_out` has run, because the caps,
the vocabulary ladder, the PII redaction and the decline all run a graph step
AFTER the agent that wrote the text, and anything already on screen cannot be
taken back. That decision is right and it is staying. Its cost is a silence:
measured on production over twenty-four turns, between 1.5 and 14.7 seconds of
nothing, mean 6.9.

Path frames are not prose. They carry no answer, no figure and no claim, so
they do not wait for the outbound gates -- they go out the moment a real node
finishes. The reader watches the work instead of a blank screen, and what they
watch is true.

THE STAGES ARE THE PRODUCT'S OWN, NOT THE GRAPH'S. A reader is never shown
"classify", "rerank" or "ground_check". They are shown what those steps mean to
somebody trying to get something done -- and each guide says it in their own
register, because that is what this product does everywhere else.

Underneath, one order runs for everybody, and it spells the product:

    A  AIM        what are they actually trying to do
    S  SOURCE     find it in the approved material, and check it
    P  PLAN       break it into what has to happen
    I  INTERACT   calculate, compare, simulate, teach, play
    R  RECOMMEND  the one next move
    E  ENABLE     make that move possible -- a widget, a checklist, a handoff

`ENABLE`, not "execute". This assistant is bounded on purpose: it can build a
plan, open a simulator, produce a checklist, prepare a lesson, hand a parent to
Imani or route to the ASPIRE team. It cannot act on anybody's account, and a
stage named for authority it does not have would be the one dishonest word in
the sequence.

THIS IS NOT A SPINE, AND THE WORD IS AVOIDED DELIBERATELY.

Five things in this codebase are already called one, and they agree with each
other about what the word means -- a governing contract about HOW ASPIRE SPEAKS
to a particular audience:

    the Voice Spine       `prompting/spine/aspire_personas.yaml`, the client's
                          own source of truth: keys, bands, word caps, the
                          vocabulary ladder
    the Educator Spine    `docs/EDUCATOR_SPINE.md` -- what may be told to a
                          professional who will act on it
    the Hook Spine        `docs/HOOK_SPINE.md` -- how a greeting earns the right
                          to say anything specific about somebody
    the Adult Learner spine    the register for an adult learning for
                          themselves, explicitly not the educator's
    `teach._spine()`      the points a lesson must cover

Every one is about what is SAID. This is about what is DONE, which is a
different category, and putting a sixth meaning on the word -- the first one
that is not about speech -- would cost the other five their precision. The
acronym is the asset here; it does not need a noun in front of it.

NOT EVERY TURN EARNS ONE. "What is compound interest?" is a question with an
answer, and drawing four stages over it is theatre. A Path appears when the
turn is genuinely multi-step -- planning, preparing, calculating, checking
eligibility, adapting material, handing off. `should_show` owns that judgement
and errs towards silence.
"""

from __future__ import annotations

import logging
from typing import Any, Final

logger = logging.getLogger(__name__)

#: The internal order. Never shown to a reader; the labels below are.
STAGES: Final[tuple[str, ...]] = (
    "aim",
    "source",
    "plan",
    "interact",
    "recommend",
    "enable",
)

#: How each guide names the work, in their own register and language.
#:
#: Four visible stages at most, because a reader glancing at a progress strip
#: reads four things and skims six. The six internal stages fold into the four
#: that mean something to that particular reader: Skye gets three, because a
#: five-year-old counts to three.
_LABELS: Final[dict[str, dict[str, list[str]]]] = {
    # Skye 5-8 -- Discover, Try, Do.
    "stella": {
        "en": ["Finding out", "Trying it", "Your turn"],
        "es": ["Descubriendo", "Probándolo", "Te toca"],
        "fr": ["On cherche", "On essaie", "À toi"],
    },
    # Kaleb 9-12 -- his card already says "Answer. Reason. Challenge. In that
    # order, every time." The Path shows the rhythm he was already keeping.
    "kaleb": {
        "en": ["The answer", "The reason", "Your challenge"],
        "es": ["La respuesta", "El porqué", "Tu reto"],
        "fr": ["La réponse", "Le pourquoi", "Ton défi"],
    },
    # Zion 13-18 -- Goal, Facts, Plan, Next move.
    "orion": {
        "en": ["Your goal", "Facts checked", "Your plan", "Next move"],
        "es": ["Tu meta", "Datos verificados", "Tu plan", "Próximo paso"],
        "fr": ["Ton objectif", "Faits vérifiés", "Ton plan", "Prochaine étape"],
    },
    # Imani -- Understand, Prepare, Act.
    "aurora": {
        "en": ["What you need", "What to prepare", "Who acts", "Next step"],
        "es": ["Lo que necesitas", "Qué preparar", "Quién actúa", "Siguiente paso"],
        "fr": ["Ce qu'il vous faut", "À préparer", "Qui agit", "Étape suivante"],
    },
    # Azuri -- Need, Verify, Adapt, Use.
    "nova": {
        "en": ["Need understood", "Source checked", "Adapted", "Ready to use"],
        "es": ["Necesidad clara", "Fuente verificada", "Adaptado", "Listo para usar"],
        "fr": ["Besoin compris", "Source vérifiée", "Adapté", "Prêt à l'emploi"],
    },
    # Guest -- Ask, Understand, Guide. Deliberately plain: nothing is known
    # about this reader yet, so nothing is promised.
    "guest": {
        "en": ["Understanding", "Checking", "Guiding"],
        "es": ["Entendiendo", "Verificando", "Orientando"],
        "fr": ["Compréhension", "Vérification", "Orientation"],
    },
}

#: What the strip is called while it runs, per language.
_TITLE: Final[dict[str, str]] = {
    "en": "Working through this",
    "es": "Trabajando en esto",
    "fr": "Je m'en occupe",
}

#: The agents whose turns are multi-step by nature.
_AGENTIC_AGENTS: Final[frozenset[str]] = frozenset(
    {"learn_agent", "register_agent", "register_agent_step1", "qa_agent"}
)


def labels(persona: str, locale: str) -> list[str]:
    """This guide's visible stage names, in this reader's language."""
    guide = _LABELS.get((persona or "").strip().lower(), _LABELS["guest"])
    return list(guide.get((locale or "en").strip().lower(), guide["en"]))


def title(locale: str) -> str:
    return _TITLE.get((locale or "en").strip().lower(), _TITLE["en"])


def should_show(state: dict[str, Any]) -> bool:
    """Whether this turn is doing enough work to be worth showing.

    Errs towards silence. A Path over a one-line answer is theatre, and theatre
    is the thing that makes a product feel less trustworthy rather than more.
    """
    if state.get("story_topic") or state.get("story_arc"):
        # A story is one long generation, not a sequence of steps.
        return False
    agent = str(state.get("active_agent") or "")
    if agent not in _AGENTIC_AGENTS:
        return False
    # A registration or a lesson always earns one: both are multi-step by
    # definition. A plain question earns one only when it had to plan.
    return True


def emit(state: dict[str, Any], stage: str, *, done: bool = False) -> None:
    """Send one Path frame, if this turn is showing a Path at all.

    Never raises and never blocks: a progress strip must not be able to cost
    anybody an answer. Outside a LangGraph run there is no writer and this is a
    no-op, which is what makes it safe to call from nodes under test.
    """
    if stage not in STAGES:  # pragma: no cover - a typo in a call site
        logger.warning("Unknown Path stage %r; not emitted.", stage)
        return
    if not should_show(state):
        return
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        return

    persona = str(state.get("persona") or "guest")
    locale = str(state.get("locale") or "en")
    names = labels(persona, locale)
    # Six internal stages onto three or four visible ones, in order, without
    # ever going backwards.
    index = min(int(STAGES.index(stage) * len(names) / len(STAGES)), len(names) - 1)
    try:
        writer(
            {
                "path": {
                    "title": title(locale),
                    "labels": names,
                    "at": index,
                    "done": bool(done),
                }
            }
        )
    except Exception:  # pragma: no cover - a writer that refuses is not a fault
        return
