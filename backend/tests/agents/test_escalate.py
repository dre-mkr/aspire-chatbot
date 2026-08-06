"""Escalation: triage, redaction, and the rule about children.

The two acceptance criteria for G1 are here by name: an out-of-KB question
produces a ticket with a redacted summary and a clear user-facing message, and
a distress signal produces a high-priority ticket plus a guardian notification.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.agents.escalate import graph as esc  # noqa: E402
from app.graph.state import initial_state  # noqa: E402


def state_for(**overrides):
    state = initial_state(
        session_id="s-esc",
        user_id=overrides.pop("user_id", "u-esc"),
        device_id="d",
        persona=overrides.pop("persona", "stella"),
        age_band=overrides.pop("age_band", "9-12"),
        account_status="beneficiary",
        locale=overrides.pop("locale", "en"),
    )
    state["messages"] = overrides.pop(
        "messages", [HumanMessage(content="I need help with this")]
    )
    state.update(overrides)
    return state


class Recorder:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def __call__(self, row: dict) -> None:
        self.rows.append(row)


class TestTriage:
    def test_a_safeguarding_flag_is_high_and_notifies_the_guardian(self):
        """The acceptance case."""
        decision = esc.triage(state_for(safety_flags={"safeguarding": True}))
        assert decision.priority == "high"
        assert decision.category == "safeguarding"
        assert decision.notify_guardian is True

    def test_distress_is_high_for_a_child(self):
        decision = esc.triage(state_for(safety_flags={"distress": True}))
        assert decision.priority == "high"
        assert decision.notify_guardian is True

    def test_an_adult_in_distress_is_high_without_a_guardian_notification(self):
        """There is no guardian record to notify, and inventing one would be
        telling somebody's next of kin about their mental health."""
        decision = esc.triage(
            state_for(persona="aurora", age_band="adult", safety_flags={"distress": True})
        )
        assert decision.priority == "high"
        assert decision.notify_guardian is False

    def test_safeguarding_wins_over_every_other_reason(self):
        decision = esc.triage(
            state_for(
                escalation_reason="no_context",
                safety_flags={"safeguarding": True, "distress": True},
            )
        )
        assert decision.category == "safeguarding"

    @pytest.mark.parametrize(
        ("reason", "priority", "category"),
        [
            ("no_context", "normal", "knowledge_gap"),
            ("below_relevance_floor", "normal", "knowledge_gap"),
            ("unattributed_figure", "normal", "accuracy"),
            ("uncited_policy_claim", "normal", "accuracy"),
            ("user_request", "normal", "general"),
            ("repeated_clarification", "normal", "comprehension"),
            ("complaint", "high", "complaint"),
        ],
    )
    def test_each_reason_triages_the_same_way_every_time(self, reason, priority, category):
        decision = esc.triage(state_for(escalation_reason=reason))
        assert (decision.priority, decision.category) == (priority, category)

    def test_an_unknown_reason_does_not_raise(self):
        assert esc.triage(state_for(escalation_reason="something new")).priority == "normal"


class TestRedaction:
    def test_the_summary_never_carries_a_value(self):
        state = state_for(
            messages=[
                HumanMessage(content="My son's ID is A12345678, born 14/03/2015"),
                AIMessage(content="Let me pass this on."),
            ]
        )
        summary = esc.summarise(state)["escalation_summary"]
        assert "A12345678" not in summary
        assert "14/03/2015" not in summary
        assert "[collected: national_id]" in summary

    def test_a_summary_written_upstream_is_not_rewritten(self):
        """The QA agent redacts at the point of escalating; doing it twice would
        turn `[collected: email]` into a second pass over nothing."""
        state = state_for(escalation_summary="already done")
        assert esc.summarise(state) == {}

    @pytest.mark.asyncio
    async def test_a_leaked_value_is_caught_at_the_table_boundary(self, caplog):
        """The last check before a row that gets exported.

        Every writer redacts. This asserts what happens when one does not,
        because a ticket table is joined to case records and read by people.
        """
        recorder = Recorder()
        state = state_for(escalation_summary="call me on 869-555-0123")
        with caplog.at_level("ERROR"):
            await esc.make_open_ticket(recorder)(state)

        assert "869-555-0123" not in recorder.rows[0]["summary"]
        assert "reached a ticket summary" in caplog.text


@pytest.mark.asyncio
class TestTheTicket:
    async def test_an_out_of_kb_question_produces_a_redacted_ticket(self):
        """The acceptance case."""
        recorder = Recorder()
        graph = esc.build_escalate_graph(persist=recorder)
        state = state_for(
            persona="aurora",
            age_band="adult",
            escalation_reason="no_context",
            messages=[
                HumanMessage(content="Can I use my ID A12345678 to open this?"),
            ],
        )

        result = await graph.ainvoke(state)

        assert len(recorder.rows) == 1
        row = recorder.rows[0]
        assert row["category"] == "knowledge_gap"
        assert "A12345678" not in row["summary"]
        assert row["id"].startswith("ASP-")
        assert row["id"] in result["messages"][-1].content

    async def test_a_distress_signal_produces_a_high_ticket_and_a_notification(self):
        """The acceptance case."""
        recorder = Recorder()
        graph = esc.build_escalate_graph(persist=recorder)
        state = state_for(safety_flags={"distress": True})

        await graph.ainvoke(state)

        row = recorder.rows[0]
        assert row["priority"] == "high"
        assert row["notify_guardian"] is True

    async def test_a_persistence_failure_still_serves_the_escalation(self):
        """The user is the one who needs a person. Losing the row is our problem."""

        async def broken(row):
            raise RuntimeError("Postgres is down")

        graph = esc.build_escalate_graph(persist=broken)
        result = await graph.ainvoke(state_for(persona="aurora", age_band="adult"))
        assert result["escalation_ticket"].startswith("ASP-")
        assert result["messages"][-1].content


@pytest.mark.asyncio
class TestWhatTheUserIsTold:
    async def test_a_child_is_never_given_an_external_channel(self):
        """The rule this agent exists to hold.

        An external channel is unmonitored, unlogged and unbounded. Offering one
        to a child in difficulty is worse than offering nothing.
        """
        graph = esc.build_escalate_graph()
        result = await graph.ainvoke(state_for(safety_flags={"safeguarding": True}))
        text = result["messages"][-1].content

        for leak in ("@", "http", "call ", "phone", "869", "email"):
            assert leak not in text.lower()
        assert "grown-up" in text

    async def test_a_child_is_told_they_have_done_nothing_wrong(self):
        graph = esc.build_escalate_graph()
        result = await graph.ainvoke(state_for(safety_flags={"safeguarding": True}))
        assert "not done anything wrong" in result["messages"][-1].content

    async def test_a_child_is_not_given_a_reference_number_to_remember(self):
        """A nine-year-old has no use for a ticket id and will read it as a test."""
        graph = esc.build_escalate_graph()
        result = await graph.ainvoke(state_for())
        assert "ASP-" not in result["messages"][-1].content

    async def test_an_adult_gets_the_reference_and_a_realistic_window(self):
        graph = esc.build_escalate_graph()
        result = await graph.ainvoke(state_for(persona="aurora", age_band="adult"))
        text = result["messages"][-1].content
        assert result["escalation_ticket"] in text
        assert "working day" in text

    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    async def test_every_locale_has_copy(self, locale):
        graph = esc.build_escalate_graph()
        child = await graph.ainvoke(state_for(locale=locale))
        adult = await graph.ainvoke(
            state_for(persona="aurora", age_band="adult", locale=locale)
        )
        assert child["messages"][-1].content == esc._CHILD_MESSAGE[locale]
        assert adult["messages"][-1].content.startswith(
            esc._ADULT_MESSAGE[locale].split("{")[0]
        )

    async def test_the_escalated_directive_carries_the_reference(self):
        """A reference a person has to copy out of prose is one they get wrong."""
        graph = esc.build_escalate_graph()
        result = await graph.ainvoke(state_for(persona="aurora", age_band="adult"))
        directive = result["ui_directives"][0]
        assert directive.t == "escalated"
        assert directive.ticket_id == result["escalation_ticket"]

    async def test_the_turn_is_not_a_dead_end(self):
        graph = esc.build_escalate_graph()
        result = await graph.ainvoke(state_for())
        assert 1 <= len(result["quick_replies"]) <= 4
