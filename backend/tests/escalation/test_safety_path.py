"""The safety path reaches a person without asking the router's permission."""

from __future__ import annotations

import pytest

from app.graph.main_graph import _after_safety_in, safety_signal
from app.graph.nodes.safety_in import distress_level
from app.graph.state import initial_state

pytestmark = pytest.mark.asyncio


def _state(*, flags: dict | None = None, halt: str | None = None, **overrides):
    state = initial_state(
        session_id="s-safety",
        user_id="u-1",
        device_id="d",
        persona=overrides.pop("persona", "stella"),
        age_band=overrides.pop("age_band", "9-12"),
        account_status="beneficiary",
    )
    state["safety_flags"] = flags or {}
    state["halt_reason"] = halt
    state.update(overrides)
    return state


class TestTheDetectorFeedsTheEdge:
    """The two halves have to agree on the flag names or the edge never fires."""

    @pytest.mark.parametrize(
        "text",
        ["i want to die", "my uncle hits me", "i am scared to go home", "i feel suicidal"],
    )
    async def test_safeguarding_language_routes_to_a_person(self, text):
        level = distress_level(text)
        assert level == "safeguarding"
        assert _after_safety_in(_state(flags={level: True})) == "escalate_agent"

    @pytest.mark.parametrize(
        "text",
        ["i am so lonely", "nobody likes me", "i am being bullied", "we have no food"],
    )
    async def test_distress_language_routes_to_a_person(self, text):
        level = distress_level(text)
        assert level == "distress"
        assert _after_safety_in(_state(flags={level: True})) == "escalate_agent"

    async def test_an_ordinary_message_takes_the_ordinary_path(self):
        """Anything but escalation."""
        assert distress_level("how do i save for a bike") is None
        assert _after_safety_in(_state()) != "escalate_agent"


class TestItIsNotGated:
    async def test_no_counter_no_threshold_first_turn_reaches_a_person(self):
        """Immediate, by contract. A child does not ask three times."""
        assert _after_safety_in(_state(flags={"distress": True})) == "escalate_agent"

    async def test_a_blocked_message_still_escalates(self):
        """The one judgement call in the edge, asserted so it cannot drift."""
        state = _state(flags={"safeguarding": True}, halt="blocked_input")
        assert _after_safety_in(state) == "escalate_agent"

    async def test_a_blocked_message_with_no_safety_signal_still_halts(self):
        """The tie-break must not have quietly disabled halting."""
        assert _after_safety_in(_state(halt="blocked_input")) == "safety_out"

    @pytest.mark.parametrize(
        ("persona", "band"),
        [("stella", "5-8"), ("stella", "9-12"), ("orion", "13-15"), ("aurora", "adult")],
    )
    async def test_every_persona_reaches_a_person(self, persona, band):
        state = _state(flags={"safeguarding": True}, persona=persona, age_band=band)
        assert _after_safety_in(state) == "escalate_agent"


class TestTheRouterIsNotInvolved:
    """The property E.2 must not break."""

    async def test_the_edge_does_not_consult_allowed_agents(self):
        """Even handed an empty allow-list, safety still routes."""
        state = _state(flags={"safeguarding": True})
        state["allowed_agents"] = []
        assert _after_safety_in(state) == "escalate_agent"

    async def test_safety_signal_reports_the_more_urgent_of_the_two(self):
        both = _state(flags={"safeguarding": True, "distress": True})
        assert safety_signal(both) == "safeguarding"

    async def test_the_edge_is_declared_in_the_graph(self):
        """A predicate naming a node with no declared edge fails at runtime, so declare it."""
        from app.graph.main_graph import build_main_graph

        graph = build_main_graph(token=None).get_graph()
        destinations = {
            edge.target for edge in graph.edges if edge.source == "safety_in"
        }
        assert "escalate_agent" in destinations, (
            "safety_in must have a declared edge to escalate_agent; "
            f"it has {sorted(destinations)}"
        )
