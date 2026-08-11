"""What did the learner just demonstrate?

The tutor's loop was open at this end. `plan_move` could ask for a hint, a
harder application or a re-teach, but nothing ever looked at what the learner
actually said, so `consecutive_wrong` stayed at zero, `Move.HINT` was
unreachable, and every check question was followed by a turn that had no idea
whether it had been answered.

This module closes it. One check answer in, one `Evaluation` out:

    verdict     -- did they get it
    diagnosis   -- WHY they missed it, which is the part that changes teaching
    misconception -- which of the concept's own authored misconceptions they hold

The order matters. A deterministic match against the authored accept list is
tried first and settles most answers for nothing; the model is asked only when
the accept list cannot decide, and its answer is constrained to this module's
vocabulary rather than parsed out of prose.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.learning.concepts import CheckItem, TeachingConcept

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    """How the attempt went."""

    CORRECT = "CORRECT"
    #: The right idea with a piece missing, or right by luck with wrong reasoning.
    PARTIAL = "PARTIAL"
    WRONG = "WRONG"
    #: "I don't know." Not a wrong answer, and teaching it as one is a mistake.
    DONT_KNOW = "DONT_KNOW"
    #: "Just tell me." An explicit request outranks the hint ladder.
    ASKS_FOR_ANSWER = "ASKS_FOR_ANSWER"
    #: Nothing to grade -- they changed the subject or said something unrelated.
    NOT_AN_ANSWER = "NOT_AN_ANSWER"

    @property
    def is_success(self) -> bool:
        return self is Verdict.CORRECT

    @property
    def is_attempt(self) -> bool:
        """Whether the learner actually tried, which is what mastery counts."""
        return self in (Verdict.CORRECT, Verdict.PARTIAL, Verdict.WRONG)


class Diagnosis(str, Enum):
    """Why the attempt missed. The categories §13 of the brief names."""

    NONE = "NONE"
    #: They hold a specific, nameable wrong model of how it works.
    CONCEPTUAL = "CONCEPTUAL_MISUNDERSTANDING"
    #: The method was right and the arithmetic was not.
    CALCULATION = "CALCULATION_ERROR"
    #: They mean the right thing and are using the wrong word for it.
    TERMINOLOGY = "TERMINOLOGY_CONFUSION"
    #: Each step is defensible; the chain does not reach the conclusion.
    REASONING = "REASONING_ERROR"
    #: Right as far as it goes, and it does not go far enough.
    INCOMPLETE = "INCOMPLETE_UNDERSTANDING"
    #: An answer with nothing behind it.
    GUESS = "GUESS"
    #: They have not met the idea in any usable form.
    NO_UNDERSTANDING = "NO_UNDERSTANDING"

    @property
    def needs_reteach(self) -> bool:
        """Whether a hint would be pointless because the model underneath is wrong."""
        return self in (Diagnosis.CONCEPTUAL, Diagnosis.NO_UNDERSTANDING)


@dataclass(frozen=True, slots=True)
class Evaluation:
    """One graded answer."""

    verdict: Verdict = Verdict.NOT_AN_ANSWER
    diagnosis: Diagnosis = Diagnosis.NONE
    #: The `wrong` half of the concept's authored misconception they appear to hold.
    misconception: str = ""
    #: What to say about it, in the tutor's voice. Never shown raw to the learner.
    feedback: str = ""
    #: How the verdict was reached, for the health log: accept_list | model | heuristic.
    source: str = "heuristic"

    @property
    def correct(self) -> bool:
        return self.verdict.is_success


# ── the deterministic pass ───────────────────────────────────────────────────

#: Explicit requests for the answer. These outrank the ladder -- §12.
_ASKS_FOR_ANSWER = re.compile(
    r"""\b(?:
        (?:just\s+)?(?:tell|give|show)\s+me\s+(?:the\s+)?(?:answer|it|solution)
      | what(?:'?s|\s+is)\s+the\s+answer
      | (?:i\s+)?give\s+up
      | show\s+me\s+how
      | i\s+want\s+the\s+answer
    )\b""",
    re.VERBOSE | re.IGNORECASE,
)

#: Admissions of not being able to answer THIS QUESTION. Deliberately narrower
#: than "I don't understand", which is about the explanation rather than the
#: question and is `tutor.sounds_confused`'s business: one is scaffolded with a
#: hint, the other is answered by teaching it a different way.
_DONT_KNOW = re.compile(
    r"""^\s*(?:
        i\s+(?:really\s+)?(?:do\s*n[o']?t|don'?t)\s+know(?:\s+(?:it|that|this))?
      | (?:i\s+have\s+)?(?:no|not\s+(?:a|the)\s+)\s*idea
      | dunno | idk | no\s+clue | not\s+sure | unsure | no\s+idea
      | \?+
    )\s*[.!?]*\s*$""",
    re.VERBOSE | re.IGNORECASE,
)

#: Words that carry no answer, stripped before comparing against the accept list.
_FILLER = frozenset(
    "i think its it is the a an of to be would will maybe probably um er well "
    "so like that this because since answer my guess reckon say".split()
)

_WORD = re.compile(r"[a-z0-9$%.]+")


def _keywords(text: str) -> frozenset[str]:
    """Content words, for comparing an answer against an accept term."""
    return frozenset(
        word.strip(".,;:!?")
        for word in _WORD.findall((text or "").lower())
        if word not in _FILLER and len(word.strip(".,;:!?")) > 1
    )


def match_accept_list(item: CheckItem, answer: str) -> bool | None:
    """True, False, or None when the accept list cannot decide.

    None is a real outcome and the reason this function is not a bool. An
    accept list that does not match is only evidence of a wrong answer when the
    list is the kind that can match -- a free-text answer to a question whose
    author wrote no accept terms tells us nothing, and grading it False would
    punish the learner for the author's omission.
    """
    text = (answer or "").strip().lower()
    if not text:
        return None

    terms = [term.lower().strip() for term in item.accept if term.strip()]
    if item.answer:
        terms.append(item.answer.lower().strip())
    if not terms:
        return None

    for term in terms:
        if not term:
            continue
        # A whole authored term appearing in the answer is the strongest signal.
        if term in text:
            return True
        # Or every content word of the term, in any order.
        term_words = _keywords(term)
        if term_words and term_words <= _keywords(text):
            return True

    # A short answer that matched nothing is a wrong answer. A long one may have
    # said the right thing in its own words, which only the model can judge.
    return False if len(text.split()) <= 6 else None


def triage(answer: str) -> Verdict | None:
    """The verdicts that are decided by what was said, not by whether it is right."""
    text = (answer or "").strip()
    if not text:
        return Verdict.NOT_AN_ANSWER
    if _ASKS_FOR_ANSWER.search(text):
        return Verdict.ASKS_FOR_ANSWER
    if _DONT_KNOW.match(text):
        return Verdict.DONT_KNOW
    return None


# ── the model pass ───────────────────────────────────────────────────────────

_EVALUATE_SYSTEM = """You are marking one answer from a learner, for a tutor who will
teach differently depending on what you say. You are not talking to the learner.

Reply with JSON only:
{"verdict": "...", "diagnosis": "...", "misconception": "...", "feedback": "..."}

verdict is one of:
  CORRECT     - they have it, in their own words or the expected ones
  PARTIAL     - the right idea with a piece missing, or right with faulty reasoning
  WRONG       - they answered, and it is not right
  DONT_KNOW   - they said they do not know rather than attempting it
  NOT_AN_ANSWER - they said something that is not an attempt at this question

diagnosis explains a PARTIAL or WRONG and is NONE otherwise. One of:
  CONCEPTUAL_MISUNDERSTANDING - they hold a specific wrong model of how it works
  CALCULATION_ERROR           - right method, wrong arithmetic
  TERMINOLOGY_CONFUSION       - right idea, wrong word for it
  REASONING_ERROR             - the steps do not reach the conclusion
  INCOMPLETE_UNDERSTANDING    - right as far as it goes
  GUESS                       - an answer with nothing behind it
  NO_UNDERSTANDING            - they have not met this idea in any usable form
  NONE

misconception: if their answer matches one of the KNOWN MISCONCEPTIONS below, copy
that misconception's exact text. Otherwise "".

feedback: one or two sentences the tutor can say, addressing what THEY said. Name the
specific thing that was right before the thing that was not. No praise words, no
"great job", no exclamation marks. If they were wrong, do not give the answer away.

Be generous about wording and strict about the idea. A learner who has the concept in
plain words is CORRECT even if they used none of the expected terms."""


def _evaluation_prompt(
    *, item: CheckItem, answer: str, concept: TeachingConcept | None, band: str
) -> str:
    parts = [f"QUESTION: {item.question}"]
    if item.answer:
        parts.append(f"EXPECTED ANSWER: {item.answer}")
    if item.accept:
        parts.append(f"ALSO ACCEPTABLE: {', '.join(item.accept)}")
    if concept is not None and concept.misconceptions:
        known = "\n".join(
            f"- {entry.wrong}" for entry in concept.misconceptions[:4] if entry.wrong
        )
        if known:
            parts.append(f"KNOWN MISCONCEPTIONS for this concept:\n{known}")
    parts.append(f"The learner is in the {band} age band.")
    parts.append(f"THEIR ANSWER: {answer}")
    return "\n\n".join(parts)


def _coerce(payload: dict[str, Any]) -> Evaluation:
    """The model's object into an `Evaluation`, keeping only known vocabulary."""
    try:
        verdict = Verdict(str(payload.get("verdict") or "").strip().upper())
    except ValueError:
        verdict = Verdict.NOT_AN_ANSWER

    try:
        diagnosis = Diagnosis(str(payload.get("diagnosis") or "NONE").strip().upper())
    except ValueError:
        diagnosis = Diagnosis.NONE

    # A correct answer has no diagnosis, whatever the model volunteered.
    if verdict is Verdict.CORRECT:
        diagnosis = Diagnosis.NONE

    return Evaluation(
        verdict=verdict,
        diagnosis=diagnosis,
        misconception=str(payload.get("misconception") or "").strip()[:300],
        feedback=str(payload.get("feedback") or "").strip()[:400],
        source="model",
    )


# ── the entry point ──────────────────────────────────────────────────────────


async def evaluate_answer(
    answer: str,
    *,
    item: CheckItem | None,
    concept: TeachingConcept | None = None,
    band: str = "9-12",
    invoke: Any = None,
) -> Evaluation:
    """Grade one check answer.

    Never raises. A grading failure returns `PARTIAL`, which is the honest
    reading of "we could not tell" -- it neither credits the learner with an
    answer they may not have given nor tells them they were wrong on the
    strength of an exception.
    """
    if item is None:
        return Evaluation(verdict=Verdict.NOT_AN_ANSWER, source="heuristic")

    early = triage(answer)
    if early is not None:
        return Evaluation(
            verdict=early,
            diagnosis=(
                Diagnosis.NO_UNDERSTANDING if early is Verdict.DONT_KNOW else Diagnosis.NONE
            ),
            source="heuristic",
        )

    matched = match_accept_list(item, answer)
    if matched is True:
        return Evaluation(
            verdict=Verdict.CORRECT,
            feedback=item.explanation_on_correct,
            source="accept_list",
        )

    if invoke is not None:
        try:
            payload = await invoke(
                system=_EVALUATE_SYSTEM,
                user=_evaluation_prompt(
                    item=item, answer=answer, concept=concept, band=band
                ),
            )
        except Exception:
            logger.warning("The evaluation call failed.", exc_info=True)
            payload = None

        if isinstance(payload, dict) and payload:
            evaluation = _coerce(payload)
            # The authored explanation beats a generated one when the model
            # agrees with the accept list, because it was written by a person
            # who knows this question.
            if evaluation.correct and item.explanation_on_correct:
                evaluation = Evaluation(
                    verdict=evaluation.verdict,
                    diagnosis=evaluation.diagnosis,
                    misconception=evaluation.misconception,
                    feedback=item.explanation_on_correct,
                    source=evaluation.source,
                )
            return evaluation

    # No model, or it gave nothing usable. Fall back to what the accept list said.
    if matched is False:
        return Evaluation(
            verdict=Verdict.WRONG,
            diagnosis=Diagnosis.INCOMPLETE,
            feedback=item.explanation_on_wrong,
            source="accept_list",
        )
    return Evaluation(verdict=Verdict.PARTIAL, diagnosis=Diagnosis.INCOMPLETE)


# ── what the evaluation does to the learner's record ─────────────────────────


def evidence_for(evaluation: Evaluation, *, hinted: bool) -> Any:
    """The mastery evidence this attempt is worth, or None if it is not evidence.

    Saying "I don't know" is not a wrong answer. It is the absence of an
    attempt, and dropping a learner's score for admitting it would teach them
    to guess instead.
    """
    from app.learning.mastery import Evidence

    if evaluation.verdict is Verdict.CORRECT:
        return Evidence.CORRECT_AFTER_HINTS if hinted else Evidence.CORRECT
    if evaluation.verdict in (Verdict.WRONG, Verdict.PARTIAL):
        return Evidence.WRONG
    return None
