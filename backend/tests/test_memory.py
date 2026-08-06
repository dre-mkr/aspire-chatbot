"""The rolling window, the summary, and the token accounting.

The point of the memory change is that the prompt stops growing with the
conversation. That is a measurable claim, so it is measured rather than asserted
in a comment.
"""

from dataclasses import dataclass

import pytest

from app.db.repository import ConversationContext
from app.memory import SUMMARY_PREFACE, build_prompt, count_tokens


@dataclass
class _Turn:
    """Enough of a stored Message for `build_prompt` to consume."""

    role: str
    content: str
    seq: int = 0


def turns(n: int, *, words: int = 40) -> list[_Turn]:
    body = " ".join(["saving"] * words)
    return [
        _Turn(role="user" if i % 2 == 0 else "assistant", content=f"{body} {i}", seq=i + 1)
        for i in range(n)
    ]


class TestWindow:
    def test_only_the_window_is_sent(self):
        context = ConversationContext(recent=turns(6), older_turn_count=40)
        prepared = build_prompt("and now?", context)

        # Six messages plus the new question. The forty older ones are absent.
        assert len(prepared.messages) == 7
        assert prepared.messages[-1].content == "and now?"
        assert prepared.windowed_turns == 6
        assert prepared.summarized_turns == 40

    def test_summary_is_prepended_and_framed_as_a_record(self):
        context = ConversationContext(
            summary="The user is 12 and saving for a bicycle.", recent=turns(2)
        )
        prepared = build_prompt("how much more?", context)

        first = prepared.messages[0]
        assert first.type == "system"
        assert "bicycle" in first.content
        # Framed as reference material, so a summary that happens to contain an
        # instruction is far less likely to be obeyed as one.
        assert first.content.startswith(SUMMARY_PREFACE)

    def test_no_summary_means_no_extra_message(self):
        prepared = build_prompt("hello", ConversationContext(recent=turns(2)))
        assert all(m.type != "system" for m in prepared.messages)

    def test_an_empty_context_is_just_the_question(self):
        prepared = build_prompt("hello", ConversationContext())
        assert len(prepared.messages) == 1
        assert prepared.messages[0].content == "hello"


class TestPromptCost:
    def test_prompt_size_stops_growing_with_the_conversation(self):
        """The whole point of the change, stated as an assertion."""
        short = build_prompt("q", ConversationContext(recent=turns(6)))
        long_thread = build_prompt(
            "q", ConversationContext(recent=turns(6), older_turn_count=200)
        )
        # A 200-message thread costs the same as a 6-message one.
        assert short.tokens == long_thread.tokens

    def test_measured_saving_against_full_history(self):
        everything = [(t.role, t.content) for t in turns(60)]
        window = ConversationContext(recent=turns(60)[-6:], older_turn_count=54)

        prepared = build_prompt("q", window, full_history=everything)

        assert prepared.tokens < prepared.tokens_if_full_history
        # At sixty messages with a window of six the drop should be substantial,
        # not marginal -- if it is not, the change is not worth making.
        assert prepared.saved_percent > 80

    def test_saving_is_zero_when_nothing_was_dropped(self):
        context = ConversationContext(recent=turns(4))
        history = [(t.role, t.content) for t in turns(4)]
        prepared = build_prompt("q", context, full_history=history)
        assert prepared.saved == 0
        assert prepared.saved_percent == 0.0

    def test_token_count_is_not_a_character_count(self):
        # Guards the accounting itself: a broken encoder returning len() would
        # make every before/after number meaningless.
        text = "the quick brown fox jumps over the lazy dog"
        assert 0 < count_tokens(text) < len(text)


@pytest.mark.parametrize("role,expected", [("assistant", "ai"), ("user", "human")])
def test_roles_round_trip_to_message_types(role, expected):
    context = ConversationContext(recent=[_Turn(role=role, content="x", seq=1)])
    assert build_prompt("q", context).messages[0].type == expected


def test_the_window_is_on_by_default():
    """It was opt-in while nothing ran the job that backs it.

    With the window off, the InMemorySaver replays the whole thread -- including
    every prior turn's retrieved chunks -- into every request, so cost grows
    quadratically with conversation length and the process never releases a
    conversation. That was still the safer default while no arq worker existed
    to fold older turns into a summary: turns falling out of the window would
    simply have been forgotten.

    deploy/aspire-worker.service now runs that worker, so the window is the
    better default and this asserts the flip deliberately rather than letting it
    happen by accident.
    """
    from app.config import Settings

    assert Settings().memory_window_enabled is True


def test_the_window_requires_a_database():
    """The flag alone must not switch summarisation on.

    This used to read `agent.build_agent`'s source, because that was where the
    `flag AND database` decision lived. `build_agent` is gone; the rule moved to
    `turn.summarisation_wanted`, which is the one place that now acts on it --
    with the flag on and no Postgres there is no checkpoint for a thread to live
    in, so there is nothing to summarise FROM and the work would be a model call
    against an empty state.
    """
    import inspect

    from app import turn

    source = inspect.getsource(turn.summarisation_wanted)
    assert "memory_window_enabled and database_enabled()" in source


# --- what replaced the window read (P13-003, P13-007) ----------------------
#
# Five tests stood here. Each asserted a property of `main._prepare_messages`:
# that an opening turn skipped the ~680 ms `load_context` round trip, that a
# continuing turn still made it, and that it overlapped with the owner lookup
# rather than queueing behind it.
#
# None of them can be repointed, because the thing they optimised is gone. The
# graph does not assemble a prompt from a Postgres window -- `AsyncPostgresSaver`
# holds the thread and langgraph loads it, so there is no request-path history
# read left to skip, to overlap, or to make twice. The 680 ms is not saved; it
# is not spent.
#
# `build_prompt` and `load_context` survive, unused by the request path, and the
# tests above still exercise them. What they are FOR has narrowed twice, and the
# note here has to keep up or it becomes the reason nobody removes them:
#
#   * not the summary worker -- that job is deleted (`app/jobs.py`). The rolling
#     summary lives in the checkpoint and `turn.summarise_thread` writes it.
#   * not the transcript export -- that is client-side, in `lib/aspire/export.ts`.
#
# What is left is `scripts/measure_prompt_tokens.py`, which is the tooling behind
# the prompt-cost numbers in `docs/latency-baseline.md`, plus the window
# arithmetic they encode, which is the reasoning the graph's own
# `SUMMARY_AFTER_MESSAGES` inherited. `load_context` itself has no caller at all.
#
# What IS still asserted, and where:
#
#   the question is recorded before it is answered
#       -> tests/test_p1_regressions.py::test_open_conversation_records_the_question
#   the write is in flight before the graph runs
#       -> tests/test_p1_regressions.py::test_the_stream_starts_the_conversation_write_before_the_graph
#   PII never reaches the summary
#       -> tests/safety/ and the two below


@pytest.mark.anyio
async def test_a_short_thread_is_not_summarised(monkeypatch):
    """Compression is a model call, and a twelve-message thread does not need it."""
    from app import turn as turn_service

    class _Graph:
        # Present because `summarise_thread` refuses to read state back from a
        # graph compiled without one -- a supported configuration, and how every
        # subgraph test and the eval harness run.
        checkpointer = object()

        async def aget_state(self, config):
            return type("S", (), {"values": {"messages": [_Turn(role="user", content="hi")] * 3}})()

        async def aupdate_state(self, config, values):  # pragma: no cover
            raise AssertionError("a short thread must not be summarised")

    monkeypatch.setattr(turn_service, "summarisation_wanted", lambda: True)
    assert await turn_service.summarise_thread(_Graph(), {}) is False


@pytest.mark.anyio
async def test_the_summariser_never_sees_unredacted_text(monkeypatch):
    """Redaction runs BEFORE the model, not on its output.

    A date of birth that reaches a summary is a date of birth in every future
    prompt on that thread, forever. Summarising first and redacting the result
    would mean the value had already been sent -- the exact thing being
    prevented, arrived at one step too late.
    """
    from langchain_core.messages import HumanMessage

    from app import turn as turn_service

    seen: list[str] = []

    async def _fake_summarise(turns, previous):
        seen.extend(content for _role, content in turns)
        return "a summary"

    written: dict = {}

    class _Graph:
        checkpointer = object()

        async def aget_state(self, config):
            messages = [
                HumanMessage(content="my date of birth is 2014-03-02")
            ] + [HumanMessage(content=f"turn {i}") for i in range(20)]
            return type("S", (), {"values": {"messages": messages, "summary": ""}})()

        async def aupdate_state(self, config, values):
            written.update(values)

    monkeypatch.setattr(turn_service, "summarisation_wanted", lambda: True)
    monkeypatch.setattr(
        "app.agent.summarise_conversation", _fake_summarise, raising=True
    )

    assert await turn_service.summarise_thread(_Graph(), {}) is True
    assert written["summary"] == "a summary"
    assert seen, "the summariser was never called"
    assert not any("2014-03-02" in line for line in seen), (
        "a date of birth reached the summariser unredacted"
    )
