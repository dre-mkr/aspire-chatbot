"""What is checked on the way in."""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from app.safety import pii
from app.graph.nodes.classify import TEACHING_AGENTS
from app.graph.nodes.intents import fold
from app.graph.state import AspireState

logger = logging.getLogger(__name__)


# ── injection ────────────────────────────────────────────────────────────────

#: Instruction override.
_OVERRIDE = re.compile(
    r"""
    \b(?:ignore|disregard|forget|override|bypass|discard)\b
    [^.\n]{0,40}?
    \b(?:previous|prior|above|earlier|all|any|your|the)\b
    [^.\n]{0,20}?
    \b(?:instruction|instructions|rule|rules|prompt|prompts|direction
       |directions|guideline|guidelines|constraint|constraints|training)\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Role reassignment. "You are now a ...", "act as ...", "pretend you are ...".
_ROLE = re.compile(
    r"""
    \b(?:
        you\s+are\s+(?:now|no\s+longer)\b
        # Only as an imperative aimed at the model. Without the sentence-start
        # anchor this fires on "How do I act as a good saver?", which is a
        # nine-year-old asking a perfectly good question.
      | (?:^|[.!?]\s+)(?:please\s+|now\s+|ok(?:ay)?[, ]+)?
        (?:act|behave|respond|answer)\s+as\s+(?:if\s+you\s+are\s+|a\s+|an\s+|the\s+)
      | pretend\s+(?:to\s+be|you(?:'re|\s+are))\b
      | roleplay\s+as\b
      | from\s+now\s+on[, ]+you\b
      | enter\s+(?:developer|debug|god|admin|dan)\s+mode\b
      | switch\s+to\s+(?:developer|debug|admin|unrestricted)\s+mode\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: System-prompt extraction.
_EXTRACT = re.compile(
    r"""
    \b(?:
        (?:show|print|repeat|reveal|output|display|tell\s+me|what\s+(?:is|are))
        [^.\n]{0,30}?
        (?:system\s+prompt|initial\s+(?:prompt|instructions)|your\s+instructions
          |your\s+rules|the\s+prompt\s+above|everything\s+above)
      | repeat\s+(?:everything|all)\s+(?:above|before)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Delimiter and role-marker spoofing -- text pretending to be a message boundary.
_DELIMITER = re.compile(
    r"""
    (?:
        \[/?(?:INST|SYS|SYSTEM|ASSISTANT|USER)\]
      | <\|(?:im_start|im_end|system|endoftext|eot_id|start_header_id)\|?>
      | ^\s*(?:system|assistant)\s*:\s*$
      | \#\#\#\s*(?:system|instruction)\s*:
    )
    """,
    re.VERBOSE | re.IGNORECASE | re.MULTILINE,
)

_INJECTION_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("instruction_override", _OVERRIDE),
    ("role_reassignment", _ROLE),
    ("prompt_extraction", _EXTRACT),
    ("delimiter_spoof", _DELIMITER),
)


def injection_signals(text: str) -> list[str]:
    """Which injection shapes `text` matches. Empty means clean."""
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


# ── distress and safeguarding ────────────────────────────────────────────────

# These are matched against FOLDED text -- see `distress_level`. Accents are
# stripped before matching, so every pattern below is written without them and
# `quiero morirme`, `quiéro morírme` and `QUIERO MORIRME` are one case.
#
# The product ships in three languages and this path spoke one. Measured before
# the fix: "I want to kill myself" -> safeguarding, "quiero morirme" -> None,
# "je veux mourir" -> None. A Spanish or French disclosure went to the router
# and was answered as an ordinary question.

#: Signals that a child needs a person, not an assistant.
_SAFEGUARDING = re.compile(
    r"""
    \b(?:
      # ── English ──────────────────────────────────────────────────────────
        kill\s+my ?self | killing\s+my ?self | end\s+my\s+life
      | want\s+to\s+die | wanna\s+die | better\s+off\s+dead
      | hurt\s+my ?self | hurting\s+my ?self | cut\s+my ?self
      | suicide | suicidal
      | (?:he|she|they|dad|mum|mom|uncle|aunt|teacher|someone)\s+(?:hit|hits|beat|beats|hurt|hurts|touch|touches|touched)\s+me
      | (?:being\s+)?abused | molest\w* | someone\s+is\s+hurting\s+me
      | not\s+safe\s+at\s+home | scared\s+to\s+go\s+home
      | run\s+away\s+from\s+home
      # ── Spanish ──────────────────────────────────────────────────────────
      | (?:me\s+)?quiero\s+morir(?:me)? | quiero\s+matarme | matarme
      | no\s+quiero\s+vivir | mejor\s+muerto | mejor\s+muerta
      | suicid\w*
      | (?:hacerme|me\s+hago|me\s+quiero\s+hacer)\s+dano
      | autolesion\w* | me\s+corto\s+(?:los\s+brazos|las\s+munecas|la\s+piel)
      # A subject is REQUIRED, exactly as in the English rule above. Without one
      # `me toca` matched "cuanto me toca ahorrar" -- how much do I get to save --
      # and an ordinary savings question raised a safeguarding ticket and
      # notified a guardian. Measured, not hypothetical.
      | (?:el|ella|ellos|mi\s+(?:papa|mama|padre|madre|tio|tia|hermano|hermana|maestr[oa]|profesor[a]?)|alguien)
        \s+me\s+(?:pega|pegan|golpea|golpean|toca|tocan|lastima|hace\s+dano)
      | abusan\s+de\s+mi | abuso\s+sexual | me\s+abusan
      | no\s+(?:estoy|me\s+siento)\s+segur[oa]\s+en\s+casa
      | miedo\s+de\s+(?:ir|volver|regresar)\s+a\s+casa
      | (?:escaparme|huir|irme)\s+de\s+casa
      # ── French ───────────────────────────────────────────────────────────
      | je\s+veux\s+mourir | envie\s+de\s+mourir | veux\s+mourir
      | (?:je\s+veux\s+)?me\s+tuer | me\s+suicider | suicid\w*
      | mieux\s+mort(?:e)?
      | (?:me\s+faire|je\s+me\s+fais)\s+du\s+mal
      # Not a bare "je me coupe": that is how you say you are cutting your hair.
      | automutil\w* | me\s+couper\s+les\s+veines | je\s+me\s+coupe\s+les\s+bras
      | (?:il|elle|on|papa|maman)\s+me\s+(?:frappe|tape|bat|touche)
      | abus(?:e|ee|es)?\s+(?:de\s+moi|sexuel\w*) | on\s+me\s+fait\s+du\s+mal
      | pas\s+en\s+securite\s+(?:a\s+la\s+maison|chez\s+moi)
      | peur\s+de\s+rentrer | peur\s+de\s+retourner\s+a\s+la\s+maison
      | fuguer | m'enfuir\s+de\s+la\s+maison
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

_DISTRESS = re.compile(
    r"""
    \b(?:
      # ── English ──────────────────────────────────────────────────────────
        i(?:'m|\s+am)\s+(?:so\s+)?(?:sad|scared|frightened|terrified|alone|lonely|worthless|hopeless)
      | i\s+(?:feel|felt)\s+(?:so\s+)?(?:sad|scared|alone|lonely|hopeless|worthless|awful)
      | nobody\s+(?:likes|loves|cares\s+about)\s+me
      | i\s+(?:hate|can't\s+stand)\s+my ?self
      | i(?:'m|\s+am)\s+being\s+bullied | they\s+bully\s+me
      | i\s+can'?t\s+cope
      | we\s+(?:have|got)\s+no\s+(?:food|money\s+for\s+food)
      | i(?:'m|\s+am)\s+hungry\s+(?:all\s+the\s+time|every\s+day)
      # ── Spanish ──────────────────────────────────────────────────────────
      | (?:estoy|me\s+siento)\s+(?:muy\s+)?(?:triste|sol[oa]|asustad[oa]|inutil|desesperad[oa])
      | nadie\s+me\s+(?:quiere|ama) | a\s+nadie\s+le\s+importo
      | me\s+odio
      | me\s+(?:acosan|molestan|hacen\s+bullying)
      | no\s+puedo\s+mas
      | no\s+tenemos\s+comida | tengo\s+hambre\s+(?:siempre|todo\s+el\s+tiempo)
      # ── French ───────────────────────────────────────────────────────────
      | je\s+(?:suis|me\s+sens)\s+(?:tres\s+)?(?:triste|seul(?:e)?|effray(?:e|ee)|nul(?:le)?|desespere(?:e)?)
      | personne\s+ne\s+m'aime | personne\s+ne\s+se\s+soucie\s+de\s+moi
      | je\s+me\s+deteste
      | on\s+me\s+harcele | harcelement
      | je\s+n'?en\s+peux\s+plus
      | on\s+n'?a\s+pas\s+(?:de\s+)?(?:nourriture|a\s+manger)
      | j'ai\s+faim\s+(?:tout\s+le\s+temps|tous\s+les\s+jours)
    )\b
    """,
    re.VERBOSE | re.IGNORECASE,
)


def distress_level(text: str) -> str | None:
    """`"safeguarding"`, `"distress"`, or None.

    Folded first. Without it the Spanish and French patterns would only match
    a reader who typed their accents, which is exactly the reader least likely
    to be doing so on a phone keyboard in the middle of a disclosure.
    """
    folded = fold(text)
    if _SAFEGUARDING.search(folded):
        return "safeguarding"
    if _DISTRESS.search(folded):
        return "distress"
    return None


# ── off-topic, during a lesson ───────────────────────────────────────────────

#: Words that place a message inside the money curriculum.
_ON_TOPIC = re.compile(
    r"""
    \b(?:money|save|saving|saved|savings|spend|spending|spent|budget|bank|banking
      |coin|coins|dollar|dollars|cent|cents|ec\$|xcd|cash|earn|earning|earned
      |cost|costs|price|prices|buy|buying|bought|sell|selling|pay|paying|paid
      |goal|goals|deposit|account|interest|allowance|pocket\s+money|wage|wages
      |afford|cheap|expensive|worth|change|owe|borrow|lend|share|shared)\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Messages with no money word that are still on topic: the child is answering the lesson.
_LESSON_REPLY = re.compile(
    r"""
    ^\s*(?:
        yes|yeah|yep|no|nope|ok|okay|sure|maybe|dunno|i\s+don'?t\s+know
      | keep\s+going|next|ready|go\s+on|again|help|hint
      | [a-c1-4]        # a tapped option
      | \d+(?:\.\d+)?   # a numeric answer
    )\s*[.!?]?\s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def is_off_topic(text: str) -> bool:
    """Whether a message during a lesson has left the curriculum."""
    stripped = text.strip()
    if not stripped:
        return False
    if _LESSON_REPLY.match(stripped):
        return False
    return not _ON_TOPIC.search(stripped)


# ── the node ─────────────────────────────────────────────────────────────────

#: What a blocked turn says.
_BLOCKED: dict[str, str] = {
    "en": "Let's stay with what we were doing. What would you like to know?",
    "es": "Sigamos con lo que estábamos haciendo. ¿Qué te gustaría saber?",
    "fr": "Restons sur ce que nous faisions. Que veux-tu savoir ?",
}


def latest_user_text(state: AspireState) -> str:
    """The message this turn is about."""
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", None) == "human":
            content = message.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
    return ""


def safety_in(state: AspireState) -> dict[str, Any]:
    """Inspect the inbound message and put the findings on `safety_flags`."""
    text = latest_user_text(state)
    flags: dict[str, Any] = dict(state.get("safety_flags") or {})

    injections = injection_signals(text)
    if injections:
        # WARNING and one log line per turn.
        logger.warning(
            "Blocking a turn for session %s: injection signals %s.",
            state.get("session_id"),
            ", ".join(injections),
        )
        flags["injection"] = injections
        locale = state.get("locale", "en")
        from langchain_core.messages import AIMessage

        return {
            "safety_flags": flags,
            "halt_reason": "prompt_injection",
            "messages": [AIMessage(content=_BLOCKED.get(locale, _BLOCKED["en"]))],
        }

    kinds = pii.kinds_in(text)
    if kinds:
        # The kinds, never the values.
        flags["inbound_pii"] = kinds
        logger.info(
            "Inbound message for session %s contained %s; it will be redacted "
            "before it reaches the summary.",
            state.get("session_id"),
            ", ".join(kinds),
        )

    level = distress_level(text)
    if level is not None:
        flags[level] = True
        # WARNING for safeguarding: this one should page somebody.
        log = logger.warning if level == "safeguarding" else logger.info
        log(
            "Safety signal %r raised for session %s; routing to escalation.",
            level,
            state.get("session_id"),
        )

    # Every teaching agent, not just the signed-in one.
    #
    # This read `== "learn_agent"`, so the digression path was unreachable for a
    # guest (`learning_sample`) and for a guardian (`learning_preview`) -- the
    # two audiences most likely to wander, and the ones with no account behind
    # them to make the wandering safe. Measured, the 21 Aug long-thread run:
    # `learning_sample` graded "My sister's name is Renata" as a WRONG ANSWER
    # and sent the reader down the hint ladder, because `_digress` was dead code
    # for the persona actually being tested.
    if state.get("active_agent") in TEACHING_AGENTS and is_off_topic(text):
        flags["off_topic"] = True

    return {"safety_flags": flags}
