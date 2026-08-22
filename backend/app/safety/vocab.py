"""What each age band is allowed to be taught, and what it may not be told."""

from __future__ import annotations

import re
import unicodedata
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
        "interest": (
            "interest", "interests",
            "interés", "intereses", "intérêt", "intérêts",
        ),
        "compound": (
            "compound", "compounds", "compounded", "compounding",
            "compuesto", "compuestos", "capitalización", "capitalizado",
            "composé", "composés", "capitalisation", "capitalisé",
        ),
        "investment": (
            "investment", "investments", "invest", "invests", "invested",
            "investing", "investor", "investors",
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
        # `credited` matters more than it looks: the programme's own published
        # phrasing is "2%, credited twice a year", so an answer echoing the
        # source leaks the term at a band that may not hear it.
        "credit": (
            "credit", "credits", "credited", "crediting",
            "crédito", "créditos", "crédit", "crédits",
        ),
        "loan": (
            "loan", "loans", "loaned", "loaning",
            "préstamo", "préstamos",
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
            "loan", "loans", "loaned", "loaning",
            "préstamo", "préstamos",
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


def strip_accents(text: str) -> str:
    """`interés` and `interes` are the same word to this gate.

    ACCENTS ARE OPTIONAL IN PRACTICE AND THE GATE CANNOT BE. A model writing
    quickly drops them, a phone keyboard without a Spanish layout drops them, a
    voice transcript drops them, and a reader typing fast drops them. Before
    this, every one of those cases walked a banned word past a five-year-old:

        "un interés cada año"  -> caught
        "un interes cada ano"  -> CLEAN, and the child reads it

    Decomposes and discards the combining marks, so the fold is one rule rather
    than a table of pairs -- it covers French circumflexes and cedillas, Spanish
    tildes and diaereses, and anything a fourth language brings, without being
    told about them. `ñ` folds to `n`, which is right HERE: this gate compares
    against a fixed list of banned forms, and no pair on it is told apart by
    that mark alone.
    """
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(ch)
    )


def _compile(variants: tuple[str, ...]) -> re.Pattern[str]:
    """A whole-word, case-insensitive alternation over one term's variants.

    Compiled over the ACCENT-FOLDED forms, and `check` folds the text it scans
    the same way, so the two always meet. Folding one side only is worse than
    folding neither: it looks like coverage and silently has none.
    """
    ordered = sorted({strip_accents(v) for v in variants}, key=len, reverse=True)
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


#: The terms the band ladder holds back that ASPIRE'S OWN FACTS require.
#:
#: A child in this programme owns EC$500 of investment. Telling them what that
#: is is not financial education, it is telling them what they have -- and the
#: ladder was refusing it, so Skye could not say what half of a five-year-old's
#: own money does, and could not spell out the programme's name either, because
#: "Achieving Success through Personal INVESTMENT..." trips the same gate.
#:
#: These lift ONLY for an answer grounded in the Golden Record. Ungrounded
#: financial-education prose still meets the full ladder, which is what the
#: ladder was written for: a five-year-old does not need compound interest
#: explained, and does need to know the money is theirs.
PROGRAMME_TERMS: Final[frozenset[str]] = frozenset(
    {"interest", "investment", "credit", "dividend", "portfolio", "compound"}
)


def check(
    text: str,
    band: str,
    *,
    programme_scope: bool = False,
) -> list[VocabViolation]:
    """Every banned term in `text` for this band, in the order they appear.

    `programme_scope` says this answer is grounded in the Golden Record -- the
    sourced ASPIRE facts -- and lifts `PROGRAMME_TERMS` for it.

    WHAT IT NEVER LIFTS, and the distinction is the whole of the rule:

      * `_GENERAL_BAN` -- guaranteed return, get rich, risk-free, crypto, day
        trading, guaranteed profit. Not an age gate. A position the programme
        takes, at every band including adult, in every context. A scam sentence
        does not become safe because it is about ASPIRE; it becomes worse.
      * The per-card figure rules. Skye may now say her money is invested and
        still may not say 2%, because "never a rate, a percentage, a balance or
        a projection, not even a sourced one" lives in her card, not here. The
        WORDS and the NUMBERS were always separate rules and they stay separate.
    """
    if not text:
        return []

    patterns = _PATTERNS.get(band, _PATTERNS["adult"])
    if programme_scope:
        patterns = {
            term: pattern
            for term, pattern in patterns.items()
            # `_GENERAL_BAN` keys are never in PROGRAMME_TERMS, so this cannot
            # reach them. Stated as a filter over the band's own terms rather
            # than a lookup, so adding a scam phrase to the general list can
            # never accidentally make it liftable.
            if term not in PROGRAMME_TERMS or term in _GENERAL_BAN
        }
    # Scanned folded, REPORTED against the original. `strip_accents` removes
    # combining marks without changing how many characters precede any given
    # letter, so the offsets a caller uses to blank a word still land on it --
    # and `matched` shows what the reader actually wrote, accents and all.
    folded = strip_accents(text)
    violations: list[VocabViolation] = []
    for term, pattern in patterns.items():
        for match in pattern.finditer(folded):
            violations.append(
                VocabViolation(
                    term=term,
                    matched=text[match.start() : match.end()],
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
