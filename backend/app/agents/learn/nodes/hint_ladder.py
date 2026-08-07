"""Three rungs, and never a fourth.

    rung 1  NUDGE   "Ooh, so close! Think about where the money goes first."
    rung 2  NARROW  "It's one of these two. Which one?"   (two quick replies)
    rung 3  REVEAL  "It's saving! Here's why..."          then teach and move on

Hard cap at two wrong attempts before rung 3. There is no third attempt,
because the third attempt is the one where a child concludes they are bad at
this and closes the app.

## The forbidden words

"Incorrect", "Wrong", "No", and a bare X. Not softened -- absent. `sanitise`
strips them from any authored or generated hint, and `NEGATIVE_WORDS` is the
list. This is not squeamishness: a nine-year-old reading "Incorrect" from a
mascot who has been warm for eight minutes reads it as the mascot's opinion of
them.

What replaces them is not praise for a wrong answer, which children see through
instantly. It is a redirection: "Ooh, so close! Think about where the money goes
first." acknowledges the attempt and points at the thing to reconsider.

## Hints are authored, not generated

Every rung is written in the lesson YAML, band-keyed. A generated hint is a
different hint every time a child fails the same question, which makes the
ladder feel arbitrary -- and it is one more place a banned word can enter.

`FALLBACK_HINTS` exists for a question whose author left the rungs out. It is
generic and it is deliberately not good, so that its appearance in a session log
is a prompt to write the real ones.
"""

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
#:
#: These have no innocent use inside a hint. There is no sentence in a
#: children's money lesson that legitimately needs "incorrect".
VERDICT_WORDS: tuple[str, ...] = (
    "incorrect",
    "wrong",
    "nope",
    "failed",
    "failure",
    "mistake",
    "error",
)

#: Words that are only a verdict IN VERDICT POSITION -- at the very start,
#: where a child reads them as the answer to what they just did.
#:
#: "no" is the reason this second list exists. Banning it outright would flag
#: "a plan with no enjoyment in it is a plan you abandon", which is a perfectly
#: good sentence, and `sanitise` would then delete the word and leave a lie. It
#: is only ever a verdict when it opens the hint.
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
    """Whether this hint tells a child they were wrong.

    Two different tests, because the two failures are different. A verdict word
    is a verdict anywhere in the sentence; an ordinary negation is a verdict
    only when it is the first thing read.
    """
    return bool(_VERDICT.search(text) or _LEADING.match(text) or _CROSS.search(text))


def sanitise(text: str) -> str:
    """A hint with every forbidden word removed, still readable.

    Removal rather than substitution. Swapping "wrong" for "not quite right"
    would produce a sentence that still says the same thing in the same place,
    and the sentence is usually better without the clause at all: "That's wrong
    -- think about where the money goes" reads perfectly as "Think about where
    the money goes".
    """
    out = _CROSS.sub("", text)
    out = _VERDICT.sub("", out)
    # Only the LEADING occurrence, and only if it leads. Removing every "no"
    # would turn "a plan with no enjoyment" into its own opposite, which is a
    # worse failure than the one being fixed.
    out = _LEADING.sub("", out)
    out = re.sub(r"\s{2,}", " ", out)
    # Tidy the punctuation the removal left behind: a leading comma, a doubled
    # full stop, a dangling dash.
    out = re.sub(r"^[\s,.;:!-]+", "", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,.;:!?])\1+", r"\1", out)
    return out.strip()


#: Used only when a question's author left the rungs out. Generic on purpose --
#: its appearance in a log is a prompt to write the real ones.
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
    #: True at rung 3: the answer is given, the concept is retaught, and the
    #: lesson moves on. There is no fourth attempt.
    reveals: bool


def rungs_for(question: CheckQuestion, band: str) -> list[str]:
    """The three hint texts for this question at this band.

    Falls back band-downward first (a 9-12 hint for a 13-15 learner is fine),
    then to `FALLBACK_HINTS`, then to the 5-8 generic set. Always three, always
    sanitised.
    """
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
    """Two options for rung 2: the right one and the most plausible wrong one.

    "The most plausible" is simply the first other option, because lesson
    authors put the tempting distractor first -- and picking it by a heuristic
    the author cannot see would make the narrowing unpredictable to them.

    A free-text question has no options, and rung 2 then narrows nothing: the
    hint text still helps, and `options` is empty rather than invented.
    """
    if question.answer is None or len(question.options) < 2:
        return []
    correct = question.options[question.answer]
    other = next(
        (option for option in question.options if option != correct),
        None,
    )
    return [correct, other] if other else []


def hint_for(question: CheckQuestion, band: str, attempts: int) -> Hint:
    """The rung to give after `attempts` wrong answers.

    One wrong answer gets the nudge. Two get the narrowing. The cap is enforced
    here rather than by the caller, so there is no code path on which a third
    attempt is requested: `attempts >= MAX_ATTEMPTS` returns the reveal, and
    the reveal ends the question.
    """
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

        # Asserted rather than trusted. The hint text is authored content and
        # `sanitise` has already run on it -- this is the check that a bad edit
        # to a YAML file cannot put "Wrong." in front of a child.
        if contains_negative(hint.text):  # pragma: no cover - sanitise prevents it
            logger.error(
                "A negative word survived sanitising in a hint for %s; dropping it.",
                question.id,
            )
            hint = Hint(hint.rung, "Let's look at it together.", hint.options, hint.reveals)

        return {
            "messages": [AIMessage(content=hint.text)],
            "quick_replies": hint.options or _continue_chips(band),
            "learning": merge(
                learning,
                hint_rung=hint.rung,
                # The reveal ENDS the question. The phase moves to reteach, which
                # explains the answer and advances -- there is no route from here
                # back to another attempt.
                phase="reteaching" if hint.reveals else "checking",
            ),
        }

    return hint_ladder


def _continue_chips(band: str) -> list[str]:
    """Something to tap after a nudge, so the turn is never a dead end."""
    if band == "5-8":
        return ["Try again", "Show me"]
    return ["Let me try again", "Show me the answer"]
