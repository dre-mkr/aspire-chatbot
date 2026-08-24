"""A savings goal said out loud becomes a signable pledge, then a standing goal."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.agents.qa.nodes import _pledge_instruction
from app.graph.nodes.cards import make_intent_gate
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


class TestThePledgeLoop:
    async def test_a_goal_offers_the_card(self):
        out = await gate(_state("I want to save EC$200 a month for a bicycle"))
        d = out["ui_directives"][0]
        assert d.t == "pledge" and not d.pledged
        assert d.amount_line == "EC$200 a month" and d.goal == "a bicycle"

    async def test_signing_stores_the_pledge(self):
        offer = await gate(_state("I want to save EC$200 a month for a bicycle"))
        out = await gate(_state(offer["ui_directives"][0].button_value))
        assert out["pledge"] == {"amount_line": "EC$200 a month", "goal": "a bicycle"}
        assert out["ui_directives"][0].pledged is True

    async def test_the_standing_pledge_reaches_the_register(self):
        line = _pledge_instruction(
            {"pledge": {"amount_line": "EC$200 a month", "goal": "a bicycle"}}
        )
        assert "EC$200 a month" in line and "bicycle" in line

    async def test_the_youngest_get_a_promise_not_a_pledge(self):
        out = await gate(
            _state("I want to save EC$5 a week for a football", band="5-8")
        )
        assert out["ui_directives"][0].button_label == "I promise"

    @pytest.mark.parametrize(
        "msg", ["what is saving", "I saved my game yesterday", "how do I save money"]
    )
    async def test_no_card_without_an_amount(self, msg):
        assert (await gate(_state(msg))).get("safety_flags", {}).get("card") is None

    async def test_one_standing_pledge_at_a_time(self):
        out = await gate(
            _state(
                "I want to save EC$50 a week for shoes",
                pledge={"amount_line": "EC$200 a month", "goal": "a bicycle"},
            )
        )
        assert out.get("safety_flags", {}).get("card") is None
