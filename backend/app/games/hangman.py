"""Hangman: one letter at a time, with the word never leaving the server."""

from __future__ import annotations

from functools import lru_cache

from app.games.config import GameSettings, get_game_settings
from app.games.loader import HANGMAN, load_sets
from app.games.models import (
    Entry,
    GameSet,
    HangmanEntry,
    Language,
    Prompt,
    PromptKind,
    Reveal,
)
from app.games.normalise import letters_of, normalise

#: What is drawn as still hidden.
MASK = "_"


def masked(word: str, guessed: str) -> str:
    """The board: letters found, everything else a blank.

    Built from the GUESSED set forward, never from the word with letters
    removed. That direction is the whole safety property -- the answer is never
    in anything sent to the client, so there is nothing to read out of the
    payload, and `tests/games/test_no_answer_leak.py` can prove it.

    Spaces and hyphens are shown, because a two-word answer that looks like one
    long word is a puzzle about the puzzle.
    """
    found = {ch for ch in normalise(guessed) if ch}
    out = []
    for char in word:
        if not char.isalpha():
            out.append(char)
        elif normalise(char) in found:
            out.append(char)
        else:
            out.append(MASK)
    return " ".join(out)


class HangmanGame:
    """Guess the word a letter at a time.

    The first game here whose submissions are MOVES rather than answers, which
    is why `GameWithMoves` exists: the engine's rule is "a correct answer
    resolves the item", and under it the first right letter ended the word.
    `record` is what says when a word is actually finished, and the letters
    found live in the session, so the word itself never leaves this process
    until it is revealed.

    A guess that is not a single letter and not a word is UNREADABLE rather than
    wrong, so `check` returns None and the engine leaves the item open without
    spending a life -- which is what a mistyped letter needs.
    """

    game_type = HANGMAN
    display_name = "Hangman"

    supports_hints = True

    round_size = 4

    # The letters already found stay on the board; a wrong guess costs a life,
    # not the word.
    advance_on_wrong = False

    def __init__(self, settings: GameSettings | None = None) -> None:
        self._settings = settings or get_game_settings()
        self._by_language = load_sets(
            self._settings.resolved(self._settings.seed_dir), game_type=HANGMAN
        )
        self._entries: dict[str, HangmanEntry] = {
            entry.id: entry
            for sets in self._by_language.values()
            for game_set in sets
            for entry in game_set.entries
            if isinstance(entry, HangmanEntry)
        }

    # --- content ----------------------------------------------------------

    def sets_for(self, language: Language) -> list[GameSet]:
        # Drafts are loaded and validated, never played.
        return [s for s in self._by_language.get(language, []) if not s.draft]

    def entry(self, entry_id: str) -> HangmanEntry:
        return self._entries[entry_id]

    # --- rules ------------------------------------------------------------

    def prompt(self, entry: Entry, position: int, total: int) -> Prompt:
        assert isinstance(entry, HangmanEntry)
        # The opening position: nothing guessed, so every letter is a blank. The
        # engine redraws this from `board()` once moves have been made.
        return Prompt(
            kind=PromptKind.HANGMAN,
            text=masked(entry.word, ""),
            position=position,
            total=total,
            # The alphabet is the keyboard, and it is the same every time, so it
            # is not sent. What IS sent is the length, in the mask.
            choices=(),
        )

    def check(self, entry: Entry, answer: str) -> bool | None:
        """A whole word, or one letter.

        A word is the player committing, and is right or wrong. A single letter
        is right if it is in the word. Anything else -- two letters, a digit, an
        empty string -- is unreadable, and the engine keeps the item open.
        """
        assert isinstance(entry, HangmanEntry)
        said = normalise(answer)
        if not said:
            return None

        target = normalise(entry.word)
        if said == target:
            return True

        if len(said) == 1 and said.isalpha():
            return said in set(letters_of(entry.word))

        # A guess at the whole word that is not the word. Long enough to be an
        # attempt rather than a slip.
        if len(said) >= 3 and said.isalpha():
            return False

        return None

    # --- moves -------------------------------------------------------------
    #
    # `GameWithMoves`. A letter is a move; only a complete word finishes the
    # item. Everything the player has earned lives in `progress`, which the
    # engine hands back on every submission and clears between words -- so the
    # word itself is never held anywhere the client can reach.

    def record(self, entry: Entry, answer: str, progress: dict) -> bool:
        """Record a guess. True when the word is now fully known."""
        assert isinstance(entry, HangmanEntry)
        said = normalise(answer)
        guessed = set(progress.get("guessed") or ())

        if said == normalise(entry.word):
            # They said the whole word. Nothing left to guess.
            progress["guessed"] = sorted(set(letters_of(entry.word)))
            return True

        if len(said) == 1 and said.isalpha():
            guessed.add(said)
            progress["guessed"] = sorted(guessed)
            # Finished only when every distinct letter has been found.
            return set(letters_of(entry.word)) <= guessed

        # A wrong whole-word guess: the player committed and was wrong, so the
        # item is over. `check` already returned False, so it resolves as missed.
        if len(said) >= 3 and said.isalpha():
            return True

        return False

    def board(self, entry: Entry, progress: dict) -> str:
        assert isinstance(entry, HangmanEntry)
        return masked(entry.word, "".join(progress.get("guessed") or ()))

    def unreadable_message(self, answer: str) -> str:
        return "Guess one letter, or say the whole word if you think you have it."

    def reveal(self, entry: Entry) -> Reveal:
        assert isinstance(entry, HangmanEntry)
        return Reveal(
            answer=entry.word,
            explanation=entry.definition,
            topic=entry.topic,
        )

    def teaching(self, entry: Entry) -> str:
        assert isinstance(entry, HangmanEntry)
        return entry.definition

    def hint(self, entry: Entry, level: int) -> str:
        """Category, then length, then the meaning. Never a letter.

        Giving a letter would be playing the game for them; every rung here says
        something about what the word MEANS, which is the part worth learning.
        """
        assert isinstance(entry, HangmanEntry)
        if level <= 1:
            return entry.hint
        if level == 2:
            distinct = len(set(letters_of(entry.word)))
            return (
                f"It has {len(letters_of(entry.word))} letters, "
                f"{distinct} of them different."
            )
        return entry.definition


@lru_cache(maxsize=1)
def get_hangman() -> HangmanGame:
    """Process-wide instance. Seeds are read once, at first use."""
    return HangmanGame()
