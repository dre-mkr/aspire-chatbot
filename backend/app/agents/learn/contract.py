"""What a lesson must be, checked in code rather than asked for in a prompt."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

#: The lesson contract, per band.
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

#: The band used when the reader's is unknown.
FALLBACK_BAND = "9-12"


def contract_for(band: str) -> BandContract:
    return CONTRACTS.get(band) or CONTRACTS[FALLBACK_BAND]


# ── measurement ──────────────────────────────────────────────────────────────

#: Sentence terminators.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")

_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)
_MARKDOWN_LIST = re.compile(r"^\s{0,3}[-*•]\s+|^\s{0,3}\d+[.)]\s+", re.MULTILINE)

#: Emoji and pictographs, by block.
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


#: Violations that mean this is not a lesson.
BLOCKING: frozenset[str] = frozenset(
    {"EMPTY", "TOO_SHORT", "UNGROUNDED", "NO_QUESTION", "TOO_MANY_QUESTIONS"}
)


@dataclass(frozen=True, slots=True)
class ContractResult:
    """Whether a rendered lesson may be served, and if not, precisely why."""

    ok: bool
    violations: tuple[ContractViolation, ...] = ()
    words: int = 0

    @property
    def blocking(self) -> tuple[ContractViolation, ...]:
        """The violations that mean this is not a lesson."""
        return tuple(v for v in self.violations if v.code in BLOCKING)

    @property
    def servable(self) -> bool:
        """Whether this may be served as it stands."""
        return not self.blocking

    def quoted(self) -> str:
        return "\n".join(f"  - {violation}" for violation in self.violations)


def check_lesson(
    text: str,
    *,
    band: str,
    expect_question: bool = True,
    grounding_terms: Iterable[str] = (),
) -> ContractResult:
    """Whether this is a lesson."""
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
_TTS_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"EC\$\s?([\d,]+(?:\.\d{2})?)"), r"\1 EC dollars"),
    (re.compile(r"XCD\s?([\d,]+(?:\.\d{2})?)"), r"\1 EC dollars"),
    (re.compile(r"\bEC\$"), "EC dollars"),
    (re.compile(r"([\d.]+)\s?%"), r"\1 percent"),
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"\s*/\s*"), " or "),
    # Parentheticals are an aside a reader skims and a listener cannot.
    (re.compile(r"\s*\([^)]*\)"), ""),
    (re.compile(r"\s*--\s*"), ", "),
    (re.compile(r"\s*—\s*"), ", "),
)


def tts_safe(text: str) -> str:
    """The lesson as a voice should read it."""
    out = text
    for pattern, replacement in _TTS_SUBSTITUTIONS:
        out = pattern.sub(replacement, out)
    return re.sub(r"\s{2,}", " ", out).strip()
