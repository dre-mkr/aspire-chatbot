"""Answer comparison. A pure function, deliberately: no model call decides
whether a child got a word right.

Two children typing the same word must always get the same verdict, and the same
child typing it twice must too. That rules out asking a language model, which is
also how you end up handing the answer to something that can be talked into
repeating it.
"""

from __future__ import annotations

import re
import unicodedata

_REPEATED_LETTER = re.compile(r"(.)\1+")


def normalise(text: str) -> str:
    """Fold a typed answer to its comparable form.

    Case, surrounding space, inner punctuation and accents all disappear, so
    `Save`, `save `, `SAVE!` and `save.` are one string. Accents matter for the
    Spanish and French sets: a child who types `interes` for `interés` knows the
    word, and a keyboard without accents is not a wrong answer.
    """
    # NFKD splits an accented letter into base + combining mark, so dropping
    # category Mn removes the accent and keeps the letter.
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in stripped if c.isalnum()).casefold()


def levenshtein(a: str, b: str, *, max_edits: int) -> int:
    """Edit distance, giving up once it exceeds `max_edits`.

    Returns `max_edits + 1` for anything further apart — the caller only ever
    asks "is this within tolerance", so the exact distance beyond the cutoff
    would be wasted work.
    """
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
    """Whether a typed answer counts as the word.

    Three rules, in order of how confident each is.

    1. Exact after normalisation. Always correct.

    2. A held key. A child hunting for letters produces `savve` and `moneyy`
       constantly, and collapsing repeated letters on both sides catches it at
       any word length. This is safe where general edit distance is not:
       un-doubling a letter almost never lands on a different real word.

    3. A single edit, but only on longer words. `interrest` and `interests` are
       plainly the same child reaching for INTEREST. At four letters the same
       tolerance would accept `safe`, `cave`, `gave` and `wave` as SAVE — all
       real words, and accepting them teaches the wrong one. Hence the length
       floor, and hence rule 2 carrying the short words instead.

    `max_edits=0` disables 2 and 3 together, leaving exact matching only.
    """
    typed = normalise(answer)
    target = normalise(word)
    if not typed:
        return False
    if typed == target:
        return True

    # One knob turns all forgiveness off. Held keys are not edit distance, but a
    # setting called "max edits: 0" that still accepted `savve` would be a lie.
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

# Deliberately NOT accepted. On "Inflation means prices fall and money buys
# more", a child who answers "no" almost certainly means "no, that is false" —
# but a child answering "no" to "Should you save?" means the opposite. The word
# does not say which proposition it is answering, and guessing would mark honest
# reasoning wrong. Better to ask again.
_AMBIGUOUS = frozenset({"yes", "y", "yeah", "yep", "yup", "no", "n", "nope", "nah"})


def parse_verdict(answer: str) -> bool | None:
    """`true`/`t`/`false`/`f` in any case, or None if it cannot be read.

    None is not "wrong". The caller leaves the item open and asks again, because
    spending a statement on an answer nobody could interpret teaches nothing.
    """
    value = normalise(answer)
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return None


def looks_like_yes_no(answer: str) -> bool:
    """Whether an unreadable answer was a yes/no, so the reprompt can say so."""
    return normalise(answer) in _AMBIGUOUS
