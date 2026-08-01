"""Data shapes for the games layer.

The split that matters here is between what the engine knows and what it hands
out. An `Entry` carries the answer; nothing that leaves the engine does, except
`Reveal` — and a `Reveal` is only ever produced by an operation that has already
consumed the item it names.

That is the integrity property, and it is enforced by these types rather than by
filtering at the boundary: a caller cannot accidentally serialise an answer it
was never given.

Nothing here is named for a particular game. `Prompt` carries a `kind` and some
`text`; a scramble puts letters in it and true/false puts a statement in it, and
the engine never learns the difference.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Persona(str, Enum):
    """Mirrors `app.voice.registry.Persona`.

    Deliberately re-declared rather than imported: the voice module owns voice
    ids and can be switched off entirely, and games must not stop working
    because of it. The two are checked against each other in the tests.
    """

    STELLA = "stella"
    ORION = "orion"
    AURORA = "aurora"
    NOVA = "nova"


# Games are a learning activity for account holders. A parent or a newcomer
# asking about them wants to know what their child is doing, not to play.
PLAYING_PERSONAS = frozenset({Persona.STELLA, Persona.ORION})


class Language(str, Enum):
    EN = "en"
    ES = "es"
    FR = "fr"


class Volatility(str, Enum):
    """Whether a fact can go stale underneath us.

    `STABLE` is a definition — what interest is, what a budget does. It does not
    expire. `VOLATILE` is a figure someone else sets and can change without
    telling us: a statutory rate, a fee, a threshold. A volatile item is only
    servable while its `verified_on` date is inside the review window, because
    the alternative is teaching a child last decade's rate as fact.
    """

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

    # Provenance. `stable` content ignores the dates; volatile content is only
    # served while someone has confirmed it recently.
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
    """One row of a numbered breakdown inside an explanation.

    The 10-20-30-40 formula is the case that needs this: four labelled shares
    that only make sense read against each other, which prose cannot do.
    """

    marker: str
    label: str
    text: str


@dataclass(frozen=True, kw_only=True)
class StatementEntry(Entry):
    """One true/false item.

    The explanation is the reason this game exists — ECCB wrote real teaching
    into each one, and it is reproduced verbatim rather than regenerated. The
    verdict is only the hook that makes someone read it.

    `explanation` is always the flat, authoritative text. The fields under it are
    an optional presentation layer for content that has been laid out: a line to
    lead with, the paragraphs it breaks into, a numbered list where one belongs.
    A client that has none of them still has the whole explanation.
    """

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
    """What the set says once every item is done.

    Set-level rather than per-item: the point of it is what the five say
    together, which no single item can carry.
    """

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
    # A set still being authored. It loads and validates like any other — so the
    # structure stays under test — but it is never served. This is the switch
    # that keeps placeholder copy away from a child while the real content is
    # still being chased.
    draft: bool = False

    def __len__(self) -> int:
        return len(self.entries)


# --- What the engine hands out -------------------------------------------


@dataclass(frozen=True, slots=True)
class Prompt:
    """An item as the player sees it. Structurally cannot carry the answer.

    `kind` tells a client how to render `text`: scrambled letters to arrange, or
    a statement to judge. `choices` is empty when the player composes their own
    answer and populated when the answer is a pick from a fixed set.
    """

    kind: PromptKind
    text: str
    position: int
    total: int
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Summary:
    solved: int
    # Answered wrong, in a game where that resolves the item. Neither solved nor
    # skipped, and worth counting separately from both.
    missed: int
    skipped: int
    total: int
    hints_used: int
    duration_seconds: float
    # The set's own closing words, when it has any. Reaches the client exactly
    # once, with the result that finishes the round.
    closing: Closing | None = None


@dataclass(frozen=True, slots=True)
class Reveal:
    """The one type carrying an answer.

    Only produced by an operation that has already advanced past the item, so
    the revealed answer is no longer scorable by the time anyone holds it.

    `explanation` is always populated. Everything after it is the optional
    layout, filled by games whose teaching is longer than a sentence.
    """

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
    """A running game as the browser is allowed to see it.

    Read-only, and answer-free like everything else that leaves the engine. This
    is what a page reload asks for: the client held none of this, so refreshing
    loses nothing.
    """

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
    # Present only when this answer RESOLVED the item — right, or wrong in a
    # game that moves on. An unresolved wrong answer carries none, which is what
    # keeps a scramble's word secret while it is still being guessed at.
    reveal: Reveal | None = None
    next_prompt: Prompt | None = None
    finished: bool = False
    summary: Summary | None = None
    # Set when the answer could not be read at all — an ambiguous `yes` on a
    # true/false, say. Not a wrong answer: the item stays open and unspent.
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
    # Fixed at start. For a game that plays its whole set this is seed order;
    # for one that serves a round it is the shuffled selection, and either way
    # it is stored so a reload resumes exactly the same items in the same order.
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
