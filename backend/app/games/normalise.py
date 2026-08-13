"""Answer comparison."""

from __future__ import annotations

import re
import unicodedata

_REPEATED_LETTER = re.compile(r"(.)\1+")


def normalise(text: str) -> str:
    """Fold a typed answer to its comparable form."""
    # NFKD splits an accented letter into base + mark, so dropping the marks keeps the letter.
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in stripped if c.isalnum()).casefold()


def levenshtein(a: str, b: str, *, max_edits: int) -> int:
    """Edit distance, giving up once it exceeds `max_edits`."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_edits:
        return max_edits + 1

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ca != cb),  # substitution
                )
            )
        # Whole row already past tolerance: no later row can come back under it.
        if min(current) > max_edits:
            return max_edits + 1
        previous = current

    return previous[-1]


def _collapse_repeats(text: str) -> str:
    """`savve` -> `save`, `moneyy` -> `money`. Runs of one letter become one."""
    return _REPEATED_LETTER.sub(r"\1", text)


def answer_matches(
    answer: str,
    word: str,
    *,
    typo_tolerance_min_length: int,
    max_edits: int,
) -> bool:
    """Whether a typed answer counts as the word."""
    typed = normalise(answer)
    target = normalise(word)
    if not typed:
        return False
    if typed == target:
        return True

    # One knob turns all forgiveness off.
    if max_edits <= 0:
        return False

    if _collapse_repeats(typed) == _collapse_repeats(target):
        return True
    if len(target) < typo_tolerance_min_length:
        return False
    return levenshtein(typed, target, max_edits=max_edits) <= max_edits


def letters_of(text: str) -> list[str]:
    """Sorted comparable letters — the anagram check for seed validation."""
    return sorted(normalise(text))


# --- True/false ------------------------------------------------------------

_TRUE = frozenset({"true", "t"})
_FALSE = frozenset({"false", "f"})

# Deliberately NOT accepted.
_AMBIGUOUS = frozenset({"yes", "y", "yeah", "yep", "yup", "no", "n", "nope", "nah"})


def parse_verdict(answer: str) -> bool | None:
    """`true`/`t`/`false`/`f` in any case, or None if it cannot be read."""
    value = normalise(answer)
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return None


def looks_like_yes_no(answer: str) -> bool:
    """Whether an unreadable answer was a yes/no, so the reprompt can say so."""
    return normalise(answer) in _AMBIGUOUS
