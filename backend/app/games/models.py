"""Data shapes for the games layer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

# Re-exported so `app.games.models` stays the one import for this package's vocabulary.
from app.domain import Language, Persona

# Games are a learning activity for account holders.
#
# `EVERYONE` plays from the general-purpose pool: the reader has not said who
# they are, and refusing them a game would make "Everyone" the one persona that
# quietly does less. Aurora and Nova stay out on purpose -- both are written
# around programme information and teaching material, and a guardian mid-form
# does not want a quiz.
PLAYING_PERSONAS = frozenset({Persona.STELLA, Persona.ORION, Persona.EVERYONE})


class Volatility(str, Enum):
    """Whether a fact can go stale underneath us."""

    STABLE = "stable"
    VOLATILE = "volatile"


class PromptKind(str, Enum):
    """How an item is put to the player."""

    SCRAMBLE = "scramble"
    STATEMENT = "statement"


# --- Seed content ---------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Entry:
    """What every game's item has in common. Never leaves the engine."""

    id: str
    language: Language
    difficulty_band: str
    persona_bands: tuple[Persona, ...]
    topic: str | None = None

    # Provenance.
    volatility: Volatility = Volatility.STABLE
    verified_on: date | None = None
    source_document: str | None = None

    def servable_on(self, today: date, *, review_days: int) -> bool:
        if self.volatility is Volatility.STABLE:
            return True
        if self.verified_on is None:
            return False
        return (today - self.verified_on).days <= review_days


@dataclass(frozen=True, kw_only=True)
class ScrambleEntry(Entry):
    word: str
    scramble: str
    hint: str
    definition: str


@dataclass(frozen=True, kw_only=True)
class Bullet:
    """One row of a numbered breakdown inside an explanation."""

    marker: str
    label: str
    text: str


@dataclass(frozen=True, kw_only=True)
class StatementEntry(Entry):
    """One true/false item."""

    statement: str
    answer: bool
    explanation: str

    takeaway: str | None = None
    paragraphs: tuple[str, ...] = ()
    bullets: tuple[Bullet, ...] = ()
    after: str | None = None
    topic_line: str | None = None


@dataclass(frozen=True, kw_only=True)
class Closing:
    """What the set says once every item is done."""

    lead: str
    text: str


@dataclass(frozen=True)
class GameSet:
    id: str
    game_type: str
    language: Language
    title: str
    source: str
    entries: tuple[Entry, ...]
    closing: Closing | None = None
    # A set still being authored.
    draft: bool = False

    def __len__(self) -> int:
        return len(self.entries)


# --- What the engine hands out -------------------------------------------


@dataclass(frozen=True, slots=True)
class Prompt:
    """An item as the player sees it."""

    kind: PromptKind
    text: str
    position: int
    total: int
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Summary:
    solved: int
    # Answered wrong, in a game where that resolves the item.
    missed: int
    skipped: int
    total: int
    hints_used: int
    duration_seconds: float
    # The set's own closing words, when it has any.
    closing: Closing | None = None


@dataclass(frozen=True, slots=True)
class Reveal:
    """The one type carrying an answer."""

    answer: str
    explanation: str
    takeaway: str | None = None
    paragraphs: tuple[str, ...] = ()
    bullets: tuple[Bullet, ...] = ()
    after: str | None = None
    topic: str | None = None
    topic_line: str | None = None


@dataclass(frozen=True, slots=True)
class GameState:
    """A running game as the browser is allowed to see it."""

    game_type: str
    display_name: str
    prompt: Prompt
    supports_hints: bool
    hint_level: int
    max_hint_level: int
    # Clue texts for the levels already spent, so a reload redraws them.
    hints: tuple[str, ...]
    attempts: int
    solved: int
    skipped: int
    total: int
    language: Language
    persona: Persona | None


@dataclass(frozen=True, slots=True)
class SubmitResult:
    correct: bool
    attempts: int
    # The teaching, on a resolved item: a definition, or ECCB's own explanation.
    teaching_note: str | None = None
    # Present only when this answer RESOLVED the item — right, or wrong in a game that moves on.
    reveal: Reveal | None = None
    next_prompt: Prompt | None = None
    finished: bool = False
    summary: Summary | None = None
    # Set when the answer could not be read at all — an ambiguous `yes` on a true/false, say.
    unreadable: str | None = None


@dataclass(frozen=True, slots=True)
class HintResult:
    text: str
    level: int
    # Set when the ladder is exhausted and the item has been given up.
    reveal: Reveal | None = None
    next_prompt: Prompt | None = None
    finished: bool = False
    summary: Summary | None = None


@dataclass(frozen=True, slots=True)
class SkipResult:
    reveal: Reveal
    next_prompt: Prompt | None = None
    finished: bool = False
    summary: Summary | None = None


# --- Server-side session --------------------------------------------------


@dataclass(slots=True)
class GameSession:
    """Live state for one conversation. Never serialised to a client."""

    session_id: str
    game_type: str
    set_id: str
    language: Language
    persona: Persona | None
    # Fixed at start.
    order: tuple[str, ...] = ()
    index: int = 0
    hint_level: int = 0
    attempts: int = 0
    solved: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    hints_used: dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def finished(self) -> bool:
        return self.index >= len(self.order)

    @property
    def current_entry_id(self) -> str | None:
        return None if self.finished else self.order[self.index]

    def advance(self) -> None:
        """Move to the next item and reset per-item counters."""
        self.index += 1
        self.hint_level = 0
        self.attempts = 0
        self.updated_at = time.time()

    def total_hints(self) -> int:
        return sum(self.hints_used.values())

    def summarise(self) -> Summary:
        return Summary(
            solved=len(self.solved),
            missed=len(self.missed),
            skipped=len(self.skipped),
            total=len(self.order),
            hints_used=self.total_hints(),
            duration_seconds=round(time.time() - self.started_at, 1),
        )
