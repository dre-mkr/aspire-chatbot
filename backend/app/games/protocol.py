"""The contract a game type implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.games.models import Entry, GameSet, Language, Prompt, Reveal


@runtime_checkable
class Game(Protocol):
    """Content and rules for one game type."""

    game_type: str
    """Stable id used by tools and events, e.g. "word_scramble"."""

    display_name: str
    """What the assistant calls it, e.g. "Unscramble These Words"."""

    supports_hints: bool
    """Whether `hint` may be called at all. False means the engine declines."""

    round_size: int | None
    """How many items one game serves, or None to play the whole set in order."""

    advance_on_wrong: bool
    """Whether a wrong answer resolves the item; a scramble retries, true/false moves on."""

    def sets_for(self, language: Language) -> list[GameSet]:
        """Every playable set in a language. Empty is a normal answer."""
        ...

    def entry(self, entry_id: str) -> Entry:
        """Look up one entry. Raises KeyError if unknown."""
        ...

    def prompt(self, entry: Entry, position: int, total: int) -> Prompt:
        """The item as the player sees it. Must not carry the answer."""
        ...

    def check(self, entry: Entry, answer: str) -> bool | None:
        """Whether the answer is correct."""
        ...

    def reveal(self, entry: Entry) -> Reveal:
        """The answer and its teaching, for an item being resolved."""
        ...

    def unreadable_message(self, answer: str) -> str:
        """What to say when `check` returned None."""
        ...

    def teaching(self, entry: Entry) -> str:
        """What to say once the item is resolved, right or wrong."""
        ...

    def hint(self, entry: Entry, level: int) -> str:
        """A nudge at 1..max_hint_level, progressively more revealing."""
        ...


@runtime_checkable
class GameWithMoves(Protocol):
    """A game where one submission is a MOVE rather than an answer.

    Optional, and checked with `isinstance` at the point of use so that a game
    which does not implement it is unaffected. Hangman is the only one today:
    a letter is progress towards the word, not a verdict on it, and the engine's
    "a correct answer resolves the item" rule would end the word on the first
    right letter.

    A game implementing this keeps its per-item state in `GameSession.progress`,
    which the engine clears on every item and never inspects.
    """

    def record(self, entry: Entry, answer: str, progress: dict) -> bool:
        """Record a move. Returns whether the item is now finished."""
        ...

    def board(self, entry: Entry, progress: dict) -> str:
        """What the player can see so far. Must never contain what they have not earned."""
        ...
