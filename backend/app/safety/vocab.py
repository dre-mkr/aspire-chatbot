"""What each age band is allowed to be taught, and what it may not be told."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Bands, youngest first.
BANDS: Final[tuple[str, ...]] = ("5-8", "9-12", "13-15", "16-18", "adult")


@dataclass(frozen=True, slots=True)
class VocabViolation:
    """One banned term found in outbound text."""

    term: str
    #: The variant actually matched, which is what a log line should name -- "compounding" is more useful to a promp…
    matched: str
    start: int
    end: int


# ── the general list ───────────────────────────────────────────────────────── Applies at every band including…

_GENERAL_BAN: Final[dict[str, tuple[str, ...]]] = {
    "guaranteed return": ("guaranteed return", "guaranteed returns"),
    "get rich": ("get rich", "get-rich", "getting rich"),
    "risk-free": ("risk-free", "risk free", "riskfree"),
    "crypto": ("crypto", "cryptocurrency", "cryptocurrencies", "bitcoin"),
    "day trading": ("day trading", "day-trade", "day trade"),
    "guaranteed profit": ("guaranteed profit", "guaranteed profits"),
}


# ── the per-band ladders ───────────────────────────────────────────────────── `allow` is what this band ADDS.

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
    # No additions and no restrictions beyond the general list.
    "16-18": (),
    "adult": (),
}

#: Banned terms per band, with every variant written out.
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
    """A whole-word, case-insensitive alternation over one term's variants."""
    ordered = sorted(variants, key=len, reverse=True)
    parts = []
    for variant in ordered:
        escaped = re.escape(variant)
        left = r"\b" if variant[:1].isalnum() else ""
        right = r"\b" if variant[-1:].isalnum() else ""
        parts.append(f"{left}{escaped}{right}")
    return re.compile("|".join(parts), re.IGNORECASE)


#: `band -> term -> pattern`, built once at import.
_PATTERNS: Final[dict[str, dict[str, re.Pattern[str]]]] = {
    band: {
        **{term: _compile(variants) for term, variants in _GENERAL_BAN.items()},
        **{term: _compile(variants) for term, variants in _BAN[band].items()},
    }
    for band in BANDS
}


def concepts_for(band: str) -> frozenset[str]:
    """Every concept this band and every younger band may be taught."""
    if band not in BANDS:
        return frozenset()
    ladder: set[str] = set()
    for step in BANDS:
        ladder.update(_ALLOW.get(step, ()))
        if step == band:
            break
    return frozenset(ladder)


def is_allowed_concept(concept: str, band: str) -> bool:
    """Whether `concept` is on this band's ladder."""
    normalised = concept.replace("_", " ").replace("-", " ").strip().lower()
    if normalised in concepts_for(band):
        return True

    try:
        from app.learning.concepts import get_store

        store = get_store()
    except Exception:  # pragma: no cover - import cycles during partial startup
        return False

    # Both compared case-insensitively. An id is an identifier, not copy, and
    # the two sides of this comparison are written by different authors: the
    # store carries `CON-0019` from the seed, while the widget composer emits
    # whatever case the model wrote. Measured: a composed compound-interest
    # widget was dropped as "not on the 13-15 ladder" because it said
    # `con-0019` -- the gate's failure silently deletes the feature, so a case
    # mismatch must not be able to cause it.
    #
    # This does NOT widen the gate. The concept must still exist in the store
    # and still return `teachable_at(band)`.
    wanted = concept.strip().lower()
    for candidate in store.all():
        if candidate.slug.lower() == wanted or candidate.id.lower() == wanted:
            return candidate.teachable_at(band)
    return False


def banned_terms(band: str) -> frozenset[str]:
    """The term names checked at this band, general list included."""
    return frozenset(_PATTERNS.get(band, _PATTERNS["adult"]).keys())


def check(text: str, band: str) -> list[VocabViolation]:
    """Every banned term in `text` for this band, in the order they appear."""
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
    """A re-prompt instruction naming what to remove and what may replace it."""
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
