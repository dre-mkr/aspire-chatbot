"""Turn an agent reply into something worth listening to."""

from __future__ import annotations

import re

from num2words import num2words

from app.voice.registry import Language

# Order matters throughout this module; each step assumes the previous ran.

_CODE_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]{4,}\|?\s*$", re.M)

# Source markers the agent might emit: [ASP-001], [kb-012], [web-about-1], [3], [^2].
_CITATION = re.compile(r"\[\^?(?:[A-Za-z][\w-]*-)?\d[\w-]*\]")
_PAREN_SOURCE = re.compile(r"\((?:source|src|ref|fuente|source\s*:)\s*:?[^)]*\)", re.I)

_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EXPLICIT_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_BARE_DOMAIN = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:kn|com|org|net|gov|edu|io|co|uk)\b(?:/\S*)?",
    re.I,
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# A connector left stranded by a removed URL or address ("apply online at .").
_DANGLING_CONNECTOR = re.compile(
    # Anchored to the text immediately before a removed link, so stripping a conjunction here cannot touch one in t…
    r"\b(?:"
    r"at|on|via|from|email|e-?mail|visit|or|and"  # en
    r"|en|por|desde|correo|visita|o|y"  # es
    r"|à|sur|depuis|courriel|visitez|ou|et"  # fr
    r")\s*[:,]?\s*$",
    re.I,
)

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.M)
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.M)
_HORIZONTAL_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$", re.M)
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1", re.S)

_MONTHS = {
    Language.EN: "January February March April May June July August September October November December".split(),
    Language.ES: "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
    Language.FR: "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
}
_MONTH_INDEX = {
    lang: {name.lower(): i + 1 for i, name in enumerate(names)}
    for lang, names in _MONTHS.items()
}
# English month names appear in the knowledge base regardless of reply language.
_MONTH_INDEX[Language.ES].update(_MONTH_INDEX[Language.EN])
_MONTH_INDEX[Language.FR].update(_MONTH_INDEX[Language.EN])

_WORDS = {
    Language.EN: {
        "dollars": "dollars",
        "ec_dollars": "Eastern Caribbean dollars",
        "cents": "cents",
        "and": "and",
        "to": "to",
        "percent": "percent",
        "point": "point",
        "of": "of",
        "date": "{day} {month} {year}",
    },
    Language.ES: {
        "dollars": "dólares",
        "ec_dollars": "dólares del Caribe Oriental",
        "cents": "centavos",
        "and": "con",
        "to": "a",
        "percent": "por ciento",
        "point": "coma",
        "of": "de",
        "date": "{day} de {month} de {year}",
    },
    Language.FR: {
        "dollars": "dollars",
        "ec_dollars": "dollars des Caraïbes orientales",
        "cents": "centimes",
        "and": "et",
        "to": "à",
        "percent": "pour cent",
        "point": "virgule",
        "of": "de",
        "date": "{day} {month} {year}",
    },
}


def _say_number(value: int, language: Language) -> str:
    return num2words(value, lang=language.value)


def _say_day(day: int, language: Language) -> str:
    """French says 'premier' for the 1st; English and Spanish use the cardinal."""
    if language is Language.FR and day == 1:
        return "premier"
    return _say_number(day, language)


def _strip_structure(text: str) -> str:
    """Remove everything that only means something on a screen."""
    text = _CODE_FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _TABLE_RULE.sub(" ", text)
    text = _TABLE_ROW.sub(" ", text)
    text = _PAREN_SOURCE.sub(" ", text)
    text = _CITATION.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)  # keep the label, drop the target
    text = _HORIZONTAL_RULE.sub(" ", text)
    text = _HEADING.sub("", text)
    text = _BLOCKQUOTE.sub("", text)
    text = _BULLET.sub("", text)
    text = _EMPHASIS.sub(r"\2", text)
    return text


def _strip_links(text: str) -> str:
    """Drop URLs and emails, and any connector they leave stranded."""
    # Longest-first so an explicit URL is consumed before the bare-domain rule can bite a fragment of it.
    for pattern in (_EXPLICIT_URL, _EMAIL, _BARE_DOMAIN):
        out: list[str] = []
        last = 0
        for match in pattern.finditer(text):
            head = text[last : match.start()]
            # "Apply online at https://..." must not become "Apply online at." Applied repeatedly so "or email info@..." lo…
            trimmed = head.rstrip()
            while True:
                shorter = _DANGLING_CONNECTOR.sub("", trimmed).rstrip()
                if shorter == trimmed:
                    break
                trimmed = shorter
            out.append(trimmed if head.strip() else head)
            last = match.end()
        out.append(text[last:])
        text = "".join(out)
    return text


def _normalise_numbers(text: str, language: Language) -> str:
    words = _WORDS[language]

    def iso_date(match: re.Match[str]) -> str:
        year, month, day = (int(g) for g in match.groups())
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return match.group(0)
        return words["date"].format(
            day=_say_day(day, language),
            month=_MONTHS[language][month - 1],
            year=_say_number(year, language),
        )

    def worded_date(match: re.Match[str]) -> str:
        day = int(match.group("day"))
        month_name = match.group("month").lower()
        year = int(match.group("year"))
        index = _MONTH_INDEX[language].get(month_name)
        if index is None or not 1 <= day <= 31:
            return match.group(0)
        return words["date"].format(
            day=_say_day(day, language),
            month=_MONTHS[language][index - 1],
            year=_say_number(year, language),
        )

    def money(match: re.Match[str]) -> str:
        eastern = bool(match.group("ec"))
        whole = int(match.group("whole").replace(",", "").replace(" ", ""))
        cents = match.group("cents")
        unit = words["ec_dollars"] if eastern else words["dollars"]
        spoken = f"{_say_number(whole, language)} {unit}"
        if cents and int(cents):
            spoken += f" {words['and']} {_say_number(int(cents), language)} {words['cents']}"
        return spoken

    def numeric_range(match: re.Match[str]) -> str:
        low, high = int(match.group(1)), int(match.group(2))
        return f"{_say_number(low, language)} {words['to']} {_say_number(high, language)}"

    def percent(match: re.Match[str]) -> str:
        return f"{_decimal(match.group(1), language)} {words['percent']}"

    def plain(match: re.Match[str]) -> str:
        return _decimal(match.group(0), language)

    # Dates first: an ISO date contains hyphens that the range rule would otherwise read as "two thousand twenty-fo…
    text = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", iso_date, text)
    text = re.sub(
        r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?:de\s+)?(?P<month>[A-Za-zéûàî]+)\.?,?\s+"
        r"(?:de\s+)?(?P<year>\d{4})\b",
        worded_date,
        text,
    )
    text = re.sub(
        r"\b(?P<month>[A-Za-zéûàî]+)\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\b",
        worded_date,
        text,
    )

    # Currency before bare numbers, so the symbol is not orphaned.
    text = re.sub(
        r"(?P<ec>EC)?\$\s?(?P<whole>\d{1,3}(?:[,\s]\d{3})*|\d+)(?:\.(?P<cents>\d{2}))?",
        money,
        text,
    )
    # Ranges: en dash, em dash, or hyphen between two integers.
    text = re.sub(r"\b(\d{1,4})\s*[-–—]\s*(\d{1,4})\b", numeric_range, text)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", percent, text)
    text = re.sub(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b", plain, text)
    return text


def _decimal(raw: str, language: Language) -> str:
    """'1,000.5' -> 'one thousand point five'."""
    cleaned = raw.replace(",", "")
    if "." in cleaned:
        whole, _, fraction = cleaned.partition(".")
        spoken = _say_number(int(whole or 0), language)
        digits = " ".join(_say_number(int(d), language) for d in fraction)
        return f"{spoken} {_WORDS[language]['point']} {digits}"
    return _say_number(int(cleaned), language)


def _tidy(text: str) -> str:
    """Collapse the whitespace and punctuation the stripping left behind."""
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])\1+", r"\1", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"(?:\s*[,;:]\s*)+\.", ".", text)
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]*\n[ \t]*", ". ", text)
    text = re.sub(r"(\.\s*){2,}", ". ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" .,;:\n\t")


def _truncate(text: str, limit: int) -> str:
    """Cut at a sentence boundary, and never mid-word."""
    if len(text) <= limit:
        return text

    window = text[:limit]
    boundary = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    # Only honour a boundary that keeps most of the budget; otherwise a reply whose first sentence is short would b…
    if boundary >= limit * 0.6:
        return window[: boundary + 1].strip()

    space = window.rfind(" ")
    return (window[:space] if space > 0 else window).strip(" ,;:") + "."


def speakable(text: str, language: Language | str, *, max_chars: int = 1500) -> str:
    """Prepare agent output for text-to-speech."""
    if not text or not text.strip():
        return ""

    language = Language(language)
    result = _strip_structure(text)
    result = _strip_links(result)
    result = _normalise_numbers(result, language)
    result = _tidy(result)
    return _truncate(result, max_chars)


def has_many_numbers(text: str, threshold: int = 3) -> bool:
    """Whether text is figure-heavy enough to deserve the higher-quality model."""
    return len(re.findall(r"\d", text)) >= threshold
