"""Three rungs, and never a fourth."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.agents.learn.state import MAX_ATTEMPTS, MAX_HINT_RUNG
from app.curriculum.schema import CheckQuestion, for_band

logger = logging.getLogger(__name__)

NUDGE, NARROW, REVEAL = 1, 2, 3

#: Words that are a verdict on the child wherever they appear.
VERDICT_WORDS: tuple[str, ...] = (
    "incorrect",
    "wrong",
    "nope",
    "failed",
    "failure",
    "mistake",
    "error",
)

#: Words that are a verdict only at the very start, where a child reads them as one.
LEADING_WORDS: tuple[str, ...] = ("no", "nah", "not quite", "bad", "sorry")

NEGATIVE_WORDS: tuple[str, ...] = VERDICT_WORDS + LEADING_WORDS

_VERDICT = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in VERDICT_WORDS) + r")\b",
    re.IGNORECASE,
)

_LEADING = re.compile(
    r"^[\s\"'“”*_]*(?:" + "|".join(re.escape(word) for word in LEADING_WORDS) + r")\b",
    re.IGNORECASE,
)

#: A bare X or cross, in any of the forms that render as one.
_CROSS = re.compile(r"[✗✘❌×]|\bX\b")


def contains_negative(text: str) -> bool:
    """Whether this hint tells a child they were wrong."""
    return bool(_VERDICT.search(text) or _LEADING.match(text) or _CROSS.search(text))


def sanitise(text: str) -> str:
    """A hint with every forbidden word removed, still readable."""
    out = _CROSS.sub("", text)
    out = _VERDICT.sub("", out)
    # Only the LEADING occurrence, and only if it leads.
    out = _LEADING.sub("", out)
    out = re.sub(r"\s{2,}", " ", out)
    # Tidy the punctuation the removal left behind: leading commas, doubled stops.
    out = re.sub(r"^[\s,.;:!-]+", "", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,.;:!?])\1+", r"\1", out)
    return out.strip()


#: Used only when a question's author left the rungs out.
FALLBACK_HINTS: dict[str, list[str]] = {
    "5-8": [
        "Ooh, so close! Have another think about it.",
        "It is one of these two. Which one feels right?",
        "Let me show you -- here is the answer, and here is why.",
    ],
    "9-12": [
        "Nearly! Think about it once more.",
        "It is one of these two. Which one?",
        "Here is the answer, and here is why it works that way.",
    ],
    "13-15": [
        "Close. Try approaching it from the other side.",
        "It is one of these two. Which fits better?",
        "Here it is, and here is the reasoning behind it.",
    ],
}


@dataclass(frozen=True, slots=True)
class Hint:
    rung: int
    text: str
    #: Rung 2 narrows to two options, so the child taps rather than recalls.
    options: list[str]
    #: True at rung 3: the answer is given, the concept is retaught, and the lesson moves on.
    reveals: bool


def rungs_for(question: CheckQuestion, band: str) -> list[str]:
    """The three hint texts for this question at this band."""
    authored = for_band(question.hints, band)
    if not authored:
        authored = FALLBACK_HINTS.get(band) or FALLBACK_HINTS["5-8"]
        logger.info(
            "Question %s has no authored hints for %s; using the generic ladder.",
            question.id,
            band,
        )

    texts = [sanitise(text) for text in list(authored)[:MAX_HINT_RUNG]]
    while len(texts) < MAX_HINT_RUNG:
        texts.append(sanitise(FALLBACK_HINTS["5-8"][len(texts)]))
    return texts


def narrow_options(question: CheckQuestion) -> list[str]:
    """Two options for rung 2: the right one and the most plausible wrong one."""
    if question.answer is None or len(question.options) < 2:
        return []
    correct = question.options[question.answer]
    other = next(
        (option for option in question.options if option != correct),
        None,
    )
    return [correct, other] if other else []


def hint_for(question: CheckQuestion, band: str, attempts: int) -> Hint:
    """The rung to give after `attempts` wrong answers."""
    texts = rungs_for(question, band)

    if attempts <= 1:
        rung = NUDGE
    elif attempts == MAX_ATTEMPTS - 1:
        rung = NARROW
    else:
        rung = REVEAL

    if rung == REVEAL:
        return Hint(rung=REVEAL, text=texts[2], options=[], reveals=True)
    if rung == NARROW:
        return Hint(rung=NARROW, text=texts[1], options=narrow_options(question), reveals=False)
    return Hint(rung=NUDGE, text=texts[0], options=[], reveals=False)


def make_hint_ladder(curriculum=None):
    """The node. Emits a hint and, at rung 3, reveals and moves on."""

    def hint_ladder(state: Any) -> dict[str, Any]:
        from app.agents.learn.state import band_of, merge
        from app.curriculum.schema import load_all

        lessons = (curriculum or load_all()).lessons
        learning = state.get("learning") or {}
        band = band_of(state)

        lesson = lessons.get(learning.get("lesson_id") or "")
        question = None
        if lesson is not None:
            question = next(
                (
                    candidate
                    for candidate in lesson.check_questions
                    if candidate.id == learning.get("question_id")
                ),
                None,
            )
        if question is None:  # pragma: no cover - guarded by the graph's routing
            return {}

        attempts = int(learning.get("attempts") or 0)
        hint = hint_for(question, band, attempts)

        from langchain_core.messages import AIMessage

        # Asserted rather than trusted.
        if contains_negative(hint.text):  # pragma: no cover - sanitise prevents it
            logger.error(
                "A negative word survived sanitising in a hint for %s; dropping it.",
                question.id,
            )
            hint = Hint(hint.rung, "Let's look at it together.", hint.options, hint.reveals)

        return {
            "messages": [AIMessage(content=hint.text)],
            "quick_replies": hint.options or _continue_chips(band, str(state.get("locale") or "en")),
            "learning": merge(
                learning,
                hint_rung=hint.rung,
                # The reveal ENDS the question.
                phase="reteaching" if hint.reveals else "checking",
            ),
        }

    return hint_ladder


def _continue_chips(band: str, locale: str = "en") -> list[str]:
    """Something to tap after a nudge, so the turn is never a dead end."""
    from app.prompting.ui_lines import chips, line

    if band == "5-8":
        return [line("try_again", locale), {"en": "Show me", "es": "Muéstrame", "fr": "Montre-moi"}.get(locale, "Show me")]
    return chips(["let_me_try_again", "show_answer"], locale)
