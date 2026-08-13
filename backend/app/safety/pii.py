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

#: A FULL date of birth: day, month and year together.
_DOB = re.compile(
    r"""
    \b(?:
        \d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)\d{2}          # 14/03/2015
      | (?:19|20)\d{2}[/.\-]\d{1,2}[/.\-]\d{1,2}          # 2015-03-14
      | \d{1,2}(?:st|nd|rd|th)?\s+
        (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*
        \.?,?\s+(?:19|20)\d{2}                            # 14 March 2015
      | (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*
        \.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}  # March 14, 2015
    )\b
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

#: What `redact` leaves behind, per kind.
_NEUTRAL: Final[dict[str, str]] = {
    "email": "[an email address]",
    "phone": "[a phone number]",
    "national_id": "[an ID number]",
    "account_number": "[an account number]",
    "date_of_birth": "[a date of birth]",
    "street_address": "[an address]",
}


def detect(text: str) -> list[PIISpan]:
    """Every piece of personal data in `text`, in the order it appears."""
    if not text:
        return []

    found: list[tuple[int, int, int, str, str]] = []
    for priority, (kind, pattern, group) in enumerate(_PATTERNS):
        for match in pattern.finditer(text):
            start, end = match.span(group)
            if start < 0 or end <= start:
                continue
            found.append((start, end, priority, kind, match.group(group)))

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


def kinds_in(text: str) -> list[str]:
    """The distinct kinds present, in first-appearance order."""
    seen: list[str] = []
    for span in detect(text):
        if span.kind not in seen:
            seen.append(span.kind)
    return seen


def _rewrite(text: str, replacement: Callable[[PIISpan], str]) -> str:
    """Replace every span back-to-front so earlier offsets stay valid."""
    spans = detect(text)
    if not spans:
        return text
    out = text
    for span in reversed(spans):
        out = out[: span.start] + replacement(span) + out[span.end :]
    return out


def redact(text: str) -> str:
    """`text` with every detected value replaced by a neutral phrase."""
    return _rewrite(text, lambda span: _NEUTRAL.get(span.kind, "[removed]"))


def redact_for_summary(text: str) -> str:
    """`text` with every detected value replaced by `[collected: <field>]`."""
    return _rewrite(text, lambda span: f"[collected: {span.kind}]")


def redact_all(texts: Iterable[str]) -> list[str]:
    """`redact_for_summary` over a sequence, for the persist node's message list."""
    return [redact_for_summary(text) for text in texts]
