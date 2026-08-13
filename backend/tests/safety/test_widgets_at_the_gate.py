"""Widgets at the outbound gate."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from app.graph.nodes import safety_out as so
from app.widgets import sentinel

WIDGET = (
    '⟦widget⟧{"v": 1, "kind": "compare", "a11y_text": "Two ways to use five '
    'dollars", "panels": [{"label": "Spend", "reveal": "It is gone"}, '
    '{"label": "Save", "reveal": "You still have it"}]}⟦/widget⟧'
)


@pytest.mark.asyncio
class TestTheOutboundGateWithAWidget:
    async def test_widget_json_is_not_counted_against_the_word_cap(self, state_for):
        """The failure this whole seam exists to prevent."""
        node = so.make_safety_out(None)
        text = f"Two ways to use it. {WIDGET} Which one?"
        state = state_for(age_band="5-8", messages=[AIMessage(content=text)])

        update = await node(state)

        flags = update["safety_flags"].get("outbound", {})
        assert "length_violation" not in flags
        assert "length_truncated" not in flags

    async def test_a_clean_turn_keeps_the_widget_exactly_where_it_was(
        self, state_for
    ):
        """No gate fired, so the message is returned byte-for-byte."""
        node = so.make_safety_out(None)
        text = f"Two ways to use it. {WIDGET} Which one?"
        state = state_for(age_band="5-8", messages=[AIMessage(content=text)])

        update = await node(state)

        assert "messages" not in update or update["messages"][0].content == text

    async def test_a_rewritten_turn_keeps_its_widget_at_the_end(
        self, state_for, recorder
    ):
        """A rewrite keeps the widget, reattached at the end of the new text."""
        recorder.scripted("Money you keep is money you still have.")
        node = so.make_safety_out(recorder)
        long = " ".join(["Saving means putting money away for later"] * 8)
        state = state_for(age_band="5-8", messages=[AIMessage(content=f"{long} {WIDGET}")])

        update = await node(state)

        content = update["messages"][0].content
        assert sentinel.count(content) == 1
        assert content.endswith("⟦/widget⟧")
        assert so.word_count(sentinel.strip(content)) <= 35

    async def test_the_prose_around_a_widget_is_still_gated(self, state_for):
        """The widget is lifted out; the prose is not let off."""
        node = so.make_safety_out(None)
        state = state_for(
            age_band="9-12",
            messages=[AIMessage(content=f"This is compound interest. {WIDGET}")],
        )

        update = await node(state)

        flags = update["safety_flags"]["outbound"]
        assert "compound" in " ".join(flags.get("vocab_violations", []))
        assert sentinel.count(update["messages"][0].content) == 1

    async def test_pii_beside_a_widget_is_still_redacted(self, state_for):
        node = so.make_safety_out(None)
        state = state_for(
            age_band="adult",
            messages=[AIMessage(content=f"Call 869-555-0147 about it. {WIDGET}")],
        )

        update = await node(state)

        assert "pii_redacted" in update["safety_flags"]["outbound"]
        assert "869-555-0147" not in update["messages"][0].content

    async def test_the_carried_count_is_reported(self, state_for):
        node = so.make_safety_out(None)
        state = state_for(age_band="9-12", messages=[AIMessage(content=f"Hi. {WIDGET}")])

        update = await node(state)

        assert update["safety_flags"]["outbound"]["widgets_carried"] == 1

    async def test_a_widget_cannot_smuggle_a_link_past_the_link_gate(self, state_for):
        """The smuggled link is rejected by `validate_widget`, not by this gate."""
        node = so.make_safety_out(None)
        smuggled = '⟦widget⟧{"kind": "compare", "a11y_text": "see https://evil.example"}⟦/widget⟧'
        state = state_for(
            persona="stella",
            age_band="5-8",
            messages=[AIMessage(content=f"Look. {smuggled}")],
        )

        update = await node(state)

        # Carried through this gate untouched, then rejected by `validate_widget`.
        from app.widgets.validate import validate_widget

        carried = sentinel.split(update["messages"][0].content)[1] if "messages" in update else [smuggled]
        raw = carried[0].removeprefix(sentinel.OPEN).removesuffix(sentinel.CLOSE)
        assert not validate_widget(raw, age_band="5-8", locale="en").ok


@pytest.mark.asyncio
class TestWhoMayEmitOne:
    async def test_all_three_learning_names_may(self):
        """One subgraph registered three times."""
        from app.graph.stream_interceptor import WIDGET_AGENTS

        assert WIDGET_AGENTS == {"learn_agent", "learning_preview", "learning_sample"}

    async def test_the_chip_requirement_covers_the_same_three(self):
        """Both gates must name the same set, or a preview gets unanswerable widgets."""
        from app.graph.stream_interceptor import WIDGET_AGENTS

        assert so.LEARNING_AGENTS == WIDGET_AGENTS
