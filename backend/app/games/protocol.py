"""The contract a game type implements.

Everything above this line — the engine, the tools, the agent, the routing —
talks to `Game` and never to a particular game. Two of them exist: word scramble
and true/false.

A `Game` is stateless. It knows its content and its rules; the engine owns the
session, the cursor and the scoring.

Two capabilities are declared rather than assumed, because true/false proved
that assuming them was wrong:

- `supports_hints`. A hint on a binary choice *is* the answer, so true/false
  declines rather than returning something useless. The engine checks the flag
  and refuses the request itself; a game that says no never has `hint` called.
- `round_size`. A bank of eighteen is not a warm-up. A game may serve a short
  shuffled round instead of its whole set.
"""

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
        """Whether the answer is correct. Pure — never calls a model.

        Returns None when the answer could not be read as an answer at all —
        an ambiguous `yes` on a true/false statement, say. That is not the same
        as wrong: the engine leaves the item open and asks again rather than
        spending it and showing the explanation.
        """
        ...

    def reveal(self, entry: Entry) -> Reveal:
        """The answer and its teaching, for an item being resolved.

        The only place a game hands its answer back. The engine pairs this with
        advancing the cursor, so the answer is never live. Games whose teaching
        runs longer than a sentence fill the optional layout fields too.
        """
        ...

    def unreadable_message(self, answer: str) -> str:
        """What to say when `check` returned None.

        Lives with the content because the right wording depends on what went
        wrong — a yes/no on a true/false statement needs a different sentence
        from an empty box.
        """
        ...

    def teaching(self, entry: Entry) -> str:
        """What to say once the item is resolved, right or wrong.

        The reason the games exist. For a scramble it is the word's meaning; for
        true/false it is ECCB's own explanation, reproduced rather than written.
        """
        ...

    def hint(self, entry: Entry, level: int) -> str:
        """A nudge at 1..max_hint_level, progressively more revealing.

        Only called when `supports_hints` is True. Must never return the answer
        at any level — giving up is the engine's job, through `Reveal`.
        """
        ...
