"""Data shapes for the eligibility pre-check.

The property this module exists to hold: **an answer is a token, never a fact
about a person.** `age_band` is one of five strings. There is no birthdate
field, no exact age field, no name, no parish-plus-anything. The engine cannot
leak what it was never given, and the outcome row (`Outcome`) is a strictly
narrower thing again — it drops even the tokens.

Nothing here is named for a particular question. A `Question` has options and an
id; the engine walks a list of them and never learns what "citizenship" means.
The meaning lives in `rules.py`, where every rule carries the knowledge-base row
it came from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Language(str, Enum):
    """Re-declared rather than imported from `app.games`.

    Same reasoning the games module gives for re-declaring `Persona`: the two
    features are independently switchable and neither may stop working because
    the other is off. Checked against each other in the tests.
    """

    EN = "en"
    ES = "es"
    FR = "fr"


class Verdict(str, Enum):
    """The three outcomes. There is deliberately no plain yes and no plain no.

    `LIKELY_ELIGIBLE` is the strongest thing this flow may ever say, and its
    copy says "based on what you've told me" in every language. `NOT_YET` covers
    both a child who is too young and an applicant outside the cohort — the
    wording differs by criterion, the outcome type does not. `NEEDS_CONFIRMATION`
    is where everything the knowledge base does not settle goes, and that is
    most of the interesting cases.
    """

    LIKELY_ELIGIBLE = "likely_eligible"
    NOT_YET = "not_yet"
    NEEDS_CONFIRMATION = "needs_confirmation"


class Criterion(str, Enum):
    """What a verdict turned on, for the copy and for the anonymised outcome.

    `NONE` is a real member rather than a null: a likely-eligible result turned
    on nothing, and the insight view counts that alongside the rest.
    """

    NONE = "none"
    CITIZENSHIP = "citizenship"
    AGE_MINIMUM = "age_minimum"
    AGE_COHORT = "age_cohort"
    RESIDENCE = "residence"
    SCHOOL = "school"


@dataclass(frozen=True, kw_only=True)
class Option:
    """One tappable answer.

    `value` is the token the engine stores and reasons over. `label` is what the
    person reads, already in their language — the engine never assembles copy,
    it only ever hands back what `content.py` authored.
    """

    value: str
    label: str


@dataclass(frozen=True, kw_only=True)
class Question:
    """One step of the flow, as the person sees it.

    `position` and `total` drive the progress indicator. `total` is computed per
    session rather than fixed, because the under-5 branch asks one extra
    question and a progress bar that lies about its own length is worse than no
    progress bar.
    """

    id: str
    text: str
    help: str | None
    options: tuple[Option, ...]
    position: int
    total: int
    answered_with: str | None = None
    can_go_back: bool = False


@dataclass(frozen=True, kw_only=True)
class ChecklistItem:
    """One document, with everything the knowledge base actually says about it.

    `caveat` is not decoration. Three of the five documents in the source are
    hedged by the source itself ("confirm the current document list at
    aspire.gov.kn"), and dropping that hedge would present a settled list the
    programme has not published. `signed_by` is filled only where a guardian is
    genuinely involved.
    """

    id: str
    title: str
    detail: str
    where: str
    signed_by: str | None = None
    caveat: str | None = None
    # Whether this is an ALTERNATIVE to the item above it rather than another
    # thing to bring. A passport showing a St. Kitts or Nevis birthplace stands
    # in for a birth certificate (ASP-250); given a tick box of its own it read
    # as a second document to go and find, which is how a checklist sends
    # somebody looking for paperwork they do not need.
    alternative: bool = False


@dataclass(frozen=True, kw_only=True)
class Step:
    """One numbered step of the application walkthrough."""

    number: int
    title: str
    detail: str
    link: str | None = None
    link_label: str | None = None


@dataclass(frozen=True, kw_only=True)
class Result:
    """What the flow concluded, and everything shown alongside it.

    `unresolved` lists every criterion the answers left open, not just the one
    the verdict is filed under — a person who said "I'm not sure" twice should
    see both, and the mentor question is framed from the first.
    """

    verdict: Verdict
    criterion: Criterion
    headline: str
    body: tuple[str, ...]
    disclaimer: str
    unresolved: tuple[str, ...] = ()
    mentor_question: str | None = None
    checklist: tuple[ChecklistItem, ...] = ()
    steps: tuple[Step, ...] = ()
    notices: tuple[str, ...] = ()
    contacts: tuple[str, ...] = ()
    # Set only on the under-5 branch: the year they can register, so the result
    # can name it rather than saying "later".
    reminder_year: int | None = None


@dataclass(kw_only=True)
class Session:
    """One person's progress through the flow, server-side.

    Keyed by the conversation's thread id, exactly as a game session is, and for
    the same reason: the browser holding this would make a refresh mid-flow a
    lost flow. `answers` holds option tokens and nothing else — see the module
    docstring.
    """

    session_id: str
    language: Language
    answers: dict[str, str] = field(default_factory=dict)
    # Which question is showing. Kept rather than derived so that going back
    # does not discard the answers ahead of the cursor.
    index: int = 0
    finished: bool = False
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True, kw_only=True)
class Outcome:
    """The only thing that reaches Postgres.

    Strictly narrower than `Session`: a verdict, the criterion it turned on, the
    language, and when. No thread id — that would link this row to a transcript
    and undo the whole point of it. No option tokens, so no age band and no
    island. This is what the admin insight view counts.
    """

    verdict: Verdict
    criterion: Criterion
    language: Language
