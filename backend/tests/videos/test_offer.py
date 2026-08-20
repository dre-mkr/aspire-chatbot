"""When a finished turn may end by offering a video, and when it must not.

Almost every test here asserts that nothing is offered. That is the feature:
the brief asks for something conversational rather than intrusive, and the only
way to be intrusive with two films is to keep putting them in front of someone
who did not ask.
"""

from __future__ import annotations

import pytest

from app.videos.offer import offer_for


def _state(**overrides):
    """A finished turn's state, with nothing set that would suppress an offer."""
    base = {
        "persona": "stella",
        "locale": "en",
        "safety_flags": {},
        "offered_video": None,
        "videos_offered": [],
    }
    return {**base, **overrides}


class TestWhenAnOfferIsMade:
    def test_a_question_the_film_answers_is_offered_it(self):
        offer = offer_for(_state(), "What does scarcity mean?")
        assert offer is not None
        video_id, chip = offer
        assert video_id == "captain-careful-scarcity"
        assert "scarcity" in chip.lower()

    def test_the_chip_is_short_enough_to_be_read_as_an_acceptance(self):
        """The chip is also what gets SENT, and `wants_video` refuses a sentence.

        This is the seam the feature quietly dies in: a chip phrased as the
        lovely full question arrives as an eleven-word message, fails the
        command-length gate, and opens nothing at all.
        """
        from app.graph.nodes.intents import wants_video

        for question in ("What does scarcity mean?", "How can I start saving money?"):
            offer = offer_for(_state(), question)
            assert offer is not None
            _video_id, chip = offer
            assert wants_video(chip), chip


class TestWhenNoOfferIsMade:
    def test_an_unrelated_question_is_offered_nothing(self):
        assert offer_for(_state(), "who do I contact about my application") is None

    def test_an_empty_turn_is_offered_nothing(self):
        assert offer_for(_state(), "   ") is None

    @pytest.mark.parametrize("card", ["video", "eligibility", "signup", "game"])
    def test_a_turn_that_is_already_a_card_is_not_also_an_offer(self, card):
        """A form and an offer in one turn is the assistant talking over itself."""
        state = _state(safety_flags={"card": card})
        assert offer_for(state, "What does scarcity mean?") is None

    @pytest.mark.parametrize("flag", ["widget_interaction", "game_result"])
    def test_a_continuation_is_not_a_question(self, flag):
        state = _state(safety_flags={flag: True})
        assert offer_for(state, "What does scarcity mean?") is None

    def test_never_two_turns_running(self):
        """One is already in front of them."""
        state = _state(offered_video="monique-saving-adventure")
        assert offer_for(state, "What does scarcity mean?") is None

    def test_never_the_same_film_twice_in_one_conversation(self):
        """A declined offer is an answer. Asking again is not listening."""
        state = _state(videos_offered=["captain-careful-scarcity"])
        assert offer_for(state, "What does scarcity mean?") is None

    def test_a_second_different_film_is_still_allowed(self):
        state = _state(videos_offered=["captain-careful-scarcity"])
        offer = offer_for(state, "How can I start saving money?")
        assert offer is not None and offer[0] == "monique-saving-adventure"

    def test_a_guardian_is_never_offered_one_unasked(self):
        state = _state(persona="aurora")
        assert offer_for(state, "What does scarcity mean?") is None

    def test_a_teacher_is_never_offered_one_unasked(self):
        state = _state(persona="nova")
        assert offer_for(state, "What does scarcity mean?") is None

    def test_a_reader_in_spanish_is_not_offered_an_english_film(self):
        state = _state(locale="es")
        assert offer_for(state, "What does scarcity mean?") is None


class TestNothingHereCanSpoilAnAnsweredTurn:
    """This runs after the answer exists. It must not be able to raise."""

    def test_an_unknown_persona_is_survivable(self):
        state = _state(persona="not-a-persona")
        assert offer_for(state, "What does scarcity mean?") is None

    def test_an_unknown_locale_is_survivable(self):
        state = _state(locale="klingon")
        assert offer_for(state, "What does scarcity mean?") is None

    def test_a_state_missing_every_optional_key_is_survivable(self):
        assert offer_for({}, "What does scarcity mean?") is not None
