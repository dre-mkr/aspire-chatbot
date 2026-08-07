"""Widgets at the outbound gate.

`safety_out` measuring, rewriting and redacting a message that has a widget in
it -- without destroying the widget, and without letting the widget carry
anything past a gate.

This combination had never run. The widget pipeline was complete (nine schemas,
seven gates, a sentinel machine in the transport, a React registry) and nothing
in the graph emitted one, so no message containing a `⟦widget⟧` had ever reached
this node. The first one would have been counted as several hundred words
against a thirty-five word cap, re-prompted, and rewritten into prose.

The unit tests for the split itself are in `tests/widgets/test_sentinel.py`.
"""

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
        """The failure this whole seam exists to prevent.

        Thirty-five words is the 5-8 cap and a composed widget is a few hundred
        characters of JSON. Counted, every widget-bearing lesson turn is over
        the cap, gets re-prompted to shorten, and the model shortens it by
        deleting the widget.
        """
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
        """No gate fired, so the message is returned byte-for-byte -- the
        widget stays mid-paragraph if that is where the model put it."""
        node = so.make_safety_out(None)
        text = f"Two ways to use it. {WIDGET} Which one?"
        state = state_for(age_band="5-8", messages=[AIMessage(content=text)])

        update = await node(state)

        assert "messages" not in update or update["messages"][0].content == text

    async def test_a_rewritten_turn_keeps_its_widget_at_the_end(
        self, state_for, recorder
    ):
        """A widget that survives a rewrite is the only outcome here that is
        not a deletion, even though it has lost its position."""
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
        """The widget is lifted out; the prose is not let off.

        A banned term beside a widget is the same banned term.
        """
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
        """Not a real risk -- `widgets/schemas.py` rejects `http` in every
        string field at parse time -- and asserted anyway, because this gate is
        now the one place a widget's characters bypass a check.
        """
        node = so.make_safety_out(None)
        smuggled = '⟦widget⟧{"kind": "compare", "a11y_text": "see https://evil.example"}⟦/widget⟧'
        state = state_for(
            persona="stella",
            age_band="5-8",
            messages=[AIMessage(content=f"Look. {smuggled}")],
        )

        update = await node(state)

        # The block is carried through this gate untouched, and is then rejected
        # by `validate_widget` before it can be rendered -- gate 1 or gate 2,
        # depending on where the parse fails.
        from app.widgets.validate import validate_widget

        carried = sentinel.split(update["messages"][0].content)[1] if "messages" in update else [smuggled]
        raw = carried[0].removeprefix(sentinel.OPEN).removesuffix(sentinel.CLOSE)
        assert not validate_widget(raw, age_band="5-8", locale="en").ok


@pytest.mark.asyncio
class TestWhoMayEmitOne:
    async def test_all_three_learning_names_may(self):
        """One subgraph registered three times. A guardian preview and a
        signed-out sample are the two audiences being shown what the product is
        like, and dropping the interactive half for them is the wrong default.
        """
        from app.graph.stream_interceptor import WIDGET_AGENTS

        assert WIDGET_AGENTS == {"learn_agent", "learning_preview", "learning_sample"}

    async def test_the_chip_requirement_covers_the_same_three(self):
        """Gate (e) and the widget gate must name the same set, or a preview
        gets widgets with no way to reply to them."""
        from app.graph.stream_interceptor import WIDGET_AGENTS

        assert so.LEARNING_AGENTS == WIDGET_AGENTS
