"""The router cannot fetch a person any more."""

from __future__ import annotations

import pytest

from app.graph.access import ACCOUNT_STATUSES, AGE_BANDS, PERSONAS, allowed_agents
from app.graph.main_graph import ROUTABLE_AGENTS, _after_cards
from app.graph.nodes.cards import make_intent_gate
from app.graph.nodes.classify import AGENT_DESCRIPTIONS, UNROUTABLE, routable
from app.graph.nodes.intents import wants_human
from app.graph.state import initial_state
from langchain_core.messages import HumanMessage

pytestmark = pytest.mark.asyncio

SIGNED_IN = [
    (persona, band, status)
    for persona in sorted(PERSONAS)
    for band in sorted(AGE_BANDS)
    for status in sorted(ACCOUNT_STATUSES)
]


def _state(message: str, persona="stella", band="9-12", user_id="u-1"):
    state = initial_state(
        session_id="s-1",
        user_id=user_id,
        device_id="d",
        persona=persona,
        age_band=band,
        account_status="prospect",
    )
    state["messages"] = [HumanMessage(content=message)]
    state["allowed_agents"] = allowed_agents(persona, band, "prospect", user_id=user_id)
    return state


class TestNoRouterPathTerminatesAtEscalation:
    async def test_it_is_not_a_routable_destination(self):
        assert "escalate_agent" not in ROUTABLE_AGENTS

    async def test_the_router_is_never_shown_it(self):
        """Filtered from `allowed`, not merely omitted from the classifier's menu."""
        assert "escalate_agent" not in AGENT_DESCRIPTIONS
        assert "escalate_agent" in UNROUTABLE

    @pytest.mark.parametrize(("persona", "band", "status"), SIGNED_IN)
    async def test_filtering_never_empties_a_permitted_row(self, persona, band, status):
        """An emptied row would send a permitted caller down `access_denied`."""
        granted = allowed_agents(persona, band, status, user_id="u")
        if not granted:
            return
        assert routable(granted), f"{persona}/{band}/{status} has no routable agent"

    async def test_stella_keeps_teaching_and_nova_keeps_qa(self):
        # QA leads every row now; Stella keeps the lesson machine right behind it.
        assert routable(allowed_agents("stella", "9-12", "prospect", user_id="u")) == [
            "qa_agent_limited",
            "learn_agent",
        ]
        # More than one, and that is the point: a single-candidate row makes
        # `classify` skip the router entirely.
        assert routable(allowed_agents("nova", "adult", "prospect", user_id="u")) == [
            "qa_agent",
            "learn_agent",
            "learning_preview",
        ]

    async def test_the_anonymous_row_survives_too(self):
        assert routable(allowed_agents("aurora", "adult", "prospect", user_id=None)) == [
            "qa_agent_public",
            "learning_sample",
            "register_agent_step1",
        ]


class TestAskingForAPerson:
    @pytest.mark.parametrize(
        "message",
        [
            "i want to speak to a person",
            "can i talk to a real human",
            "get me an adviser",
            "customer service please",
            "I need a human",
            "hablar con una persona",
            "je veux parler a une personne",
        ],
    )
    async def test_these_are_requests(self, message):
        assert wants_human(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "who can i speak to about eligibility",
            "can a person open the account for a child",
            "is there a person at the branch on saturdays",
            "how do i save money",
        ],
    )
    async def test_these_are_questions_and_stay_with_the_knowledge_base(self, message):
        """A false positive hands somebody to a support queue they did not ask for."""
        assert wants_human(message) is False

    async def test_a_request_escalates_on_turn_one(self):
        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
        update = await gate(_state("i want to speak to a person"))

        assert update["escalation_reason"] == "user_requested_human"
        assert update["safety_flags"]["asked_for_human"] is True

    async def test_it_routes_past_the_classifier(self):
        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
        state = _state("i want to speak to a person")
        state.update(await gate(state))

        assert _after_cards(state) == "escalate_agent"

    @pytest.mark.parametrize(
        ("persona", "band"),
        [("stella", "5-8"), ("stella", "9-12"), ("orion", "13-15"), ("aurora", "adult")],
    )
    async def test_every_persona_can_ask_including_the_one_with_no_tools(
        self, persona, band
    ):
        """Even Stella, whose only routable agent makes no model calls, can ask."""
        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
        update = await gate(_state("i want to talk to a real person", persona, band))

        assert update["escalation_reason"] == "user_requested_human"

    async def test_an_ordinary_message_still_reaches_the_classifier(self):
        gate = make_intent_gate(eligibility_on=lambda: False, games_on=lambda: False)
        state = _state("how do i save for a bike")
        state.update(await gate(state) or {})

        assert _after_cards(state) == "classify"


class TestUnbuiltAgentsAreNotDestinations:
    """`UNBUILT` must match what is actually registered."""

    async def test_the_declaration_matches_the_registry(self):
        """Whatever has no builder after `register_all()` must be in `UNBUILT`."""
        import app.graph.main_graph as main_graph
        from app.graph.nodes.classify import UNBUILT

        main_graph.register_all()
        stubs = set(main_graph.AGENT_NAMES) - set(main_graph.AGENT_BUILDERS)

        assert stubs == set(UNBUILT), (
            f"UNBUILT says {sorted(UNBUILT)} but the registry leaves {sorted(stubs)} "
            f"on a stub. An agent with no builder must be in UNBUILT or the router "
            f"can send a reader to a placeholder; one WITH a builder must not be, "
            f"or it is unreachable."
        )

    async def test_a_stub_is_never_offered_to_the_router(self):
        """The end-to-end property, on the row that actually granted it."""
        from app.graph.nodes.classify import routable

        granted = allowed_agents("aurora", "adult", "beneficiary", user_id="u")
        assert "servicing_agent" in granted, (
            "this test is meaningless if the matrix stopped granting it"
        )
        assert "servicing_agent" not in routable(granted)
        assert routable(granted), "the row must keep something to route to"

    async def test_filtering_is_independent_of_registration_order(self):
        """`routable` must not change with what has been imported so far."""
        import app.graph.main_graph as main_graph
        from app.graph.nodes.classify import routable

        row = allowed_agents("stella", "9-12", "prospect", user_id="u")
        expected = routable(row)

        saved = dict(main_graph.AGENT_BUILDERS)
        try:
            main_graph.AGENT_BUILDERS.clear()
            assert routable(row) == expected, "an empty registry changed routing"
            main_graph.AGENT_BUILDERS.update({"qa_agent": lambda: None})
            assert routable(row) == expected, "a partial registry changed routing"
        finally:
            main_graph.AGENT_BUILDERS.clear()
            main_graph.AGENT_BUILDERS.update(saved)

        assert expected == ["qa_agent_limited", "learn_agent"]
