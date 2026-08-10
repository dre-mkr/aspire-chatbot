"""Ask the child to say it back."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.curriculum.schema import for_band

logger = logging.getLogger(__name__)

#: Spoken filler and hedging, removed before matching.
_FILLER = re.compile(
    r"\b(?:um+|uh+|er+|erm+|like|you know|i think|i guess|maybe|kind of|sort of"
    r"|dunno|hmm+|well|so|just)\b",
    re.IGNORECASE,
)

_WORD = re.compile(r"[a-z0-9']+")

#: Answers that are not attempts.
_NO_ATTEMPT = re.compile(
    r"^\s*(?:i\s*(?:do\s*n[o']?t|don'?t)\s*know|idk|dunno|no\s*idea|nothing"
    r"|\?+|help|i\s*can'?t)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def _normalise(text: str) -> list[str]:
    return _WORD.findall(_FILLER.sub(" ", text.lower()))


def _within_one_edit(left: str, right: str) -> bool:
    """Whether two words differ by at most one insertion, deletion or swap."""
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True

    # Classic single-pass check.
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    index_short = index_long = 0
    used = False
    while index_short < len(short) and index_long < len(long):
        if short[index_short] == long[index_long]:
            index_short += 1
            index_long += 1
            continue
        if used:
            return False
        used = True
        if len(short) == len(long):
            index_short += 1
        index_long += 1
    return True


#: Words short enough that one edit is most of the word.
_MIN_FUZZY_LENGTH = 4


def _present(word: str, haystack: str, tokens: list[str]) -> bool:
    """Whether a concept word appears in the answer, allowing for spelling."""
    if word in haystack:
        return True
    if len(word) < _MIN_FUZZY_LENGTH or " " in word:
        return False
    return any(
        len(token) >= _MIN_FUZZY_LENGTH and _within_one_edit(token, word)
        for token in tokens
    )


@dataclass(frozen=True, slots=True)
class Grade:
    """The outcome of an explain-back."""

    accepted: bool
    partial: bool
    #: Which concept words the child actually used.
    found: list[str]
    no_attempt: bool = False


def grade(answer: str, accept: list[str]) -> Grade:
    """Whether the idea is present."""
    if _NO_ATTEMPT.match(answer or ""):
        return Grade(accepted=False, partial=False, found=[], no_attempt=True)

    tokens = _normalise(answer)
    if not tokens:
        return Grade(accepted=False, partial=False, found=[], no_attempt=True)

    haystack = " ".join(tokens)
    found = [word for word in accept if _present(word.lower(), haystack, tokens)]

    if found:
        # "Partial" means thin, not wrong: one word out of a long accept list, or a very short answer.
        partial = len(found) == 1 and len(tokens) <= 4
        return Grade(accepted=True, partial=partial, found=found)

    return Grade(accepted=False, partial=False, found=[])


# ── what the agent says ──────────────────────────────────────────────────────

_ACCEPTED: dict[str, str] = {
    "5-8": "Yes! That is exactly it. {quote}",
    "9-12": "That is it exactly. {quote}",
    "13-15": "Yes -- that is the idea. {quote}",
}

_PARTIAL: dict[str, str] = {
    "5-8": "Yes -- {quote} And what do you keep it for?",
    "9-12": "Yes, {quote} Can you add what you are keeping it for?",
    "13-15": "Right so far -- {quote} What is the other half of it?",
}

#: For a child who did not attempt, or whose answer had none of the idea in it.
_OFFER: dict[str, str] = {
    "5-8": "That is a hard one to say out loud! Saving is when you keep your money for later. Say it with me?",
    "9-12": "It is tricky to put into words. Saving means keeping money now so you have it later. Does that sound right to you?",
    "13-15": "Harder to say than to know, that one. Saving is choosing to keep money now for later. Would you put it differently?",
}


def _quote(found: list[str], band: str) -> str:
    """The child's own words, handed back to them."""
    if not found:
        return ""
    word = found[0]
    if band == "5-8":
        return f"You said “{word}”, and that is the important word."
    return f"You said “{word}”, which is the heart of it."


def response_for(result: Grade, band: str) -> str:
    """What to say back. Never a correction of spelling or grammar."""
    templates = (
        _ACCEPTED
        if result.accepted and not result.partial
        else _PARTIAL
        if result.accepted
        else _OFFER
    )
    template = templates.get(band) or templates["9-12"]
    return template.format(quote=_quote(result.found, band)).strip()


def make_explain_back(curriculum=None):
    """The node."""

    def explain_back(state: Any) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        from app.agents.learn.state import band_of, merge
        from app.curriculum.schema import load_all
        from app.graph.nodes.safety_in import latest_user_text

        lessons = (curriculum or load_all()).lessons
        learning = state.get("learning") or {}
        band = band_of(state)

        lesson = lessons.get(learning.get("lesson_id") or "")
        if lesson is None:  # pragma: no cover - guarded by routing
            return {}

        question = next(
            (
                candidate
                for candidate in lesson.check_questions
                if not candidate.graded
            ),
            None,
        )
        if question is None:
            # No explain-back authored for this lesson.
            return {"learning": merge(learning, phase="updating_mastery")}

        if learning.get("phase") != "explaining_back":
            prompt = for_band(question.prompt, band) or next(iter(question.prompt.values()))
            return {
                "messages": [AIMessage(content=prompt)],
                "quick_replies": _chips(band),
                "learning": merge(
                    learning, phase="explaining_back", question_id=question.id
                ),
            }

        result = grade(latest_user_text(state), question.accept)
        logger.info(
            "explain_back lesson=%s accepted=%s partial=%s found=%s",
            lesson.id,
            result.accepted,
            result.partial,
            result.found,
        )

        return {
            "messages": [AIMessage(content=response_for(result, band))],
            "quick_replies": _chips(band),
            "learning": merge(
                learning,
                phase="updating_mastery",
                # Recorded so `mastery_update` knows which evidence to apply.
                explain_accepted=result.accepted,
            ),
        }

    return explain_back


def _chips(band: str) -> list[str]:
    if band == "5-8":
        return ["Say it", "Skip"]
    return ["Next", "Skip this"]
