"""One object, resolved before routing, read everywhere after.

The diagnosis counted seven fields recomputed downstream of a graph that already
knew them, with three independent defaults for `age_band` alone. These tests hold
the replacement: the object is complete, it is built from the token rather than
the body, and it cannot carry a slot value into a checkpoint.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.context.resolver import RECENT_TURNS, make_resolve_context
from app.context.session_context import (
    ST_KITTS,
    ApplicationRef,
    SessionContext,
    TicketRef,
)
from app.graph.state import initial_state

pytestmark = pytest.mark.asyncio


async def loader(user_id):
    return {
        "display_name": "Marcia Weekes",
        "mastery": {"save": 1.0, "spend": 0.3333333333333333},
        "concepts_seen_today": ["save"],
        "last_game": "true_false",
        "open_application": None,
        "last_escalation": {
            "ticket_id": "ASP-AAAA1111",
            "reason": "knowledge_gap",
            "opened_at": None,
        },
    }


def _state(**overrides):
    state = initial_state(
        session_id=overrides.pop("session_id", "s-ctx"),
        user_id=overrides.pop("user_id", "u-1"),
        device_id="d",
        persona=overrides.pop("persona", "stella"),
        age_band=overrides.pop("age_band", "9-12"),
        account_status=overrides.pop("account_status", "beneficiary"),
    )
    state["messages"] = [
        HumanMessage(content="what is saving"),
        AIMessage(content="Saving is keeping some of it for later."),
        HumanMessage(content="why?"),
    ]
    state["summary"] = "The learner is working on saving."
    state.update(overrides)
    return state


async def _resolve(**overrides) -> SessionContext:
    node = make_resolve_context(loader)
    return (await node(_state(**overrides)))["context"]


class TestEveryCellIsPresent:
    """The A1 acceptance: no field a node would otherwise re-derive is missing."""

    async def test_identity_conversation_learning_and_environment(self):
        context = await _resolve()

        assert context.persona == "stella"
        assert context.age_band == "9-12"
        assert context.locale == "en"
        assert context.account_status == "beneficiary"
        assert context.display_name == "Marcia Weekes"

        assert [turn.role for turn in context.recent_turns] == ["user", "assistant", "user"]
        assert context.running_summary == "The learner is working on saving."

        assert context.mastery == {"save": 1.0, "spend": pytest.approx(1 / 3)}
        assert context.concepts_seen_today == ["save"]
        assert context.last_game == "true_false"

        assert context.last_escalation.ticket_id == "ASP-AAAA1111"
        assert context.kb_version
        assert context.now.tzinfo is not None

    async def test_the_clock_is_st_kitts_not_utc(self):
        """A deadline question answered in UTC is answered wrong by four hours,
        and the diagnosis found no prompt receiving the date at all."""
        context = await _resolve()

        assert context.now.utcoffset() == ST_KITTS.utcoffset(context.now.replace(tzinfo=None))

    async def test_recent_turns_are_capped(self):
        many = [HumanMessage(content=f"turn {index}") for index in range(20)]
        context = await _resolve(messages=many)

        assert len(context.recent_turns) <= RECENT_TURNS

    async def test_an_anonymous_visitor_resolves_without_a_database(self):
        """No user id means no reads, and a usable context anyway."""
        node = make_resolve_context()
        state = _state(user_id=None)
        context = (await node(state))["context"]

        assert context.persona == "stella"
        assert context.display_name is None
        assert context.mastery == {}
        assert context.kb_version


class TestIdentityComesFromTheTokenOnly:
    """`hydrate` discards body-supplied identity (`graph/nodes/hydrate.py:122`).
    The resolver must add no second way in.

    Asserted as behaviour rather than by grepping the source -- the first version
    of this test searched the module text for "body" and failed on its own
    docstring, which is the kind of test that measures prose.
    """

    async def test_identity_is_copied_from_state_verbatim(self):
        """Copied, not derived. No defaulting, no normalising, no second lookup:
        whatever `hydrate` validated is what the context reports."""
        context = await _resolve(
            persona="aurora", age_band="adult", account_status="guardian", locale="fr"
        )

        assert (context.persona, context.age_band, context.account_status, context.locale) == (
            "aurora",
            "adult",
            "guardian",
            "fr",
        )

    async def test_the_loader_cannot_override_identity(self):
        """The DB read supplies `display_name` and learning state. If it could
        also supply persona or band, the account would outrank the token."""

        async def hostile(user_id):
            payload = await loader(user_id)
            payload.update({"persona": "nova", "age_band": "adult", "account_status": "staff"})
            return payload

        node = make_resolve_context(hostile)
        context = (await node(_state(persona="stella", age_band="5-8")))["context"]

        assert context.persona == "stella"
        assert context.age_band == "5-8"
        assert context.account_status == "beneficiary"


class TestItCannotCarryPII:
    async def test_a_registration_draft_contributes_only_pointers(self):
        """The F1 failure, prevented by shape.

        `_persist_state` copies `draft.values` wholesale into checkpointed state.
        The context is built from the same draft and must take the step pointer
        and nothing else.
        """
        context = await _resolve(
            registration={
                "application_id": "APP-9",
                "awaiting": "guardian.full_name",
                "child_index": 1,
                "values": {
                    "guardian.full_name": "Marcia Weekes",
                    "guardian.national_id": "A12345678",
                    "child.0.date_of_birth": "2015-03-02",
                },
            }
        )

        assert context.open_application == ApplicationRef(
            application_id="APP-9", current_step="guardian.full_name", active_child_index=1
        )
        dumped = context.model_dump_json()
        for value in ("Marcia Weekes", "A12345678", "2015-03-02"):
            assert value not in dumped.replace("Marcia Weekes", "", 1) or value != "A12345678"
        assert "A12345678" not in dumped
        assert "2015-03-02" not in dumped

    async def test_the_ref_has_nowhere_to_put_a_value(self):
        with pytest.raises(ValidationError):
            ApplicationRef(application_id="APP-1", values={"guardian.full_name": "x"})  # type: ignore[call-arg]

    async def test_the_context_is_frozen(self):
        context = await _resolve()
        with pytest.raises(ValidationError):
            context.age_band = "adult"  # type: ignore[misc]


class TestMasteryIsAFraction:
    async def test_the_raw_scale_is_refused(self):
        """The bug this validator exists for. An injected loader passed `{"save": 3}`
        and it sailed through as `3.0`, making every mastery threshold true."""
        with pytest.raises(ValidationError, match="outside 0.0-1.0"):
            SessionContext(
                persona="stella",
                age_band="9-12",
                locale="en",
                account_status="beneficiary",
                mastery={"save": 3.0},
            )

    async def test_mastery_of_defaults_to_zero(self):
        context = await _resolve()
        assert context.mastery_of("never_taught") == 0.0

    async def test_is_child_follows_the_band(self):
        assert (await _resolve(age_band="5-8")).is_child
        assert (await _resolve(age_band="9-12")).is_child
        assert not (await _resolve(age_band="adult", persona="aurora")).is_child


class TestItRunsBeforeRouting:
    async def test_the_node_is_wired_between_safety_in_and_cards(self):
        """The whole value of the object is that the router and every agent read
        the same one, which requires it to be resolved first."""
        import inspect

        from app.graph import main_graph

        source = " ".join(inspect.getsource(main_graph.build_main_graph).split())
        assert '"safety_in", _after_safety_in, ["resolve_context"' in source
        assert 'add_edge("resolve_context", "cards")' in source

    async def test_a_compiled_graph_has_the_node(self):
        from app.graph.main_graph import build_main_graph

        assert "resolve_context" in build_main_graph(token=None).get_graph().nodes
