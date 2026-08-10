"""The sentinel machine, driven at every chunk boundary that could break it."""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from langchain_core.messages import AIMessage  # noqa: E402

from app.graph.stream_interceptor import (  # noqa: E402
    CLOSE,
    OPEN,
    StreamInterceptor,
    WireEvent,
)

GROWTH_STACK = {
    "kind": "growth_stack",
    "v": 1,
    "concept_id": "interest",
    "title": "Watch it grow",
    "a11y_text": "Two stacks of coins. One is what you saved. The other is what the bank added.",
    "principal_cents": 5_000,
    "contribution_cents": 500,
    "rate": 0.05,
    "periods": 5,
    "reveal_line": "You did not work for that extra money.",
}


def widget_block(payload: dict | str = None) -> str:
    body = payload if isinstance(payload, str) else json.dumps(payload or GROWTH_STACK)
    return f"{OPEN}{body}{CLOSE}"


def interceptor(**overrides) -> StreamInterceptor:
    defaults = {"active_agent": "learn_agent", "age_band": "9-12", "locale": "en"}
    defaults.update(overrides)
    return StreamInterceptor(**defaults)


def drain(machine: StreamInterceptor, text: str, chunk_size: int) -> list[WireEvent]:
    """Feed `text` in fixed-size pieces, then flush."""
    events: list[WireEvent] = []
    for start in range(0, len(text), chunk_size):
        events.extend(machine.feed(text[start : start + chunk_size]))
    events.extend(machine.flush())
    return events


def prose_of(events: list[WireEvent]) -> str:
    return "".join(event.data["t"] for event in events if event.event == "token")


def directives_of(events: list[WireEvent]) -> list[dict]:
    return [event.data["d"] for event in events if event.event == "directive"]


class TestTheHappyPath:
    """The acceptance case: prose, one widget event, prose."""

    @pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 7, 11, 40, 1000])
    def test_prose_then_widget_then_prose_at_every_chunking(self, chunk_size):
        stream = f"Here is how it grows.{widget_block()} Try moving it."
        events = drain(interceptor(), stream, chunk_size)

        assert prose_of(events) == "Here is how it grows. Try moving it."
        directives = directives_of(events)
        assert len(directives) == 1
        assert directives[0]["t"] == "widget"
        assert directives[0]["payload"]["kind"] == "growth_stack"

    def test_ordinals_are_monotonic_and_gapless(self):
        events = drain(
            interceptor(), f"a{widget_block()}b{widget_block()}c", 3
        )
        ordinals = [event.data["i"] for event in events]
        assert ordinals == list(range(1, len(ordinals) + 1))

    def test_the_widget_sits_between_the_prose_that_surrounded_it(self):
        """Position is the whole reason the ordinal exists."""
        events = drain(interceptor(), f"before{widget_block()}after", 4)
        at = next(index for index, event in enumerate(events) if event.event == "directive")
        assert prose_of(events[:at]) == "before"
        assert prose_of(events[at + 1 :]) == "after"

    @pytest.mark.parametrize("split", range(1, 60))
    def test_no_split_point_leaks_a_bracket(self, split):
        """Rule 1, exhaustively."""
        stream = f"Look here.{widget_block()}Done."
        machine = interceptor()
        events = machine.feed(stream[:split]) + machine.feed(stream[split:])
        events.extend(machine.flush())
        text = prose_of(events)
        assert "⟦" not in text and "⟧" not in text
        assert "growth_stack" not in text


class TestPartialsAreNeverForwarded:
    def test_a_lone_partial_sentinel_is_held_until_it_resolves(self):
        """Only the ambiguous tail is held."""
        machine = interceptor()
        first = machine.feed("Hello ⟦wid")
        assert prose_of(first) == "Hello "

        events = machine.feed("get⟧" + json.dumps(GROWTH_STACK) + CLOSE)
        assert prose_of(events) == ""
        assert len(directives_of(events)) == 1

    def test_a_bracket_that_cannot_become_a_sentinel_is_shown_at_once(self):
        """Held is a last resort, not a policy."""
        machine = interceptor()
        assert "⟦" in prose_of(machine.feed("The bracket ⟦ is just a bracket"))

    def test_an_ambiguous_tail_at_the_end_of_a_turn_is_released_not_dropped(self):
        """Held is not dropped. If the turn ends, it was text after all."""
        machine = interceptor()
        held = machine.feed("Almost a sentinel ⟦widge")
        assert "⟦" not in prose_of(held)
        assert prose_of(held + machine.flush()) == "Almost a sentinel ⟦widge"

    def test_widget_json_never_reaches_the_client(self):
        """Rule 2, at the most hostile chunking available."""
        events = drain(interceptor(), f"x{widget_block()}y", 1)
        text = prose_of(events)
        assert "principal_cents" not in text
        assert "{" not in text


class TestFailuresAreSilent:
    def test_malformed_json_produces_prose_only_and_a_logged_gate(self, caplog):
        """The acceptance case. A gate failure is never shown to a child."""
        stream = f"Before{widget_block('{not json at all')}After"
        with caplog.at_level("INFO"):
            events = drain(interceptor(), stream, 6)

        assert prose_of(events) == "BeforeAfter"
        assert directives_of(events) == []
        assert "parse" in caplog.text

    def test_an_unknown_kind_fails_at_gate_one(self, caplog):
        block = widget_block({"kind": "hologram", "v": 1})
        with caplog.at_level("INFO"):
            events = drain(interceptor(), block, 9)
        assert directives_of(events) == []
        assert "unknown kind" in caplog.text

    def test_a_schema_failure_is_gate_two(self, caplog):
        broken = dict(GROWTH_STACK)
        broken.pop("a11y_text")
        with caplog.at_level("INFO"):
            events = drain(interceptor(), widget_block(broken), 20)
        assert directives_of(events) == []
        assert "a11y_text" in caplog.text

    def test_markup_inside_a_widget_is_refused(self):
        """The string rule, from the transport's point of view."""
        hostile = dict(GROWTH_STACK, title="<img src=x onerror=alert(1)>")
        events = drain(interceptor(), widget_block(hostile), 30)
        assert directives_of(events) == []

    def test_a_literal_colour_is_refused(self):
        hostile = dict(GROWTH_STACK, reveal_line="Look at the #ff0000 stack")
        assert directives_of(drain(interceptor(), widget_block(hostile), 30)) == []

    def test_a_gate_failure_leaves_the_stream_running(self):
        stream = f"one{widget_block('nonsense')}two{widget_block()}three"
        events = drain(interceptor(), stream, 5)
        assert prose_of(events) == "onetwothree"
        assert len(directives_of(events)) == 1


class TestUnterminatedSentinels:
    def test_an_unterminated_block_does_not_hang_the_stream(self):
        """Rule 4, the version that ends with the turn."""
        machine = interceptor()
        events = machine.feed(f"Here it is{OPEN}" + '{"kind":"growth_stack"')
        events.extend(machine.flush())
        assert prose_of(events) == "Here it is"
        assert directives_of(events) == []

    def test_the_buffer_cap_releases_the_stream(self, monkeypatch):
        """A model that opens a block and never closes it costs one widget."""
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "widget_buffer_limit_bytes", 512)
        machine = interceptor()
        machine.feed(OPEN)
        machine.feed("x" * 600)
        # The block was abandoned, so ordinary prose flows again.
        events = machine.feed(" and we carry on")
        assert prose_of(events) == " and we carry on"
        assert machine.stats()["gate_failures"]["unterminated"] == 1

    def test_a_close_with_no_open_is_ordinary_text(self):
        """Nothing was buffered, so there is nothing to close and nothing to fix."""
        events = drain(interceptor(), f"a{CLOSE}b", 3)
        assert CLOSE in prose_of(events)


class TestOnlyTheLearningAgentEmitsWidgets:
    @pytest.mark.parametrize(
        "agent", ["qa_agent", "register_agent", "escalate_agent", "servicing_agent", None]
    )
    def test_a_widget_from_another_agent_is_dropped(self, agent, caplog):
        with caplog.at_level("WARNING"):
            events = drain(
                interceptor(active_agent=agent), f"x{widget_block()}y", 8
            )
        assert directives_of(events) == []
        assert prose_of(events) == "xy"
        assert "widgets are for" in caplog.text

    @pytest.mark.parametrize(
        "agent", ["learn_agent", "learning_preview", "learning_sample"]
    )
    def test_every_learning_name_may(self, agent):
        """One subgraph, registered three times, all three able to emit."""
        events = drain(interceptor(active_agent=agent), widget_block(), 8)
        assert len(directives_of(events)) == 1


@pytest.mark.asyncio
class TestTwoSpeakersInOneTurn:
    """`teach` explains and `check` asks, both in one turn, each its own message."""

    async def _say(self, machine, node, *chunks):
        events = []
        for chunk in chunks:
            events += await machine.process(
                ("messages", (AIMessage(content=chunk), {"langgraph_node": node}))
            )
        return events

    def _prose(self, events):
        return "".join(e.data["t"] for e in events if e.event == "token")

    async def test_a_new_speaker_starts_a_new_paragraph(self):
        machine = interceptor()
        events = await self._say(machine, "teach", "Money kept is money later.")
        events += await self._say(machine, "check", "What is that?")

        assert self._prose(events) == "Money kept is money later.\n\nWhat is that?"

    async def test_one_node_streaming_is_never_broken_up(self):
        """The chunk case."""
        machine = interceptor()
        events = await self._say(machine, "teach", "Saving ", "means ", "keeping ", "money.")

        assert self._prose(events) == "Saving means keeping money."

    async def test_the_persisted_reply_matches_what_was_read(self):
        """`prose` is what the turn is stored as."""
        machine = interceptor()
        await self._say(machine, "teach", "Money kept is money later.")
        await self._say(machine, "check", "What is that?")

        assert machine.prose == "Money kept is money later.\n\nWhat is that?"

    async def test_no_leading_break_before_the_first_speaker(self):
        machine = interceptor()
        events = await self._say(machine, "teach", "Money kept is money later.")
        assert self._prose(events) == "Money kept is money later."

    async def test_a_node_that_ended_its_own_paragraph_is_not_doubled(self):
        machine = interceptor()
        events = await self._say(machine, "teach", "Money kept is money later.\n")
        events += await self._say(machine, "check", "What is that?")

        assert "\n\n\n" not in self._prose(events)

    async def test_a_widget_is_not_split_by_a_node_change(self):
        """A break inserted between the sentinels would corrupt the JSON."""
        machine = interceptor()
        await self._say(machine, "teach", f"Look at this {OPEN}")
        events = await self._say(machine, "check", '{"kind":"compare"}')

        assert "\n\n" not in self._prose(events)


class TestBandEnforcement:
    def test_a_simulator_is_refused_at_five_to_eight(self):
        """Gate 3. The band with no simulators at all."""
        simulator = {
            "kind": "simulator",
            "v": 1,
            "concept_id": "save",
            "title": "Try it",
            "a11y_text": "A slider that changes how much you put away.",
            "controls": [
                {
                    "id": "weekly",
                    "label": "Each week",
                    "unit": "xcd_cents",
                    "min": 100,
                    "max": 2000,
                    "default": 500,
                    "step": 100,
                }
            ],
            "formula": "savings_goal_time",
            "output_label": "Weeks to go",
        }
        assert directives_of(drain(interceptor(age_band="5-8"), widget_block(simulator), 30)) == []

    def test_a_growth_stack_is_refused_at_five_to_eight_and_allowed_at_nine_to_twelve(self):
        assert directives_of(drain(interceptor(age_band="5-8"), widget_block(), 30)) == []
        assert len(directives_of(drain(interceptor(age_band="9-12"), widget_block(), 30))) == 1


class TestDisabledWidgets:
    def test_sentinels_are_inert_text_when_widgets_are_off(self):
        """A deployment with WIDGETS_ENABLED=false shows the characters."""
        machine = interceptor(widgets_enabled=False)
        events = machine.feed(f"a{OPEN}b")
        assert OPEN in prose_of(events)
        assert directives_of(events) == []


class TestOtherEvents:
    def test_a_custom_directive_from_the_graph_gets_the_next_ordinal(self):
        machine = interceptor()
        first = machine.feed("hello")
        second = machine._on_custom({"directive": {"t": "quick_replies", "options": []}})
        assert second[0].data["i"] == first[0].data["i"] + 1

    def test_an_error_event_does_not_consume_an_ordinal(self):
        """The ordinal sequence describes content; an error is why there is no more."""
        machine = interceptor()
        machine.feed("hello")
        before = machine.stats()["events"]
        machine.error("upstream", "provider failed")
        assert machine.stats()["events"] == before

    def test_the_wire_format_is_sse(self):
        encoded = WireEvent("token", {"i": 1, "t": "hi"}).encode()
        assert encoded == 'event: token\ndata: {"i":1,"t":"hi"}\n\n'

    def test_non_ascii_survives_encoding(self):
        """EC$ and accented text are UTF-8, not escapes."""
        encoded = WireEvent("token", {"i": 1, "t": "l'année EC$5"}).encode()
        assert "l'année" in encoded and "EC$5" in encoded

    def test_unknown_stream_modes_are_ignored_rather_than_raised_on(self):
        import asyncio

        machine = interceptor()
        assert asyncio.run(machine.process(("values", {"anything": 1}))) == []
        assert asyncio.run(machine.process("not a tuple")) == []
