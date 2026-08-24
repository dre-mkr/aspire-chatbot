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


class TestTheGateReachesTheMatcher:
    """The typo tolerance was unreachable: this gate runs before it."""

    @pytest.mark.parametrize(
        "message", ["word scamble", "scamble", "scrambel", "hangmen", "millionare"]
    )
    def test_a_misspelled_name_is_a_request_to_play(self, message):
        from app.graph.nodes.intents import named_game, wants_game

        assert named_game(message) is not None, "the matcher understands it"
        assert wants_game(message), (
            "...and the gate must let it through, or `_open_game` -- where the "
            "matcher is called -- is never reached at all"
        )

    @pytest.mark.parametrize(
        "message", ["word scramble", "hangman", "I want to play a game", "let's play"]
    )
    def test_what_already_worked_still_does(self, message):
        from app.graph.nodes.intents import wants_game

        assert wants_game(message)

    @pytest.mark.parametrize(
        "message",
        [
            "what is compound interest",
            "a million dollars in savings",
            "is the programme free",
            "my balance please",
        ],
    )
    def test_and_a_question_is_still_not_a_game(self, message):
        from app.graph.nodes.intents import wants_game

        assert not wants_game(message)


class TestWatchingAStoryIsAskingForOne:
    """A child asked "Can I watch a story?" and got a saving hint."""

    @pytest.mark.parametrize(
        "message",
        [
            # English
            "Can I watch a story?", "watch a story", "see a story",
            "show me a story", "tell me a story", "Can we hear a story?",
            # French
            "Puis-je regarder une histoire ?", "Je veux voir une histoire",
            "Raconte-moi une histoire", "je peux écouter une histoire",
            # Spanish
            "¿Puedo ver un cuento?", "Quiero ver una historia",
            "Cuéntame un cuento", "cuentame una historia",
        ],
    )
    def test_every_way_a_child_asks(self, message):
        """Only the TELL verbs were listed, so watching one was not a request.

        It fell through to mastery placement and came back as a hint from a
        lesson the reader never started -- in French, which is how it was found.
        """
        assert intents.wants_story(message)

    @pytest.mark.parametrize(
        "message",
        ["Can I watch a video?", "I want to watch a video", "show me a video"],
    )
    def test_a_video_is_still_a_video(self, message):
        """`asks_for_a_video` yields to a story match, so this had to be checked."""
        assert not intents.wants_story(message)
        assert intents.asks_for_a_video(message)

    @pytest.mark.parametrize(
        "message",
        ["what is saving", "my balance please", "the history of ASPIRE",
         "tell me about saving", "how do I open an account"],
    )
    def test_and_an_ordinary_question_is_neither(self, message):
        assert not intents.wants_story(message)
        assert not intents.asks_for_a_video(message)
