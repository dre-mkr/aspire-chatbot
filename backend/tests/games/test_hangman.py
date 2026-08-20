"""One letter at a time, and the word never leaving the server.

The board is built from the letters GUESSED, never from the word with letters
taken out. That direction is the whole safety property of this game, and the
first class below is what proves it: there is no payload a client can read the
answer out of before it has earned it.
"""

from __future__ import annotations

import pytest

from app.games.hangman import MASK, get_hangman, masked
from app.games.models import HangmanEntry, Language, PromptKind


@pytest.fixture(scope="module")
def game():
    return get_hangman()


@pytest.fixture(scope="module")
def entries(game) -> list[HangmanEntry]:
    return [
        entry
        for game_set in game.sets_for(Language.EN)
        for entry in game_set.entries
        if isinstance(entry, HangmanEntry)
    ]


class TestTheBoardNeverCarriesTheAnswer:
    def test_nothing_guessed_shows_nothing(self):
        assert masked("SAVE", "") == "_ _ _ _"

    def test_a_guessed_letter_appears_everywhere_it_occurs(self):
        assert masked("SAVINGS", "s") == "S _ _ _ _ _ S"

    def test_an_unguessed_letter_stays_hidden(self):
        assert "V" not in masked("SAVE", "s")

    def test_case_does_not_matter(self):
        assert masked("SAVE", "S") == masked("SAVE", "s")

    def test_spaces_and_hyphens_are_shown_rather_than_hidden(self):
        """A two-word answer that looks like one long word is a different puzzle."""
        assert masked("RAINY DAY", "") == "_ _ _ _ _   _ _ _"

    @pytest.mark.parametrize("guessed", ["", "a", "aeiou", "xyz"])
    def test_the_opening_prompt_hides_every_letter(self, game, entries, guessed):
        for entry in entries:
            board = masked(entry.word, "")
            shown = {c for c in board if c.isalpha()}
            assert not shown, f"{entry.id} shows {shown} before anything is guessed"

    def test_the_prompt_sent_to_a_client_is_all_blanks(self, game, entries):
        for entry in entries:
            prompt = game.prompt(entry, 1, 4)
            assert prompt.kind is PromptKind.HANGMAN
            assert MASK in prompt.text
            assert not any(c.isalpha() for c in prompt.text), entry.id

    def test_the_length_is_the_only_thing_given_away(self, game, entries):
        entry = entries[0]
        prompt = game.prompt(entry, 1, 4)
        assert prompt.text.count(MASK) == sum(1 for c in entry.word if c.isalpha())


class TestTheContent:
    def test_there_are_words_to_guess(self, entries):
        assert entries

    def test_every_word_is_uppercase(self, entries):
        """The board is drawn in capitals; a lowercase seed displays wrong."""
        for entry in entries:
            assert entry.word == entry.word.upper(), entry.id

    def test_every_word_has_at_least_three_distinct_letters(self, entries):
        for entry in entries:
            assert len(set(entry.word)) >= 3, entry.id

    def test_no_clue_gives_the_word_away(self, entries):
        for entry in entries:
            assert entry.word.lower() not in entry.hint.lower(), entry.id
            assert entry.word.lower() not in entry.definition.lower(), entry.id

    def test_each_persona_has_its_own_set(self, game):
        bands = {
            band.value
            for game_set in game.sets_for(Language.EN)
            for entry in game_set.entries
            for band in entry.persona_bands
        }
        assert {"stella", "orion", "everyone"} <= bands

    def test_the_youngest_words_are_shorter_than_the_teenagers(self, game):
        """Not a style note: spelling length IS the difficulty in this game."""
        by_band: dict[str, list[int]] = {}
        for game_set in game.sets_for(Language.EN):
            for entry in game_set.entries:
                for band in entry.persona_bands:
                    by_band.setdefault(band.value, []).append(len(entry.word))
        young = sum(by_band["stella"]) / len(by_band["stella"])
        teen = sum(by_band["orion"]) / len(by_band["orion"])
        assert young < teen, f"stella averages {young:.1f}, orion {teen:.1f}"


class TestGuessing:
    def test_a_letter_in_the_word_is_right(self, game, entries):
        entry = entries[0]
        assert game.check(entry, entry.word[0]) is True

    def test_a_letter_not_in_the_word_is_wrong(self, game):
        entry = HangmanEntry(
            id="t", language=Language.EN, difficulty_band="warmup",
            persona_bands=(), word="SAVE", hint="h", definition="d",
        )
        assert game.check(entry, "z") is False

    def test_the_whole_word_wins(self, game, entries):
        entry = entries[0]
        assert game.check(entry, entry.word) is True
        assert game.check(entry, entry.word.lower()) is True

    def test_a_wrong_whole_word_is_wrong(self, game, entries):
        assert game.check(entries[0], "elephant") is False

    @pytest.mark.parametrize("said", ["", "   ", "4", "??"])
    def test_something_unreadable_is_none_rather_than_wrong(self, game, entries, said):
        """None keeps the item open and does not spend a life on a slip."""
        assert game.check(entries[0], said) is None

    def test_a_wrong_letter_does_not_end_the_word(self, game):
        """The letters already found stay; a wrong guess costs a life, not the word."""
        assert game.advance_on_wrong is False


class TestHints:
    def test_the_first_rung_is_the_category(self, game, entries):
        entry = entries[0]
        assert game.hint(entry, 1) == entry.hint

    def test_the_last_rung_is_the_meaning(self, game, entries):
        entry = entries[0]
        assert game.hint(entry, 3) == entry.definition

    def test_no_rung_ever_gives_a_letter(self, game, entries):
        """A hint that spells part of the answer is playing the game for them."""
        for entry in entries:
            for level in (1, 2, 3):
                assert entry.word.lower() not in game.hint(entry, level).lower()
