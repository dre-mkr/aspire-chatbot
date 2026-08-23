"""Finding and removing personal data, deterministically."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

#: The field names this module can name.
PIIKind = str

@dataclass(frozen=True, slots=True)
class PIISpan:
    """One match: what it is, where it is, and what was there."""

    kind: PIIKind
    start: int
    end: int
    text: str


# ── the patterns ──

#: RFC-shaped enough.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

#: Phone numbers, with the local form first.
_PHONE = re.compile(
    r"""
    (?<![\w-])
    (?:
        \+?1[\s.\-]?\(?869\)?[\s.\-]?\d{3}[\s.\-]?\d{4}   # +1 869 555 0123
      | \(?869\)?[\s.\-]\d{3}[\s.\-]?\d{4}                # (869) 555-0123
      | \+\d{1,3}[\s.\-]?\d{2,4}[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}
      | \b\d{3}[\s.\-]\d{4}\b                             # 555-0123, local 7-digit
    )
    (?![\w-])
    """,
    re.VERBOSE,
)

#: National ID.
_NATIONAL_ID = re.compile(
    r"""
    # NB: `#` must be escaped inside a VERBOSE pattern -- unescaped it starts a
    # comment and silently swallows the rest of the line.
    \b(?:national\s*id|nat(?:ional)?\.?\s*i\.?d\.?|id\s*(?:no\.?|number|\#)
       |nis|social\s*security|ssn)\b
    \s*(?:is|:|=|-)?\s*
    # Three digits minimum, because a US-style SSN starts "123-45-...". The
    # label is what makes this safe to be this loose -- an unlabelled "123" is
    # never matched here.
    ([A-Z]{0,3}[\s\-]?\d{3,12}(?:[\s\-]?\d{1,6})*)
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: A bare ID-shaped run, for when the label came a sentence earlier.
_ID_LIKE = re.compile(r"\b[A-Z]{0,2}\d{8,12}\b")

#: Bank and account numbers, again context-anchored for the same reason.
_ACCOUNT = re.compile(
    r"""
    \b(?:account|acct\.?|a/c|iban|sort\s*code|routing|card)\s*
      (?:no\.?|number|\#)?\b
    \s*(?:is|:|=|-)?\s*
    ([A-Z]{0,4}[\s\-]?\d[\d\s\-]{5,30}\d)
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: The cues that make a date somebody's date of birth rather than a date.
_BIRTH_CUE = r"""(?:born|birth\s*day|birthdate|date\s+of\s+birth|d\.?o\.?b\.?|b\.)"""

#: A FULL date, day/month/year together, in any of the four shapes below.
#:
#: On its own this is NOT personal data, and treating it as such was not a
#: harmless over-reach -- the same mistake `_aspire_own` exists to undo for the
#: programme's own phone number. ASPIRE's founding date, the date the ASPIRE
#: Bill passed the National Assembly, and 57 other published dates all live in
#: the corpus, and every one of them was being rewritten to "[a date of birth]"
#: on its way to the reader. The history of a government programme came out as:
#:
#:   "announced ... at the Independence 41 National Youth Rally on
#:    [a date of birth]. The ASPIRE Bill, 2024 ... passed in the National
#:    Assembly on [a date of birth]."
#:
#: So the bare pattern is kept for summaries and tickets, where over-redaction
#: costs nothing and under-redaction is the expensive mistake, and the OUTBOUND
#: gate uses `_DOB_ANCHORED` instead -- which still catches "born on 14 March
#: 2015" and leaves "passed on 28 November 2024" alone. `_NATIONAL_ID` and
#: `_ACCOUNT` in this file are anchored for exactly this reason; the date
#: pattern was the one that never was.
#: The four shapes a full date is written in. Shared by both patterns below.
_DATE_BODY = r"""
    (?:
        \d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)\d{2}          # 14/03/2015
      | (?:19|20)\d{2}[/.\-]\d{1,2}[/.\-]\d{1,2}          # 2015-03-14
      | \d{1,2}(?:st|nd|rd|th)?\s+
        (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*
        \.?,?\s+(?:19|20)\d{2}                            # 14 March 2015
      | (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*
        \.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}  # March 14, 2015
    )
"""

#: Any full date, with no cue that it belongs to a person.
_DOB = re.compile(rf"\b{_DATE_BODY}\b", re.VERBOSE | re.IGNORECASE)

#: A date carrying a cue that makes it somebody's. What the outbound gate uses.
#:
#: The cue is matched but NOT replaced -- only group 1, the date itself, is.
#: "The child was born on [a date of birth]" reads as a sentence with something
#: withheld; swallowing the cue gives "The child was [a date of birth]", which
#: reads as a bug. The placeholder already names what was removed, so keeping
#: the cue costs no privacy and buys back the grammar.
_DOB_ANCHORED = re.compile(
    rf"""
    \b{_BIRTH_CUE}
    (?:\s+(?:on|is|was|:))?          # "born on", "date of birth is", "DOB:"
    [\s:,\-]{{0,4}}
    ({_DATE_BODY})
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: A street address: a house number followed by a street word.
_ADDRESS = re.compile(
    r"""
    \b\d{1,5}[A-Za-z]?\s+
    (?:[A-Za-z'\-]+\s+){0,3}
    (?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?
      |boulevard|blvd\.?|court|ct\.?|close|crescent|terrace|way|alley|gap|path)
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: `(kind, pattern, group)`; order decides which pattern wins an overlap in `detect`.
_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], int], ...]] = (
    ("email", _EMAIL, 0),
    ("national_id", _NATIONAL_ID, 1),
    ("account_number", _ACCOUNT, 1),
    ("date_of_birth", _DOB, 0),
    ("phone", _PHONE, 0),
    ("street_address", _ADDRESS, 0),
    ("national_id", _ID_LIKE, 0),
)

#: The same table, with the date pattern swapped for the anchored one.
#:
#: The split is by DIRECTION, because the two directions have opposite costs.
#: Into a ticket or a summary, over-redacting a date costs a reader nothing and
#: under-redacting one writes a child's birthday into a record that outlives the
#: conversation -- so that path keeps the bare pattern. Out to the reader, over-
#: redacting rewrites the programme's own published history into nonsense, while
#: a genuine date of birth can only reach the outbound text by being echoed, and
#: an echo carries the cue that `_DOB_ANCHORED` needs.
_PATTERNS_OUTBOUND: Final[tuple[tuple[str, re.Pattern[str], int], ...]] = tuple(
    ("date_of_birth", _DOB_ANCHORED, 1) if kind == "date_of_birth" else entry
    for entry in _PATTERNS
    for kind in (entry[0],)
)

#: What `redact` leaves behind, per kind.
_NEUTRAL: Final[dict[str, str]] = {
    "email": "[an email address]",
    "phone": "[a phone number]",
    "national_id": "[an ID number]",
    "account_number": "[an account number]",
    "date_of_birth": "[a date of birth]",
    "street_address": "[an address]",
}


def _digits_and_letters(value: str) -> str:
    """A shape two spellings of the same number or address can be compared on."""
    return "".join(character for character in value.lower() if character.isalnum())


def _aspire_own() -> frozenset[str]:
    """ASPIRE's own published contact details, normalised.

    These are not somebody's personal data, and treating them as such is not a
    harmless over-reach: `_PHONE` matches `+1 (869) 667-5566` exactly and
    `_EMAIL` matches `aspire@gov.kn`, so the moment a decline offers the
    programme's own number the outbound gate rewrites it to
    `[a phone number]` -- turning "here is who can help" into a dead end, and
    doing it silently.

    Exempted in `detect` rather than in `redact`, so `kinds_in` and
    `redact_for_summary` inherit it too. A ticket summary recording that a
    reader was given the office number should say so.
    """
    from app.config import get_settings

    settings = get_settings()
    return frozenset(
        _digits_and_letters(value)
        for value in (
            settings.aspire_contact_email,
            settings.aspire_contact_phone,
            settings.aspire_contact_phone_alt,
            settings.aspire_contact_website,
            settings.aspire_contact_office,
        )
        if value
    )


def detect(text: str, *, outbound: bool = False) -> list[PIISpan]:
    """Every piece of personal data in `text`, in the order it appears.

    `outbound=True` requires a birth cue before a date counts as a date of
    birth. See `_PATTERNS_OUTBOUND` for why the direction changes the answer.
    """
    if not text:
        return []

    ours = _aspire_own()

    table = _PATTERNS_OUTBOUND if outbound else _PATTERNS
    found: list[tuple[int, int, int, str, str]] = []
    for priority, (kind, pattern, group) in enumerate(table):
        for match in pattern.finditer(text):
            start, end = match.span(group)
            if start < 0 or end <= start:
                continue
            value = match.group(group)
            if _digits_and_letters(value) in ours:
                continue
            found.append((start, end, priority, kind, value))

    # Earliest position wins; on a tie, the earlier pattern; on a tie, the longer span.
    found.sort(key=lambda item: (item[0], item[2], -(item[1] - item[0])))

    spans: list[PIISpan] = []
    consumed_to = -1
    for start, end, _priority, kind, value in found:
        if start < consumed_to:
            continue
        spans.append(PIISpan(kind=kind, start=start, end=end, text=value))
        consumed_to = end
    return spans


def kinds_in(text: str, *, outbound: bool = False) -> list[str]:
    """The distinct kinds present, in first-appearance order."""
    seen: list[str] = []
    for span in detect(text, outbound=outbound):
        if span.kind not in seen:
            seen.append(span.kind)
    return seen


def _rewrite(
    text: str, replacement: Callable[[PIISpan], str], *, outbound: bool = False
) -> str:
    """Replace every span back-to-front so earlier offsets stay valid."""
    spans = detect(text, outbound=outbound)
    if not spans:
        return text
    out = text
    for span in reversed(spans):
        out = out[: span.start] + replacement(span) + out[span.end :]
    return out


def redact(text: str, *, outbound: bool = False) -> str:
    """`text` with every detected value replaced by a neutral phrase."""
    return _rewrite(
        text, lambda span: _NEUTRAL.get(span.kind, "[removed]"), outbound=outbound
    )


def redact_for_summary(text: str) -> str:
    """`text` with every detected value replaced by `[collected: <field>]`."""
    return _rewrite(text, lambda span: f"[collected: {span.kind}]")


def redact_all(texts: Iterable[str]) -> list[str]:
    """`redact_for_summary` over a sequence, for the persist node's message list."""
    return [redact_for_summary(text) for text in texts]
