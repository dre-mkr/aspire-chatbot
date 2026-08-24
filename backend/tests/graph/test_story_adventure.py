"""The story is playable: a wallet, an inventory, and choices with prices."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.agents.qa.nodes import _story_instruction, follow_up_chips
from app.graph.nodes.cards import _story_choice, make_intent_gate
from app.graph.state import initial_state

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


gate = make_intent_gate()


def _state(message, arc, band="9-12"):
    s = initial_state(
        session_id="s", user_id="u", device_id="d",
        persona="kaleb", age_band=band, account_status="active", locale="en",
    )
    s["messages"] = [HumanMessage(content=message)]
    s["story_arc"] = arc
    return s


ARC = {"topic": "the island", "beat": 2, "wallet": 100, "inventory": []}


class TestTheChoiceParser:
    def test_priced_and_free(self):
        assert _story_choice("Buy the rope (EC$30)") == ("Buy the rope", 30)
        assert _story_choice("Walk on (free)") == ("Walk on", 0)
        assert _story_choice("what happens next") is None


class TestTheWallet:
    async def test_an_affordable_buy_spends_and_carries(self):
        out = await gate(_state("Buy the rope (EC$30)", dict(ARC)))
        arc = out["story_arc"]
        assert arc["wallet"] == 70 and arc["inventory"] == ["Buy the rope"]
        assert arc["afforded"] is True and arc["beat"] == 3

    async def test_an_unaffordable_buy_is_the_lesson(self):
        out = await gate(_state("Buy the boat (EC$500)", dict(ARC)))
        arc = out["story_arc"]
        assert arc["wallet"] == 100 and arc["inventory"] == []
        assert arc["afforded"] is False

    async def test_a_free_choice_spends_nothing(self):
        out = await gate(_state("Walk on (free)", dict(ARC)))
        arc = out["story_arc"]
        assert arc["wallet"] == 100 and arc["inventory"] == []


class TestTheInstruction:
    def test_the_game_state_reaches_the_model(self):
        s = _state("x", {**ARC, "last_choice": "Buy the rope", "afforded": True})
        s["story_topic"] = "the island"
        text = _story_instruction(s)
        assert "EC$100" in text and "PLAYABLE" in text and "Buy the rope" in text

    def test_the_last_beat_offers_no_choices(self):
        s = _state("x", {**ARC, "beat": 99})
        s["story_topic"] = "the island"
        assert "own line" not in _story_instruction(s)


class TestTheChips:
    def test_choices_become_the_chips(self):
        s = _state("x", dict(ARC))
        s["story_topic"] = "the island"
        answer = "The tide rises.\n- Buy the rope (EC$30)\n- Walk on (free)"
        assert follow_up_chips(s, [], set(), answer) == [
            "Buy the rope (EC$30)",
            "Walk on (free)",
        ]

    def test_no_choices_falls_back_to_the_table(self):
        s = _state("x", dict(ARC))
        s["story_topic"] = "the island"
        assert follow_up_chips(s, [], set(), "The tide rises.") != []
