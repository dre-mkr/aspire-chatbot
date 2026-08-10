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
    """Whether a wrong answer resolves the item.

    A scramble says no: the letters are still there and trying again is the
    activity. True/false says yes — re-asking a binary question is just waiting
    for the coin to land the other way, so the explanation is shown and the
    round moves on. The teaching is the point, not the score.
    """

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
