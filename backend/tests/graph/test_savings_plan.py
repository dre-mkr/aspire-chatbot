"""A goal with no number yet is a plan, and a plan takes more than one turn.

The Kaleb run of 25 Aug, pinned. A nine-year-old asked for help saving for a
bike and was declined; asked how much to put away each week and was given a
quiz question about what saving is called. Neither sentence is a claim about
the programme, and grading them as one is what produced both answers.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.agents.qa.nodes import _plan_instruction
from app.graph.nodes.cards import PLAN_TURNS, make_intent_gate
from app.graph.state import initial_state

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


gate = make_intent_gate()


def _state(message, band="9-12", **over):
    s = initial_state(
        session_id="s", user_id="u", device_id="d",
        persona="kaleb", age_band=band, account_status="active", locale="en",
    )
    s["messages"] = [HumanMessage(content=message)]
    s.update(over)
    return s


class TestAPlanOpens:
    async def test_a_goal_with_no_amount_starts_a_plan(self):
        out = await gate(_state("help me save for a bike it costs EC$300"))
        assert out["plan_goal"]
        assert out["plan_arc"]["turns"] == 1

    async def test_the_plan_writes_no_prose_of_its_own(self):
        """Like the story handoff: the node marks the turn, an agent answers it."""
        out = await gate(_state("how do i save up for a bike"))
        assert not out.get("messages")
        assert not out.get("quick_replies")

    async def test_an_amount_is_still_a_pledge_not_a_plan(self):
        """The two hand to each other; a commitment is not a request for one."""
        out = await gate(_state("I want to save EC$200 a month for a bicycle"))
        assert out.get("plan_goal") is None
        assert out["ui_directives"][0].t == "pledge"

    async def test_a_story_in_progress_is_not_interrupted_by_arithmetic(self):
        out = await gate(
            _state(
                "how do i save up for a bike",
                story_arc={"topic": "Saving up", "beat": 2, "wallet": 100},
            )
        )
        assert out.get("plan_goal") is None


class TestAPlanCarries:
    ARC = {"plan_arc": {"goal": "a bike", "turns": 1}}

    @pytest.mark.parametrize(
        "message",
        [
            "how much should i put away each week",
            "it costs EC$300",
            "how long will that take",
        ],
    )
    async def test_the_next_number_belongs_to_the_plan(self, message):
        out = await gate(_state(message, **self.ARC))
        assert out["plan_goal"] == "a bike"
        assert out["plan_arc"]["turns"] == 2

    @pytest.mark.parametrize(
        "message",
        [
            "how much do i get from ASPIRE",
            "am i eligible",
            "who runs the programme",
        ],
    )
    async def test_a_question_about_the_programme_is_never_a_plan(self, message):
        """The exemption skips the retrieval floors, so this is a safety edge.

        "How much do I get from ASPIRE" is arithmetic by the look of it and a
        claim about a government programme in substance. It goes through the
        gates like any other.
        """
        out = await gate(_state(message, **self.ARC))
        assert out.get("plan_goal") is None

    @pytest.mark.parametrize("message", ["i want a game", "tell me a story", "make it simpler"])
    async def test_asking_for_something_else_leaves_the_plan(self, message):
        out = await gate(_state(message, **self.ARC))
        assert out.get("plan_goal") is None

    async def test_an_unrelated_question_does_not_extend_it(self):
        out = await gate(_state("what is compound interest", **self.ARC))
        assert out.get("plan_goal") is None

    async def test_a_follow_up_needs_a_plan_to_follow(self):
        out = await gate(_state("how much should i put away each week"))
        assert out.get("plan_goal") is None

    async def test_the_plan_closes_rather_than_becoming_a_mode(self):
        """Left open it would claim every later message containing a number."""
        spent = {"plan_arc": {"goal": "a bike", "turns": PLAN_TURNS}}
        out = await gate(_state("how much should i put away each week", **spent))
        assert out.get("plan_goal") is None


class TestWhatTheModelIsTold:
    def test_no_plan_no_instruction(self):
        assert _plan_instruction(_state("hello")) is None

    def test_a_plan_is_told_it_is_not_a_corpus_question(self):
        line = _plan_instruction(_state("x", plan_goal="a bike"))
        assert line and "SAVINGS PLAN" in line and "a bike" in line

    def test_a_plan_with_no_goal_asks_rather_than_assumes(self):
        line = _plan_instruction(_state("x", plan_goal=""))
        assert line and "has not said what for" in line

    def test_the_youngest_band_plans_in_steps_not_percentages(self):
        line = _plan_instruction(_state("x", band="5-8", plan_goal="a kite"))
        assert line and "picture" in line

    def test_aspire_facts_are_still_cited(self):
        """The exemption is for their numbers, not for the programme."""
        line = _plan_instruction(_state("x", plan_goal="a bike"))
        assert "extracts" in line and "cited" in line
