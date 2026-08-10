"""Data shapes for the eligibility pre-check."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Language(str, Enum):
    """Re-declared rather than imported from `app.games`."""

    EN = "en"
    ES = "es"
    FR = "fr"


class Verdict(str, Enum):
    """The three outcomes."""

    LIKELY_ELIGIBLE = "likely_eligible"
    NOT_YET = "not_yet"
    NEEDS_CONFIRMATION = "needs_confirmation"


class Criterion(str, Enum):
    """What a verdict turned on, for the copy and for the anonymised outcome."""

    NONE = "none"
    CITIZENSHIP = "citizenship"
    AGE_MINIMUM = "age_minimum"
    AGE_COHORT = "age_cohort"
    RESIDENCE = "residence"
    SCHOOL = "school"


@dataclass(frozen=True, kw_only=True)
class Option:
    """One tappable answer."""

    value: str
    label: str


@dataclass(frozen=True, kw_only=True)
class Question:
    """One step of the flow, as the person sees it."""

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
    """One document, with everything the knowledge base actually says about it."""

    id: str
    title: str
    detail: str
    where: str
    signed_by: str | None = None
    caveat: str | None = None
    # Whether this is an ALTERNATIVE to the item above it rather than another thing to bring.
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
    """What the flow concluded, and everything shown alongside it."""

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
    # Set only on the under-5 branch: the year they can register, so the result can name it rather than saying "lat…
    reminder_year: int | None = None


@dataclass(kw_only=True)
class Session:
    """One person's progress through the flow, server-side."""

    session_id: str
    language: Language
    answers: dict[str, str] = field(default_factory=dict)
    # Which question is showing.
    index: int = 0
    finished: bool = False
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True, kw_only=True)
class Outcome:
    """The only thing that reaches Postgres."""

    verdict: Verdict
    criterion: Criterion
    language: Language
