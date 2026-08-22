"""HTTP shapes for the games API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GameInfoOut(BaseModel):
    id: str
    name: str
    items: int
    supports_hints: bool
    languages: list[str]


class GameListOut(BaseModel):
    games: list[GameInfoOut]


class PromptOut(BaseModel):
    """An item as the player sees it."""

    kind: str
    text: str
    position: int
    total: int
    choices: list[str] = Field(default_factory=list)


class GameStateOut(BaseModel):
    """A running game, as the browser may see it."""

    game_type: str
    display_name: str
    prompt: PromptOut
    supports_hints: bool
    hint_level: int
    max_hint_level: int
    hints: list[str] = Field(default_factory=list)
    attempts: int
    solved: int
    skipped: int
    language: str
    persona: str | None = None


class GameStateEnvelope(BaseModel):
    """What `GET /state` returns. `game` is null when nothing is running."""

    active: bool
    game: GameStateOut | None = None


class ClosingOut(BaseModel):
    """What the set says once every item is done."""

    lead: str
    text: str


class SummaryOut(BaseModel):
    solved: int
    missed: int
    skipped: int
    total: int
    hints_used: int
    duration_seconds: float
    closing: ClosingOut | None = None


class BulletOut(BaseModel):
    marker: str
    label: str
    text: str


class RevealOut(BaseModel):
    """The one shape carrying an answer, and only for a resolved item."""

    answer: str
    explanation: str
    takeaway: str | None = None
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[BulletOut] = Field(default_factory=list)
    after: str | None = None
    topic: str | None = None
    topic_line: str | None = None


class SubmitOut(BaseModel):
    correct: bool
    attempts: int
    # The teaching, once the item has resolved.
    teaching_note: str | None = None
    # Present only when this answer RESOLVED the item — right, or wrong in a game that moves on.
    reveal: RevealOut | None = None
    # Set when the answer could not be read as an answer at all.
    unreadable: str | None = None
    finished: bool = False
    game: GameStateOut | None = None
    summary: SummaryOut | None = None


class HintOut(BaseModel):
    revealed: bool
    hint: str | None = None
    level: int = 0
    reveal: RevealOut | None = None
    finished: bool = False
    game: GameStateOut | None = None
    summary: SummaryOut | None = None


class SkipOut(BaseModel):
    reveal: RevealOut
    finished: bool = False
    game: GameStateOut | None = None
    summary: SummaryOut | None = None


# --- requests --------------------------------------------------------------


class ThreadBody(BaseModel):
    """Every action names its conversation."""

    thread_id: str = Field(min_length=1, max_length=128)


class StartBody(ThreadBody):
    game_type: str = Field(default="word_scramble", max_length=64)
    language: str = Field(default="en", max_length=8)
    persona: str | None = Field(default=None, max_length=32)
    #: Optional. Absent means every item the persona may see, which is how this
    #: endpoint behaved before the age dimension existed and how any client that
    #: does not send it keeps behaving.
    age_band: str | None = Field(default=None, max_length=16)


class SubmitBody(ThreadBody):
    answer: str = Field(min_length=1, max_length=200)
