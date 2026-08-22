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
    #: The variant actually matched, which is what a log line or a re-prompt should name.
    matched: str
    start: int
    end: int


# ── the general list ──
# Applies at every band, adult included.

_GENERAL_BAN: Final[dict[str, tuple[str, ...]]] = {
    "guaranteed return": (
        "guaranteed return", "guaranteed returns",
        # es
        "rendimiento garantizado", "rendimientos garantizados",
        "retorno garantizado", "retornos garantizados",
        # fr
        "rendement garanti", "rendements garantis",
        "retour garanti", "retours garantis",
    ),
    "get rich": (
        "get rich", "get-rich", "getting rich",
        # es
        "hacerse rico", "volverse rico", "hacerte rico",
        # fr
        "devenir riche", "s'enrichir", "senrichir",
    ),
    "risk-free": (
        "risk-free", "risk free", "riskfree",
        # es
        "sin riesgo", "libre de riesgo", "sin ningún riesgo",
        # fr
        "sans risque", "sans aucun risque",
    ),
    "crypto": (
        "crypto", "cryptocurrency", "cryptocurrencies", "bitcoin",
        # es
        "cripto", "criptomoneda", "criptomonedas",
        # fr
        "cryptomonnaie", "cryptomonnaies", "crypto-monnaie", "crypto-monnaies",
    ),
    "day trading": (
        "day trading", "day-trade", "day trade",
        # es
        "trading intradiario", "operar intradía",
        # fr
        "trading intrajournalier", "day-trading",
    ),
    "guaranteed profit": (
        "guaranteed profit", "guaranteed profits",
        # es
        "ganancia garantizada", "ganancias garantizadas",
        "beneficio garantizado", "beneficios garantizados",
        # fr
        "profit garanti", "profits garantis",
        "bénéfice garanti", "bénéfices garantis",
    ),
}


# ── the per-band ladders ──
# `_ALLOW` is what a band adds to everything the younger bands already allow.

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

#: Banned terms per band, with every variant written out -- IN ALL THREE LOCALES.
#:
#: The key stays English because it is an identifier: it is what `explain()` puts
#: in a reprompt, what the tests assert on, and what the persona cards list. Only
#: the VARIANTS are multilingual.
#:
#: Why they have to be. `check()` runs on the finished reply in `safety_out`,
#: whatever language it is in, and these patterns are what it matches against.
#: With English variants alone the gate was a no-op the moment the model answered
#: in Spanish or French -- "un interés cada año" and "un intérêt chaque année"
#: both reached a five-year-old untouched, while the English sentence saying the
#: same thing was stripped. The word caps were never affected; they count words
#: in any language. The ladder was.
#:
#: Adding a language means adding variants here, and nowhere else.
_BAN: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "5-8": {
        "interest": ("interest", "interés", "intereses", "intérêt", "intérêts"),
        "compound": (
            "compound", "compounds", "compounded", "compounding",
            "compuesto", "compuestos", "capitalización", "capitalizado",
            "composé", "composés", "capitalisation", "capitalisé",
        ),
        "investment": (
            "investment", "investments", "invest", "investing", "investor",
            "inversión", "inversiones", "invertir", "invierte", "invertido",
            "inversionista",
            "investissement", "investissements", "investir", "investit",
            "investi", "investisseur",
        ),
        "inflation": (
            "inflation", "inflationary", "inflación", "inflacionario",
            "inflationniste",
        ),
        "dividend": (
            "dividend", "dividends", "dividendo", "dividendos",
            "dividende", "dividendes",
        ),
        "credit": ("credit", "credits", "crédito", "créditos", "crédit", "crédits"),
        "loan": (
            "loan", "loans", "préstamo", "préstamos",
            "prêt", "prêts", "emprunt", "emprunts",
        ),
        "percent": (
            "percent", "percents", "percentage", "percentages", "%",
            "por ciento", "porcentaje", "porcentajes",
            "pour cent", "pourcent", "pourcentage", "pourcentages",
        ),
        "portfolio": (
            "portfolio", "portfolios", "portafolio", "portafolios",
            "portefeuille", "portefeuilles",
        ),
    },
    "9-12": {
        "compound": (
            "compound", "compounds", "compounded", "compounding",
            "compuesto", "compuestos", "capitalización", "capitalizado",
            "composé", "composés", "capitalisation", "capitalisé",
        ),
        "inflation": (
            "inflation", "inflationary", "inflación", "inflacionario",
            "inflationniste",
        ),
        "dividend": (
            "dividend", "dividends", "dividendo", "dividendos",
            "dividende", "dividendes",
        ),
        "portfolio": (
            "portfolio", "portfolios", "portafolio", "portafolios",
            "portefeuille", "portefeuilles",
        ),
        "credit score": (
            "credit score", "credit scores", "credit rating",
            "puntaje de crédito", "calificación crediticia", "historial crediticio",
            "cote de crédit", "score de crédit",
        ),
        "loan": (
            "loan", "loans", "préstamo", "préstamos",
            "prêt", "prêts", "emprunt", "emprunts",
        ),
    },
    "13-15": {
        "derivative": (
            "derivative", "derivatives", "derivado", "derivados",
            "dérivé", "dérivés",
        ),
        "leverage": (
            "leverage", "leveraged", "leveraging",
            "apalancamiento", "apalancado", "apalancar",
            "effet de levier", "effets de levier",
        ),
        "amortisation": (
            "amortisation", "amortization", "amortise", "amortize",
            "amortised", "amortized",
            "amortización", "amortizar", "amortizado",
            "amortissement", "amortir", "amorti",
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


def _flatten_id(value: str) -> str:
    """A concept id, slug or ladder entry with case and separator spelling removed.

    The store seeds ids as `CON-0064` and slugs as `compound_interest`, while a
    composer writes back whichever separator it feels like. Neither spelling is
    canonical, so every comparison in this module flattens both sides instead.
    """
    return value.replace("_", " ").replace("-", " ").strip().lower()


def is_allowed_concept(concept: str, band: str) -> bool:
    """Whether `concept` is on this band's ladder."""
    wanted = _flatten_id(concept)
    if wanted in concepts_for(band):
        return True

    try:
        from app.learning.concepts import get_store

        store = get_store()
    except Exception:  # pragma: no cover - import cycles during partial startup
        return False

    # Flattened on both sides: a case fold alone left `con_0064` unequal to `CON-0064`
    # and dropped a composed widget. The gate itself still requires `teachable_at(band)`.
    for candidate in store.all():
        if _flatten_id(candidate.slug) == wanted or _flatten_id(candidate.id) == wanted:
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
