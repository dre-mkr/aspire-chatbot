"""Ask the child to say it back. Grade the idea, never the sentence.

Explain-it-back is the strongest retention mechanic available and it is
trivially easy to ruin. The failure mode is grading: the moment a child's
answer is marked against a phrasing, the exercise stops being "tell me what you
think" and becomes "guess the words I want", and children stop volunteering
anything.

So this grades for CONCEPT PRESENCE and nothing else.

## What is accepted

Any answer containing one of the concept words the lesson author listed. "yu
keep the muny" contains "keep" and "muny", and it is a correct answer to "what
does saving mean". It is accepted whole, with no comment about the spelling.

## What is never done

  * No spelling correction. Not gently, not in passing, not by "repeating it
    back properly".
  * No grammar correction, for the same reason.
  * No partial credit that reads as a mark. A partial answer is BUILT ON:
    "Yes -- you keep it. And what do you keep it for?"

## Voice

Bands 5-8 and 9-12 may answer by speaking, and a transcript is messy: false
starts, filler, no punctuation. `_normalise` strips filler before matching, so
"um, i think, um, you keep it?" matches "keep". That is not leniency, it is
reading a spoken answer as speech.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.curriculum.schema import for_band

logger = logging.getLogger(__name__)

#: Spoken filler and hedging, removed before matching. A child who says "um, I
#: think maybe you keep it" has answered the question.
_FILLER = re.compile(
    r"\b(?:um+|uh+|er+|erm+|like|you know|i think|i guess|maybe|kind of|sort of"
    r"|dunno|hmm+|well|so|just)\b",
    re.IGNORECASE,
)

_WORD = re.compile(r"[a-z0-9']+")

#: Answers that are not attempts. A child who says "I don't know" is asking for
#: help, and treating that as a wrong answer would run the hint ladder on
#: somebody who has already asked for the hint.
_NO_ATTEMPT = re.compile(
    r"^\s*(?:i\s*(?:do\s*n[o']?t|don'?t)\s*know|idk|dunno|no\s*idea|nothing"
    r"|\?+|help|i\s*can'?t)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def _normalise(text: str) -> list[str]:
    return _WORD.findall(_FILLER.sub(" ", text.lower()))


def _within_one_edit(left: str, right: str) -> bool:
    """Whether two words differ by at most one insertion, deletion or swap.

    This is the spelling tolerance, and it is why "yu kepp the muny" is
    accepted: "kepp" is one edit from "keep". A stemmer would not help here --
    the answers are phonetic rather than morphological, and a stemmer would
    still reject "muny".

    One edit rather than two, deliberately. Two edits starts matching genuinely
    different words ("save"/"have"), and accepting an answer the child did not
    give is worse than asking a follow-up.
    """
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True

    # Classic single-pass check. Not a full Levenshtein matrix: at a distance
    # bound of one, a single walk with one allowed divergence is sufficient and
    # runs in linear time on words a child typed.
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


#: Words short enough that one edit is most of the word. "own" and "own"
#: differing by an edit is "won", which is a different word.
_MIN_FUZZY_LENGTH = 4


def _present(word: str, haystack: str, tokens: list[str]) -> bool:
    """Whether a concept word appears in the answer, allowing for spelling.

    Exact substring first -- that covers multi-word accept entries like "put
    away" -- then a per-token fuzzy match for anything long enough that one
    edit does not turn it into a different word.
    """
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
    """The outcome of an explain-back. Note there is no score.

    `accepted` and `partial` are the only two dimensions, and neither is a
    number, because a number is a mark and a mark is the thing this exercise
    must not become.
    """

    accepted: bool
    partial: bool
    #: Which concept words the child actually used. The agent's reply quotes
    #: these back, which is what makes "building on it" concrete rather than
    #: generic praise.
    found: list[str]
    no_attempt: bool = False


def grade(answer: str, accept: list[str]) -> Grade:
    """Whether the idea is present. Deliberately generous.

    One concept word is enough. That threshold is low on purpose: the cost of
    accepting a thin answer is that the agent builds on it and asks a follow-up,
    while the cost of rejecting a real one is a child who tried and was told
    they were wrong.

    A stemming-free substring match handles "saving"/"save" and "keeping"/"keep"
    without a stemmer, because the accept lists are authored as short roots.
    """
    if _NO_ATTEMPT.match(answer or ""):
        return Grade(accepted=False, partial=False, found=[], no_attempt=True)

    tokens = _normalise(answer)
    if not tokens:
        return Grade(accepted=False, partial=False, found=[], no_attempt=True)

    haystack = " ".join(tokens)
    found = [word for word in accept if _present(word.lower(), haystack, tokens)]

    if found:
        # "Partial" means thin, not wrong: one word out of a long accept list,
        # or a very short answer. It changes what the agent SAYS next -- it asks
        # a follow-up rather than moving on -- and never what it scores.
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
#: Note it does not say they were wrong -- it offers the words.
_OFFER: dict[str, str] = {
    "5-8": "That is a hard one to say out loud! Saving is when you keep your money for later. Say it with me?",
    "9-12": "It is tricky to put into words. Saving means keeping money now so you have it later. Does that sound right to you?",
    "13-15": "Harder to say than to know, that one. Saving is choosing to keep money now for later. Would you put it differently?",
}


def _quote(found: list[str], band: str) -> str:
    """The child's own words, handed back to them.

    Quoting is what makes acceptance feel real. "Well done!" is a noise; "you
    said keep -- that is exactly the word" is somebody having listened.
    """
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
    """The node. Asks, or grades an answer already given.

    Which of the two it does is decided by `phase`: arriving in `checking` it
    asks the question, arriving in `explaining_back` it grades the reply. One
    node rather than two because they share the question lookup and the band
    resolution, and splitting them would mean two places that could disagree
    about which question is being asked.
    """

    def explain_back(state: Any) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        from app.agents.learn.state import merge
        from app.curriculum.schema import load_all
        from app.graph.nodes.safety_in import latest_user_text

        lessons = (curriculum or load_all()).lessons
        learning = state.get("learning") or {}
        band = str(state.get("age_band") or "9-12")

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
            # No explain-back authored for this lesson. Skipping is correct --
            # inventing one would be generating curriculum at runtime.
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
                # An unaccepted explain-back is NOT wrong-answer evidence: the
                # child was asked to articulate, not to be right.
                explain_accepted=result.accepted,
            ),
        }

    return explain_back


def _chips(band: str) -> list[str]:
    if band == "5-8":
        return ["Say it", "Skip"]
    return ["Next", "Skip this"]
