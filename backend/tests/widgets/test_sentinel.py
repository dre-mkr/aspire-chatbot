"""Splitting a widget out of a message, and the gate that has to do it."""

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


class TestSplitting:
    def test_prose_and_blocks_come_apart(self):
        prose, blocks = sentinel.split(f"Here is one. {WIDGET} Which would you pick?")

        assert prose == "Here is one. Which would you pick?"
        assert blocks == [WIDGET]

    def test_a_message_with_no_widget_is_returned_untouched(self):
        text = "  Saving means keeping money for later.  "
        assert sentinel.split(text) == (text, [])

    def test_several_widgets_keep_their_order(self):
        first = WIDGET
        second = WIDGET.replace("compare", "timeline")
        _, blocks = sentinel.split(f"a {first} b {second} c")
        assert blocks == [first, second]

    def test_an_unterminated_marker_is_not_a_widget(self):
        """Half a widget is not a widget. The transport has the same rule."""
        text = "Look at this ⟦widget⟧{\"kind\": \"compare\""
        prose, blocks = sentinel.split(text)
        assert blocks == []
        assert prose == text

    def test_json_spanning_lines_is_still_found(self):
        text = 'Before ⟦widget⟧{\n  "kind": "compare"\n}⟦/widget⟧ after'
        _, blocks = sentinel.split(text)
        assert len(blocks) == 1

    def test_reattach_puts_them_back(self):
        prose, blocks = sentinel.split(f"Words. {WIDGET}")
        assert sentinel.reattach(prose, blocks) == f"Words.\n\n{WIDGET}"

    def test_reattach_with_nothing_to_attach_is_the_prose(self):
        assert sentinel.reattach("Words.", []) == "Words."

    def test_count_and_strip(self):
        text = f"a {WIDGET} b"
        assert sentinel.count(text) == 1
        assert sentinel.strip(text) == "a b"
