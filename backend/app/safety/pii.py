"""Finding and removing personal data, deterministically.

No model call. Not "no model call for now" -- no model call, ever, by design.
Three reasons, in order of how much they cost when ignored:

  1. **A classifier that is 99% accurate leaks one national ID in a hundred.**
     This runs on every outbound message and on every string that reaches the
     rolling summary, which is thousands of calls a day. A regex that matches
     too much wastes a phone number; a model that misses one writes a child's
     ID number into a summary that is then sent to the model forever.

  2. **It has to be explainable.** A reviewer asking "why was this redacted"
     gets a rule name and a span. "The model thought it looked like an address"
     is not an answer anybody can act on.

  3. **It has to be free and instant.** It is on the critical path of every
     turn.

## What this catches, and what it does not

It catches: e-mail addresses, phone numbers (including the local +1-869 form),
national ID numbers, bank/account numbers, full dates of birth, and street
addresses. Those are the fields the registration flow collects, which is the
threat model that matters here -- a parent typing their national ID into a chat
box because the assistant asked for it.

It does not catch a name. Names are not reliably distinguishable from ordinary
words without a model, and a redactor that eats every capitalised word makes
the transcript unreadable. Names are handled structurally instead: the
registration flow persists them to `application_pii` and puts
`[collected: full_name]` in the transcript, so a name never has to be *found* in
prose because it was never *written* to prose.

## The two redactors are not interchangeable

`redact` produces text a human still reads -- the outbound safety gate uses it,
and its job is to remove the number while leaving a readable sentence.

`redact_for_summary` produces text a *model* reads. It replaces the value with
`[collected: date_of_birth]`, which tells the model the fact was captured
without telling it the fact. That distinction is the whole reason the rolling
summary can exist at all on a product that collects a minor's DOB.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

#: The field names this module can name. Used in `[collected: ...]` markers and
#: in the flags `safety_in` raises, so the two always agree.
PIIKind = str

PII_KINDS: Final[tuple[str, ...]] = (
    "email",
    "phone",
    "national_id",
    "account_number",
    "date_of_birth",
    "street_address",
)


@dataclass(frozen=True, slots=True)
class PIISpan:
    """One match: what it is, where it is, and what was there.

    `text` is carried so a caller can log the *kind* alongside a redacted
    preview rather than the value itself. Nothing in this codebase logs
    `span.text`; it exists for tests and for the one admin path that legitimately
    shows a reviewer what was collected.
    """

    kind: PIIKind
    start: int
    end: int
    text: str


# ── the patterns ─────────────────────────────────────────────────────────────
#
# Order matters and is load-bearing. `detect` resolves overlaps by preferring
# the EARLIER pattern in this list, so anything specific has to precede anything
# general. An account number pattern that ran before the phone pattern would
# claim "869-555-0123" as an account number and label it wrongly in the summary.

#: RFC-shaped enough. Not a validator -- an address that would bounce is still
#: an address somebody typed, and redacting it is still correct.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

#: Phone numbers, with the local form first.
#:
#: St Kitts and Nevis is +1 (869). The general NANP shape follows, then a bare
#: run of 7-15 digits with separators. The bare form is why `_ACCOUNT` and
#: `_NATIONAL_ID` are matched before it in some orderings -- see `_PATTERNS`.
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
#:
#: Matched on context rather than on shape alone, and that is the important
#: decision here. There is no single national-ID format across the region, and
#: a bare nine-digit run is far more often a phone number, an amount in cents,
#: or a knowledge-base row id. Requiring the words nearby -- "national id",
#: "id number", "NIS", "social security" -- means this fires on the case that
#: matters (somebody answering the question "what is your national ID?") and
#: stays quiet on the cases that do not.
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

#: A bare identity-document-shaped run, for the case where the label came a
#: sentence earlier ("What is your national ID?" / "A12345678").
#:
#: Two letters or fewer, then eight or more digits, unbroken. Tight enough that
#: a price, a year and a phone number do not match; loose enough to catch a
#: pasted ID.
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
#:
#: A year alone is not a date of birth and is not redacted -- "I was born in
#: 2015" is age information, which the product already holds as an age band and
#: which the learning agent legitimately reasons about. What must not survive is
#: the complete date, because a complete date plus a name is an identity.
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
#:
#: Anchored on the street-type word rather than on capitalisation, because
#: capitalisation is not reliable in chat and because "12 Main" on its own is
#: more often a score than an address.
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

#: `(kind, pattern, group)`. `group` is which capture holds the value: 0 for
#: the whole match, 1 where the pattern anchors on a label it must not eat.
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
#:
#: Neutral phrases rather than a uniform block, because the sentence still has
#: to read. "Call us on [a phone number]" is comprehensible; "Call us on
#: [REDACTED]" reads like an error.
_NEUTRAL: Final[dict[str, str]] = {
    "email": "[an email address]",
    "phone": "[a phone number]",
    "national_id": "[an ID number]",
    "account_number": "[an account number]",
    "date_of_birth": "[a date of birth]",
    "street_address": "[an address]",
}


def detect(text: str) -> list[PIISpan]:
    """Every piece of personal data in `text`, in the order it appears.

    Overlaps are resolved in favour of whichever pattern is earlier in
    `_PATTERNS`, and then in favour of the longer match. That ordering is why
    "my national id is 869 555 0123" is reported once as a national ID rather
    than twice, as an ID and a phone number -- and reporting it twice would put
    two different `[collected: ...]` markers in the summary for one fact.
    """
    if not text:
        return []

    found: list[tuple[int, int, int, str, str]] = []
    for priority, (kind, pattern, group) in enumerate(_PATTERNS):
        for match in pattern.finditer(text):
            start, end = match.span(group)
            if start < 0 or end <= start:
                continue
            found.append((start, end, priority, kind, match.group(group)))

    # Earliest position wins; on a tie, the earlier pattern; on a tie, the
    # longer span. Sorting by (start, priority, -length) then sweeping is O(n
    # log n) and, more usefully, is a rule somebody can read.
    found.sort(key=lambda item: (item[0], item[2], -(item[1] - item[0])))

    spans: list[PIISpan] = []
    consumed_to = -1
    for start, end, _priority, kind, value in found:
        if start < consumed_to:
            continue
        spans.append(PIISpan(kind=kind, start=start, end=end, text=value))
        consumed_to = end
    return spans


def has_pii(text: str) -> bool:
    """Whether anything at all matched. Cheaper to read than `bool(detect(...))`."""
    return bool(detect(text))


def kinds_in(text: str) -> list[str]:
    """The distinct kinds present, in first-appearance order.

    What `safety_in` puts on the flags, and what the escalation summary reports
    -- "this conversation contained a phone number and a date of birth" is
    useful to a reviewer, and the values themselves are not.
    """
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
    """`text` with every detected value replaced by a neutral phrase.

    For text a person will read. Used by `safety_out` gate (c), which runs on
    every outbound message -- including the model's own, because a model that
    has been told a phone number in an earlier turn will happily repeat it.
    """
    return _rewrite(text, lambda span: _NEUTRAL.get(span.kind, "[removed]"))


def redact_for_summary(text: str) -> str:
    """`text` with every detected value replaced by `[collected: <field>]`.

    For text a MODEL will read, and the difference from `redact` is the point.
    The rolling summary is fed back into the prompt on every subsequent turn
    forever; a date of birth that reaches it is a date of birth in every future
    request. `[collected: date_of_birth]` preserves the only thing the model
    actually needs -- that the field is done and must not be asked for again --
    and preserves nothing else.

    Called BEFORE summarisation, never after. Summarising first and redacting
    the summary would mean the value was in a model prompt already, which is
    exactly the thing being prevented.
    """
    return _rewrite(text, lambda span: f"[collected: {span.kind}]")


def redact_all(texts: Iterable[str]) -> list[str]:
    """`redact_for_summary` over a sequence, for the persist node's message list."""
    return [redact_for_summary(text) for text in texts]
