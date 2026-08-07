"""What a lesson must be, checked in code rather than asked for in a prompt.

A prompt that says "40 to 90 words" produces 30-word replies often enough that
the instruction is decorative. This module is the same requirement expressed as a
predicate, so a lesson that misses it is *detected* rather than merely
discouraged -- which is the difference between the three-tier guarantee in
`render.py` and a hopeful adjective.

## The numbers, and why they differ from `safety_out.WORD_CAPS`

`WORD_CAPS` is a reading-stamina ceiling for a mascot's conversational turn:
thirty-five words at 5-8, which is three short sentences. That is correct for a
chat turn and it is *below the floor of a lesson*. A concept explained in
thirty-five words to a six-year-old is a definition read aloud, which is the
reported symptom of this whole workstream stated as a specification.

So a learning turn has its own band contract with a FLOOR as well as a ceiling,
and `safety_out` reads the lesson caps for learning agents (`LESSON_WORD_CAPS`).
The two are reconciled in one place, here, rather than left to disagree -- a
prompt asking for more words than the outbound gate permits produces a re-prompt
on every single turn, which is a second model call forever caused by two
constants drifting apart.

## Sentence caps are about clause count, not about style

Twelve words is roughly one clause. A six-year-old reading a twenty-word sentence
loses the subject before the verb arrives, and the failure is silent -- they do
not report confusion, they disengage. Checked as a maximum over sentences rather
than as a mean, because one long sentence in a short paragraph is the whole
paragraph for a reader who stalls on it.

## Exactly one question, and it is the check question

A lesson that ends with two questions asks a child to choose which to answer,
and a lesson that ends with none has not checked anything. The count is over `?`
in the prose, which also catches the model's habit of asking a rhetorical
question mid-explanation -- fine for an adult, an invitation to answer for a
seven-year-old.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

#: The lesson contract, per band.
#:
#: `min_words` is the number this whole workstream is about. `max_words` matches
#: `safety_out.LESSON_WORD_CAPS` exactly; see the module docstring on why the two
#: must not drift.
@dataclass(frozen=True, slots=True)
class BandContract:
    band: str
    min_words: int
    max_words: int
    #: Longest single sentence, in words. None for adult bands.
    max_sentence_words: int | None
    #: The shape the prompt asks for, quoted back on a retry.
    structure: str
    #: Whether bullet lists are permitted at all.
    allows_lists: bool = False


CONTRACTS: dict[str, BandContract] = {
    "5-8": BandContract(
        band="5-8",
        min_words=40,
        max_words=90,
        max_sentence_words=12,
        structure="hook, then the idea, then an EC$ example, then the check question",
    ),
    "9-12": BandContract(
        band="9-12",
        min_words=60,
        max_words=120,
        max_sentence_words=16,
        structure="hook, then the idea, then an EC$ example, then the check question",
    ),
    "13-15": BandContract(
        band="13-15",
        min_words=90,
        max_words=180,
        max_sentence_words=24,
        structure=(
            "hook, then how it works, then an EC$ example, then why it matters, "
            "then the check question"
        ),
    ),
    "16-18": BandContract(
        band="16-18",
        min_words=90,
        max_words=180,
        max_sentence_words=24,
        structure=(
            "hook, then how it works, then an EC$ example, then why it matters, "
            "then the check question"
        ),
        allows_lists=True,
    ),
    "adult": BandContract(
        band="adult",
        min_words=120,
        max_words=220,
        max_sentence_words=None,
        structure=(
            "context, then how it works, then an EC$ example, then what to do, "
            "then the check question"
        ),
        allows_lists=True,
    ),
}

#: The band used when the reader's is unknown. The MIDDLE of the ladder, matching
#: `state.FALLBACK_BAND`: defaulting to 5-8 would serve a teenager baby talk, and
#: defaulting to adult would serve a child an unbounded lesson.
FALLBACK_BAND = "9-12"


def contract_for(band: str) -> BandContract:
    return CONTRACTS.get(band) or CONTRACTS[FALLBACK_BAND]


# ── measurement ──────────────────────────────────────────────────────────────

#: Sentence terminators. Mirrors `safety_out._SENTENCE_END` so that "how many
#: sentences is this?" has one answer in the product.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")

_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)
_MARKDOWN_LIST = re.compile(r"^\s{0,3}[-*•]\s+|^\s{0,3}\d+[.)]\s+", re.MULTILINE)

#: Emoji and pictographs, by block. Not exhaustive and does not need to be -- the
#: rule is "at most one", and the blocks below cover everything a model reaches
#: for when writing warmly to a child.
_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff⬀-⯿]"
)


def word_count(text: str) -> int:
    """Words, by whitespace. The same definition `safety_out.word_count` uses."""
    return len(text.split())


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]


def longest_sentence_words(text: str) -> int:
    return max((word_count(sentence) for sentence in sentences(text)), default=0)


def question_count(text: str) -> int:
    return text.count("?")


# ── the check ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ContractViolation:
    code: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ContractResult:
    """Whether a rendered lesson may be served, and if not, precisely why.

    The violations are quoted back to the model on the retry. "Be more thorough"
    moves a word count by ten percent; "that was 22 words and this band needs at
    least 60, structured as hook / idea / EC$ example / check question" produces
    one that fits, because the model can count.
    """

    ok: bool
    violations: tuple[ContractViolation, ...] = ()
    words: int = 0

    def quoted(self) -> str:
        return "\n".join(f"  - {violation}" for violation in self.violations)


def check_lesson(
    text: str,
    *,
    band: str,
    expect_question: bool = True,
    grounding_terms: Iterable[str] = (),
) -> ContractResult:
    """Whether this is a lesson. Deterministic, and the only judge that matters.

    `grounding_terms` is the concept body's vocabulary. Its absence is the
    brief's "contains no sentence from the concept body's semantic neighbourhood"
    check, implemented as term overlap rather than as an embedding comparison --
    the failure being caught is a model that ignored the body and wrote from its
    own knowledge, and that failure shows up as *none of the concept's words
    appearing*, which lexical overlap detects exactly and an embedding comparison
    detects fuzzily at the cost of a network call inside a validator.
    """
    contract = contract_for(band)
    violations: list[ContractViolation] = []
    body = text.strip()
    words = word_count(body)

    if not body:
        return ContractResult(
            ok=False,
            violations=(ContractViolation("EMPTY", "no prose was produced at all"),),
            words=0,
        )

    if words < contract.min_words:
        violations.append(
            ContractViolation(
                "TOO_SHORT",
                f"that lesson is {words} words; a {band} learner needs at least "
                f"{contract.min_words}, written as {contract.structure}",
            )
        )
    elif words > contract.max_words:
        violations.append(
            ContractViolation(
                "TOO_LONG",
                f"that lesson is {words} words; the {band} ceiling is "
                f"{contract.max_words}",
            )
        )

    if contract.max_sentence_words is not None:
        longest = longest_sentence_words(body)
        if longest > contract.max_sentence_words:
            violations.append(
                ContractViolation(
                    "SENTENCE_TOO_LONG",
                    f"the longest sentence is {longest} words; at {band} no sentence "
                    f"may exceed {contract.max_sentence_words}",
                )
            )

    questions = question_count(body)
    if expect_question and questions == 0:
        violations.append(
            ContractViolation("NO_QUESTION", "the lesson ends with no check question")
        )
    elif questions > 1:
        violations.append(
            ContractViolation(
                "TOO_MANY_QUESTIONS",
                f"there are {questions} questions; a lesson asks exactly one, at the end",
            )
        )
    elif not expect_question and questions > 0:
        violations.append(
            ContractViolation("UNEXPECTED_QUESTION", "this move asks no question")
        )

    if _MARKDOWN_HEADING.search(body):
        violations.append(ContractViolation("MARKUP", "the lesson contains a heading"))
    if not contract.allows_lists and _MARKDOWN_LIST.search(body):
        violations.append(
            ContractViolation("MARKUP", f"the lesson contains a list; {band} gets prose")
        )

    if len(_EMOJI.findall(body)) > 1:
        violations.append(ContractViolation("EMOJI", "at most one emoji in a lesson"))

    terms = [term for term in grounding_terms if term]
    if terms:
        lowered = body.lower()
        if not any(term.lower() in lowered for term in terms):
            violations.append(
                ContractViolation(
                    "UNGROUNDED",
                    "the lesson uses none of the concept's own words, so it was "
                    "written from general knowledge rather than from the material given",
                )
            )

    return ContractResult(ok=not violations, violations=tuple(violations), words=words)


# ── TTS safety ───────────────────────────────────────────────────────────────

#: What a text-to-speech voice reads badly, and what to say instead.
#:
#: "EC$25" is read as "E C dollar sign twenty five" by every engine this was
#: tested against. The substitution happens on the VOICE channel only -- the
#: screen keeps "EC$25", which is what a reader expects to see and what the
#: currency actually looks like.
_TTS_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"EC\$\s?([\d,]+(?:\.\d{2})?)"), r"\1 EC dollars"),
    (re.compile(r"XCD\s?([\d,]+(?:\.\d{2})?)"), r"\1 EC dollars"),
    (re.compile(r"\bEC\$"), "EC dollars"),
    (re.compile(r"([\d.]+)\s?%"), r"\1 percent"),
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"\s*/\s*"), " or "),
    # Parentheticals are an aside a reader skims and a listener cannot. Removed
    # rather than reordered: an aside that mattered belongs in a sentence.
    (re.compile(r"\s*\([^)]*\)"), ""),
    (re.compile(r"\s*--\s*"), ", "),
    (re.compile(r"\s*—\s*"), ", "),
)


def tts_safe(text: str) -> str:
    """The lesson as a voice should read it.

    Applied on the voice channel only. The screen and the audio are the same
    lesson said two ways, not two lessons -- so this is a rendering of one string
    rather than a second generation, which is also what keeps them from drifting.
    """
    out = text
    for pattern, replacement in _TTS_SUBSTITUTIONS:
        out = pattern.sub(replacement, out)
    return re.sub(r"\s{2,}", " ", out).strip()
