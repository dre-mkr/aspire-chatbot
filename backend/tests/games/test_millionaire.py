"""Four choices, one right, and every way a player might name it.

The tests that matter here are the ones about how an answer ARRIVES. A tapped
button sends the option's text, but a child in the composer types "B", or "2",
or nothing readable at all -- and being marked wrong for typing the right
answer is the game breaking, not the player failing.
"""

from __future__ import annotations

import pytest

from app.games.millionaire import get_millionaire
from app.games.models import Language, PromptKind, QuizEntry


@pytest.fixture(scope="module")
def game():
    return get_millionaire()


@pytest.fixture(scope="module")
def entries(game) -> list[QuizEntry]:
    return [
        entry
        for game_set in game.sets_for(Language.EN)
        for entry in game_set.entries
        if isinstance(entry, QuizEntry)
    ]


class TestTheContent:
    def test_there_are_questions_to_ask(self, entries):
        assert entries

    def test_every_question_has_four_distinct_choices(self, entries):
        for entry in entries:
            assert len(entry.choices) == 4, entry.id
            assert len(set(entry.choices)) == 4, entry.id

    def test_every_answer_index_points_at_a_real_choice(self, entries):
        for entry in entries:
            assert 0 <= entry.answer_index < len(entry.choices), entry.id
            assert entry.answer == entry.choices[entry.answer_index]

    def test_every_question_asks_something(self, entries):
        for entry in entries:
            assert entry.question.rstrip().endswith("?"), entry.id

    def test_every_question_teaches_after_it_is_answered(self, entries):
        """The explanation is the reason the game exists, not a nicety."""
        for entry in entries:
            assert entry.explanation.strip(), entry.id

    def test_each_persona_has_its_own_set(self, game):
        """Otherwise the engine's filter finds nothing and the card 422s."""
        bands = {
            band.value
            for game_set in game.sets_for(Language.EN)
            for entry in game_set.entries
            for band in entry.persona_bands
        }
        assert {"stella", "orion", "guest"} <= bands

    def test_the_answer_is_not_the_longest_choice_every_time(self, entries):
        """A quiz where the longest option is always right is not a quiz."""
        longest = [
            entry.answer_index == max(range(4), key=lambda i: len(entry.choices[i]))
            for entry in entries
        ]
        assert sum(longest) < len(entries), "the answer is always the longest option"

    def test_the_answer_is_not_always_in_the_same_position(self, entries):
        assert len({entry.answer_index for entry in entries}) > 1


class TestThePrompt:
    def test_the_prompt_carries_the_choices_and_not_the_answer(self, game, entries):
        entry = entries[0]
        prompt = game.prompt(entry, 1, 5)
        assert prompt.kind is PromptKind.QUIZ
        assert list(prompt.choices) == list(entry.choices)
        # The index is what the client would need in order to cheat, and it is
        # the one thing that never leaves this side.
        assert not hasattr(prompt, "answer_index")


class TestHowAnAnswerMayArrive:
    def test_the_option_text_is_accepted(self, game, entries):
        entry = entries[0]
        assert game.check(entry, entry.answer) is True

    def test_a_wrong_option_text_is_wrong(self, game, entries):
        entry = entries[0]
        wrong = entry.choices[(entry.answer_index + 1) % 4]
        assert game.check(entry, wrong) is False

    def test_the_letter_is_accepted(self, game, entries):
        entry = entries[0]
        letter = "abcd"[entry.answer_index]
        assert game.check(entry, letter) is True
        assert game.check(entry, letter.upper()) is True

    def test_a_wrong_letter_is_wrong(self, game, entries):
        entry = entries[0]
        wrong = "abcd"[(entry.answer_index + 1) % 4]
        assert game.check(entry, wrong) is False

    def test_the_number_is_accepted(self, game, entries):
        entry = entries[0]
        assert game.check(entry, str(entry.answer_index + 1)) is True

    def test_case_and_spacing_do_not_matter(self, game, entries):
        entry = entries[0]
        assert game.check(entry, f"  {entry.answer.upper()}  ") is True

    @pytest.mark.parametrize("said", ["", "   ", "maybe the second one", "z", "9"])
    def test_something_unreadable_is_none_rather_than_wrong(self, game, entries, said):
        """None leaves the question open; the engine does not spend an attempt.

        A typo costing a player their answer is the difference between a game
        and a trap.
        """
        assert game.check(entries[0], said) is None


class TestTheShapeOfTheGame:
    def test_a_wrong_answer_moves_on(self, game):
        """The four options are still on screen; a retry is a three-way guess."""
        assert game.advance_on_wrong is True

    def test_there_are_no_hints(self, game):
        """The four choices ARE the hint. A nudge on top of them is the answer."""
        assert game.supports_hints is False

    def test_asking_for_a_hint_anyway_raises_rather_than_leaking(self, game, entries):
        with pytest.raises(NotImplementedError):
            game.hint(entries[0], 1)

    def test_the_reveal_carries_the_answer_and_its_teaching(self, game, entries):
        entry = entries[0]
        reveal = game.reveal(entry)
        assert reveal.answer == entry.answer
        assert reveal.explanation == entry.explanation
