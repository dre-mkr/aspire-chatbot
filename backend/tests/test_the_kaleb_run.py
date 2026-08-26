"""The turns a nine-year-old actually took, and what each one produced.

From a live transcript: a lesson question answered with a game request, a
correct answer answered with "we did not get to a lesson", a menu choice
answered with a different game's score, and a question about videos answered by
denying the video exists -- above a chip offering it.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.intents import asks_for_a_video, wants_game


class TestAskingForAGameWithoutSayingPlay:
    """"NO I WANT A GAME", in capitals, after being handed a lesson question --
    and it was not a game request, because every pattern needed the verb."""

    @pytest.mark.parametrize(
        "message",
        ["NO I WANT A GAME", "i want a game", "I want another game",
         "can i have a game", "give me a game", "we want a quiz",
         "quiero un juego", "dame un juego", "je veux un jeu"],
    )
    def test_these_ask_for_a_game(self, message):
        assert wants_game(message) is True

    @pytest.mark.parametrize(
        "message",
        ["what is a game", "the game of life is hard", "i want a story"],
    )
    def test_talking_about_games_is_not_asking_for_one(self, message):
        assert wants_game(message) is False


class TestAskingWhichVideoExists:
    """"what video do you have about savings" was answered "I don't have a
    savings video title to share" -- above a chip offering that exact video.
    The corpus holds no titles; only the catalog does, and the question never
    reached it."""

    @pytest.mark.parametrize(
        "message",
        ["what video do you have about savings", "which videos do you have",
         "any videos about saving?", "what films have you got",
         "¿qué videos tienes?", "quel film avez-vous"],
    )
    def test_these_reach_the_catalog(self, message):
        assert asks_for_a_video(message) is True

    @pytest.mark.parametrize(
        "message",
        ["what is a video call", "what video game do you have", "tell me a story"],
    )
    def test_a_video_compound_is_not_a_film_request(self, message):
        """"video call" and "video game" are other things, and a game request
        must reach the games rather than the shelf."""
        assert asks_for_a_video(message) is False

    def test_a_video_game_request_reaches_the_games(self):
        assert wants_game("what video game do you have") is True


class TestTheWrapUpCanCountWithoutAnAccount:
    """"Putting money away for a rainy day." -> "We did not get to a lesson
    this time." Mastery is not recorded for a signed-out reader -- by design --
    so the count was always zero, and most readers are signed out."""

    @pytest.mark.asyncio
    async def test_an_anonymous_session_counts_what_it_touched(self):
        from app.agents.learn.graph import make_wrap_session

        class _EmptyStore:
            async def all_for(self, _learner):
                return []

        state = {
            "learning": {"phase": "wrapping", "concepts_touched": ["CON-1", "CON-2"]},
            "age_band": "9-12",
            "locale": "en",
            "session_id": "s-1",
            "user_id": None,
            "active_agent": "learn_agent",
        }
        update = await make_wrap_session(_EmptyStore())(state)
        said = update["messages"][0].content
        assert "did not" not in said.lower(), said
        assert "2" in said, said

    @pytest.mark.asyncio
    async def test_nothing_touched_still_wraps_nothing(self):
        """The guard that came first still holds: no concept, no ceremony."""
        from app.agents.learn.graph import make_wrap_session

        class _EmptyStore:
            async def all_for(self, _learner):
                return []

        state = {
            "learning": {"phase": "wrapping", "concepts_touched": []},
            "age_band": "9-12",
            "locale": "en",
            "session_id": "s-2",
            "user_id": None,
        }
        update = await make_wrap_session(_EmptyStore())(state)
        assert "messages" not in update


class TestAnAbandonedGameDoesNotOutrankTheNextRequest:
    """Picked "Hangman" from the menu, was answered "You got 2 before we
    stopped. Want to pick it up again, or carry on with the lesson?" """

    @pytest.mark.asyncio
    async def test_an_abandoned_result_yields_to_an_explicit_request(self):
        from langchain_core.messages import HumanMessage

        from app.graph.nodes.cards import make_intent_gate

        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)
        state = {
            "safety_flags": {"game_result": {"game": "truefalse", "completed": False, "score": 2}},
            "messages": [HumanMessage(content="Hangman")],
            "persona": "kaleb",
            "age_band": "9-12",
            "locale": "en",
        }
        update = await gate(state)
        assert update != {}, "the request for Hangman was dropped again"

    @pytest.mark.asyncio
    async def test_a_finished_game_keeps_its_reaction(self):
        """A score deserves its moment; the next request can wait a turn."""
        from langchain_core.messages import HumanMessage

        from app.graph.nodes.cards import make_intent_gate

        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: True)
        state = {
            "safety_flags": {"game_result": {"game": "truefalse", "completed": True, "score": 5}},
            "messages": [HumanMessage(content="Hangman")],
            "persona": "kaleb",
            "age_band": "9-12",
            "locale": "en",
        }
        assert await gate(state) == {}
