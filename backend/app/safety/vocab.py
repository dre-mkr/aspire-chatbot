"""What each age band is allowed to be taught, and what it may not be told.

Two lists per band and they do different jobs. Conflating them is the mistake
this module's shape exists to prevent.

  **The concept ladder** (`allow`) is what a band is *ready for*. It is
  cumulative -- 13-15 inherits everything 9-12 can hold -- and it is consulted
  by the curriculum loader and by widget gate 3, both of which ask "is this
  concept on this child's ladder?". It is emphatically NOT a whitelist of
  permitted English: a six-year-old is allowed to say "elephant".

  **The banned list** (`ban`) is what must not appear in outbound text. It is
  checked on every message by `safety_out` gate (b), and a hit is a violation
  that triggers a re-prompt.

Bans are per-band rather than inherited, because the ladder moves in both
directions. "interest" is banned at 5-8 and *allowed* at 9-12; inheriting the
younger band's bans would make the ladder unclimbable. What is inherited is the
general list -- terms nobody on this product says to anybody.

## Why exact words rather than stems

Stemming is the obvious implementation and it is wrong here, for one concrete
reason: `interest` stems to a prefix of `interesting`, and "that's interesting!"
is a sentence a mascot says to a nine-year-old several times a lesson. Flagging
it would trigger a re-prompt on a perfectly good turn, and re-prompts cost a
model call and a second of latency.

So every term carries its own variants, written out. It is more typing and it
is auditable: somebody asking "will this flag the word 'interesting'?" can
answer by reading, and the test suite pins it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Bands, youngest first. Duplicated from `graph/state.py` rather than imported
#: so that `app.safety` has no dependency on `app.graph` -- the safety layer is
#: consulted from places (the eval harness, the curriculum loader) that have no
#: graph.
BANDS: Final[tuple[str, ...]] = ("5-8", "9-12", "13-15", "16-18", "adult")


@dataclass(frozen=True, slots=True)
class VocabViolation:
    """One banned term found in outbound text."""

    term: str
    #: The variant actually matched, which is what a log line should name --
    #: "compounding" is more useful to a prompt author than "compound".
    matched: str
    start: int
    end: int


# ── the general list ─────────────────────────────────────────────────────────
#
# Applies at every band including adult. These are not concepts that arrive
# later on the ladder; they are things this product does not say. It is a
# government savings programme for minors, not a brokerage.

_GENERAL_BAN: Final[dict[str, tuple[str, ...]]] = {
    "guaranteed return": ("guaranteed return", "guaranteed returns"),
    "get rich": ("get rich", "get-rich", "getting rich"),
    "risk-free": ("risk-free", "risk free", "riskfree"),
    "crypto": ("crypto", "cryptocurrency", "cryptocurrencies", "bitcoin"),
    "day trading": ("day trading", "day-trade", "day trade"),
    "guaranteed profit": ("guaranteed profit", "guaranteed profits"),
}


# ── the per-band ladders ─────────────────────────────────────────────────────
#
# `allow` is what this band ADDS. `concepts_for` accumulates.

_ALLOW: Final[dict[str, tuple[str, ...]]] = {
    "5-8": ("save", "spend", "share", "money", "bank", "coin", "goal", "wait"),
    "9-12": ("interest", "budget", "need", "want", "goal", "deposit", "earn"),
    "13-15": (
        "compound interest",
        "inflation",
        "budget",
        "credit",
        "debit",
        "risk",
    ),
    # No additions and no restrictions beyond the general list. Named explicitly
    # rather than left absent so that `concepts_for("16-18")` is a lookup that
    # succeeds rather than a KeyError somebody has to guard.
    "16-18": (),
    "adult": (),
}

#: Banned terms per band, with every variant written out. See the module
#: docstring for why these are not stems.
_BAN: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "5-8": {
        "interest": ("interest",),
        "compound": ("compound", "compounds", "compounded", "compounding"),
        "investment": ("investment", "investments", "invest", "investing", "investor"),
        "inflation": ("inflation", "inflationary"),
        "dividend": ("dividend", "dividends"),
        "credit": ("credit", "credits"),
        "loan": ("loan", "loans"),
        "percent": ("percent", "percents", "percentage", "percentages", "%"),
        "portfolio": ("portfolio", "portfolios"),
    },
    "9-12": {
        "compound": ("compound", "compounds", "compounded", "compounding"),
        "inflation": ("inflation", "inflationary"),
        "dividend": ("dividend", "dividends"),
        "portfolio": ("portfolio", "portfolios"),
        "credit score": ("credit score", "credit scores", "credit rating"),
        "loan": ("loan", "loans"),
    },
    "13-15": {
        "derivative": ("derivative", "derivatives"),
        "leverage": ("leverage", "leveraged", "leveraging"),
        "amortisation": (
            "amortisation",
            "amortization",
            "amortise",
            "amortize",
            "amortised",
            "amortized",
        ),
    },
    "16-18": {},
    "adult": {},
}


def _compile(variants: tuple[str, ...]) -> re.Pattern[str]:
    """A whole-word, case-insensitive alternation over one term's variants.

    Longest first, so "credit score" is preferred over "credit" when both are in
    play at the same band and the longer one is the more specific finding.

    `%` gets no `\\b` on its left, because a word boundary before a non-word
    character never matches -- `\\b%\\b` matches nothing at all, which is
    exactly the kind of silent no-op a banned-term list must not contain.
    """
    ordered = sorted(variants, key=len, reverse=True)
    parts = []
    for variant in ordered:
        escaped = re.escape(variant)
        left = r"\b" if variant[:1].isalnum() else ""
        right = r"\b" if variant[-1:].isalnum() else ""
        parts.append(f"{left}{escaped}{right}")
    return re.compile("|".join(parts), re.IGNORECASE)


#: `band -> term -> pattern`, built once at import. The general list is folded
#: into every band here rather than checked separately, so a caller cannot
#: consult the band list and forget the general one.
_PATTERNS: Final[dict[str, dict[str, re.Pattern[str]]]] = {
    band: {
        **{term: _compile(variants) for term, variants in _GENERAL_BAN.items()},
        **{term: _compile(variants) for term, variants in _BAN[band].items()},
    }
    for band in BANDS
}


def concepts_for(band: str) -> frozenset[str]:
    """Every concept this band and every younger band may be taught.

    Cumulative, so a fourteen-year-old can still be told about saving. An
    unknown band returns the empty set, which reads as "nothing is on this
    child's ladder" -- the safe answer, and the one that makes gate 3 refuse
    rather than pass.
    """
    if band not in BANDS:
        return frozenset()
    ladder: set[str] = set()
    for step in BANDS:
        ladder.update(_ALLOW.get(step, ()))
        if step == band:
            break
    return frozenset(ladder)


def is_allowed_concept(concept: str, band: str) -> bool:
    """Whether `concept` is on this band's ladder.

    Matching is on the normalised concept name -- underscores and hyphens read
    as spaces -- because curriculum ids are `compound_interest` and the ladder
    is written in prose.
    """
    normalised = concept.replace("_", " ").replace("-", " ").strip().lower()
    return normalised in concepts_for(band)


def banned_terms(band: str) -> frozenset[str]:
    """The term names checked at this band, general list included.

    An unknown band gets the general list only. That is the permissive choice
    and it is deliberate: an unknown band is a bug in identity, and it is
    `access.allowed_agents` that refuses the turn outright. Refusing here as
    well would mean two different subsystems reporting the same fault, and the
    one with the clearer message would be drowned out.
    """
    return frozenset(_PATTERNS.get(band, _PATTERNS["adult"]).keys())


def check(text: str, band: str) -> list[VocabViolation]:
    """Every banned term in `text` for this band, in the order they appear.

    Case-insensitive and whole-word. Multiple variants of the same term report
    as separate violations -- "compound interest compounds" is two findings --
    because a re-prompt should tell the model how many places to fix.
    """
    if not text:
        return []

    patterns = _PATTERNS.get(band, _PATTERNS["adult"])
    violations: list[VocabViolation] = []
    for term, pattern in patterns.items():
        for match in pattern.finditer(text):
            violations.append(
                VocabViolation(
                    term=term,
                    matched=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    violations.sort(key=lambda violation: violation.start)
    return violations


def is_clean(text: str, band: str) -> bool:
    """Whether outbound text passes this band's vocabulary gate."""
    return not check(text, band)


def explain(violations: list[VocabViolation], band: str) -> str:
    """A re-prompt instruction naming what to remove and what may replace it.

    Written for the model rather than for a log, and specific on purpose:
    "avoid complex words" produces a paraphrase that is still wrong, whereas
    naming the term and the band's ladder produces a rewrite that lands.
    """
    if not violations:
        return ""
    terms = sorted({violation.term for violation in violations})
    ladder = sorted(concepts_for(band))
    return (
        f"Your answer used {', '.join(repr(term) for term in terms)}, which a "
        f"learner in the {band} band has not met yet. Rewrite it without those "
        f"words. You may use these ideas: {', '.join(ladder) or 'plain language only'}. "
        "Explain the idea itself in words they already have -- do not simply "
        "delete the sentence."
    )
