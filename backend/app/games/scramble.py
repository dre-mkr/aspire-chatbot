"""Word scramble: unscramble a word, three clues deep."""

from __future__ import annotations

from functools import lru_cache

from app.games.config import GameSettings, get_game_settings
from app.games.loader import WORD_SCRAMBLE, load_sets
from app.games.models import (
    Entry,
    GameSet,
    Language,
    Prompt,
    PromptKind,
    Reveal,
    ScrambleEntry,
)
from app.games.normalise import answer_matches


class WordScrambleGame:
    """Unscramble a word, three hints deep, four words to a set."""

    game_type = WORD_SCRAMBLE
    display_name = "Unscramble These Words"

    supports_hints = True
    # The ECCB handout is four words in a printed order, and the chat game keeps that order.
    round_size = None
    # The letters are still on the table after a wrong guess; rearranging them is the game.
    advance_on_wrong = False

    def __init__(self, settings: GameSettings | None = None) -> None:
        self._settings = settings or get_game_settings()
        self._by_language = load_sets(
            self._settings.resolved(self._settings.seed_dir), game_type=WORD_SCRAMBLE
        )
        self._entries: dict[str, ScrambleEntry] = {
            entry.id: entry
            for sets in self._by_language.values()
            for game_set in sets
            for entry in game_set.entries
            if isinstance(entry, ScrambleEntry)
        }

    # --- content ----------------------------------------------------------

    def sets_for(self, language: Language) -> list[GameSet]:
        # Drafts are loaded and validated, never played.
        return [s for s in self._by_language.get(language, []) if not s.draft]

    def entry(self, entry_id: str) -> ScrambleEntry:
        return self._entries[entry_id]

    # --- rules ------------------------------------------------------------

    def prompt(self, entry: Entry, position: int, total: int) -> Prompt:
        assert isinstance(entry, ScrambleEntry)
        return Prompt(
            kind=PromptKind.SCRAMBLE,
            text=entry.scramble,
            position=position,
            total=total,
        )

    def check(self, entry: Entry, answer: str) -> bool | None:
        assert isinstance(entry, ScrambleEntry)
        # Never None: any typed string is a guess at a word, even a bad one.
        return answer_matches(
            answer,
            entry.word,
            typo_tolerance_min_length=self._settings.typo_tolerance_min_length,
            max_edits=self._settings.typo_max_edits,
        )

    def unreadable_message(self, answer: str) -> str:
        # `check` never returns None here, so this is unreachable in practice.
        return "I could not read that as a word. Try the letters again."

    def reveal(self, entry: Entry) -> Reveal:
        assert isinstance(entry, ScrambleEntry)
        # A word and one sentence. Nothing here needs laying out.
        return Reveal(answer=entry.word, explanation=entry.definition)

    def teaching(self, entry: Entry) -> str:
        assert isinstance(entry, ScrambleEntry)
        return entry.definition

    def hint(self, entry: Entry, level: int) -> str:
        """Three rungs, none of which is the answer."""
        assert isinstance(entry, ScrambleEntry)
        if level <= 1:
            return f"It starts with {entry.word[0].upper()}."
        if level == 2:
            return f"{len(entry.word)} letters — {entry.hint}."
        return entry.definition.rstrip(".") + "."


@lru_cache(maxsize=1)
def get_word_scramble() -> WordScrambleGame:
    """Process-wide instance. Seeds are read once, at first use."""
    return WordScrambleGame()
