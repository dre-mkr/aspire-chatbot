"""Naming a game, when the reader cannot spell it."""

from __future__ import annotations

import pytest

from app.graph.nodes import intents


class TestAGameNameSurvivesATypo:
    """The readers of this product are five to twelve and type like it."""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            # The one that was actually typed, in Kittian, with one letter gone.
            ("Ah dat me a say word scamble", "scramble"),
            ("word scamble", "scramble"),
            ("scrambel", "scramble"),
            ("unscrambel", "scramble"),
            ("give me the scrambled words", "scramble"),
            ("hangmen", "hangman"),
            ("hangan", "hangman"),
            ("millionare", "millionaire"),
            ("true or fasle", "true_false"),
            ("true or flase", "true_false"),
        ],
    )
    def test_one_typo_still_launches_the_game(self, message, expected):
        assert intents.named_game(message) == expected

    @pytest.mark.parametrize(
        "message",
        [
            "I want to gamble my money",
            "a million dollars in savings",
            "tell me about compound interest",
            "my balance please",
            "is the true cost of a loan high",
            "is the programme free",
        ],
    )
    def test_a_near_miss_is_not_a_game(self, message):
        """`gamble` scores 0.71 against `scramble`, and must stay out."""
        assert intents.named_game(message) is None

    def test_asking_for_a_game_without_naming_one_still_asks_which(self):
        assert intents.named_game("I would like to play a game") is None

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("word scramble", "scramble"),
            ("true or false", "true_false"),
            ("millionaire", "millionaire"),
            ("hangman", "hangman"),
            ("ahorcado", "hangman"),
            ("verdadero o falso", "true_false"),
            ("vrai ou faux", "true_false"),
            ("millonario", "millionaire"),
        ],
    )
    def test_the_exact_names_are_unchanged(self, message, expected):
        """Fuzzy matching is a fallback; it must not move what already worked."""
        assert intents.named_game(message) == expected
