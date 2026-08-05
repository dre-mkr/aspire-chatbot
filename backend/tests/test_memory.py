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
    """The flag alone must not switch it on.

    `load_context` reads history from Postgres. With the flag on and no database
    the agent would be handed a bare question every turn -- the conversation
    would lose its memory entirely rather than merely windowing it. So the
    decision is `flag AND database`, and a deployment without Postgres keeps the
    checkpointer it has always had.
    """
    import inspect

    from app import agent

    source = inspect.getsource(agent.build_agent)
    assert "memory_window_enabled and database_enabled()" in source


# --- the opening turn does not read history (P13-003) --------------------


@pytest.mark.anyio
async def test_an_opening_turn_does_not_read_history(monkeypatch):
    """`request.thread_id is None` means there is nothing to read, so nothing is.

    The read being skipped is a ~680 ms round trip to Neon, paid ahead of the
    model by every first-time reader, for a window that is empty by
    construction: the thread id was minted by this same request.
    """
    from app import main
    from app.schemas import ChatRequest

    def explode(*args, **kwargs):  # pragma: no cover - the point is it is unreached
        raise AssertionError("load_context was called on an opening turn")

    monkeypatch.setattr(main, "load_context", explode)

    messages = await main._prepare_messages(
        ChatRequest(message="What is ASPIRE Day?"), "freshly-minted-id"
    )
    assert [m.content for m in messages] == ["What is ASPIRE Day?"]


@pytest.mark.anyio
async def test_an_opening_turn_sends_the_question_exactly_once(monkeypatch):
    """The duplicate this removed, pinned so it cannot come back.

    `_open_conversation` writes the question to Postgres before this runs, so a
    window read would return it and `build_prompt` would then append it again --
    sending the model the same sentence twice. Measured: input_token_count on an
    opening turn roughly halved once the read was skipped.
    """
    from app import main
    from app.schemas import ChatRequest

    monkeypatch.setattr(
        main, "load_context", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )

    messages = await main._prepare_messages(
        ChatRequest(message="How do I apply?"), "freshly-minted-id"
    )
    assert sum(1 for m in messages if m.content == "How do I apply?") == 1


@pytest.mark.anyio
async def test_a_continuing_turn_still_reads_history(monkeypatch):
    """The saving must not extend to turns that actually have a past.

    Without this, "skip the read" quietly becomes "never read", and the
    assistant forgets every conversation while the latency table looks better
    than ever.
    """
    from app import main
    from app.schemas import ChatRequest

    calls: list[str] = []

    async def fake_load_context(db, conversation_id, *, window_turns):
        calls.append(conversation_id)
        return ConversationContext(recent=[_Turn(role="user", content="earlier question")])

    monkeypatch.setattr(main, "load_context", fake_load_context)

    messages = await main._prepare_messages(
        ChatRequest(message="and after that?", thread_id="existing-thread"),
        "existing-thread",
    )
    assert calls == ["existing-thread"]
    assert [m.content for m in messages] == ["earlier question", "and after that?"]


# --- the owner lookup and the window read overlap (P13-007) --------------


#: Long enough that the difference between one and two of them is unmistakable,
#: short enough that the test stays cheap.
_LEG = 0.15


@pytest.mark.anyio
async def test_the_owner_lookup_and_the_window_read_overlap(monkeypatch):
    """Two independent Neon round trips, awaited as one.

    They used to run in sequence -- `owner_id_for`, then `load_context` -- so an
    authenticated caller on a continuing turn paid both end to end before the
    model was called. Nothing links them: the lookup needs only the session token
    and the read needs only the thread id.

    Measured on the clock rather than asserted structurally, because "these two
    overlap" is a claim about time and only a clock can settle it. The structural
    half is the test below; this one would pass on any arrangement that genuinely
    overlaps and fail on any that does not, which is the property worth pinning.

    Verified to FAIL on the sequential arrangement this replaced: 2 x `_LEG`
    against the 1 x it now takes.
    """
    import asyncio
    import time

    from app import main
    from app.schemas import ChatRequest

    async def slow_history(request, thread_id):
        await asyncio.sleep(_LEG)
        return ConversationContext(recent=[_Turn(role="user", content="earlier")])

    async def slow_identity():
        await asyncio.sleep(_LEG)
        return "owner-id"

    monkeypatch.setattr(main, "_load_history", slow_history)

    # Warm tiktoken first: `_assemble_prompt` counts tokens, and the encoding is
    # fetched and cached on first use. Paying that inside the timed block would
    # be measuring the encoder, not the overlap.
    await main._prepare_messages(
        ChatRequest(message="warm the encoder", thread_id="t"), "t"
    )

    started = time.perf_counter()
    messages = await main._prepare_messages(
        ChatRequest(message="and after that?", thread_id="existing-thread"),
        "existing-thread",
        identity=slow_identity(),
    )
    elapsed = time.perf_counter() - started

    assert elapsed < _LEG * 1.8, (
        f"the two reads took {elapsed:.3f}s; one leg is {_LEG:.3f}s and two are "
        f"{_LEG * 2:.3f}s, so they are running in sequence rather than together"
    )
    # The overlap must not have cost the history it was overlapping with.
    assert [m.content for m in messages] == ["earlier", "and after that?"]


@pytest.mark.anyio
async def test_the_owner_id_reaches_the_conversation_write(monkeypatch):
    """The gather must hand the resolved id on, not drop it.

    `after_history` opens the conversation, and it is the owner id that decides
    whose history list the chat appears in. Resolving it concurrently is only
    safe if the value still arrives -- a gather that returned the id and then
    wrote the row as anonymous would look fast and lose the conversation.
    """
    import asyncio

    from app import main
    from app.schemas import ChatRequest

    async def identity():
        return "owner-42"

    seen: list = []

    async def slow_history(request, thread_id):
        await asyncio.sleep(0)
        return ConversationContext()

    monkeypatch.setattr(main, "_load_history", slow_history)

    await main._prepare_messages(
        ChatRequest(message="anything", thread_id="t-1"),
        "t-1",
        identity=identity(),
        after_history=lambda owner: seen.append(owner),
    )

    assert seen == ["owner-42"], (
        "the conversation write was handed %r instead of the resolved owner id" % seen
    )


def test_the_two_reads_are_gathered_not_sequential():
    """Structural guard, so the overlap cannot be undone by an innocent edit.

    The timing test above is the real assertion. This one names the mechanism, so
    that a refactor which splits the gather back into two awaits fails with a
    message saying what it broke rather than as an unexplained slowdown nobody
    measures again.
    """
    import inspect

    from app import main

    source = inspect.getsource(main._prepare_messages)

    assert "asyncio.gather(" in source, (
        "`_prepare_messages` no longer gathers anything: the owner lookup and the "
        "window read are two sequential Neon round trips again, and an "
        "authenticated caller pays both before the model is called"
    )

    gather = source.index("asyncio.gather(")
    assert gather < source.index("_resolved("), (
        "the owner lookup is resolved outside the gather, so it no longer overlaps "
        "the window read"
    )
    assert gather < source.index("_load_history("), (
        "the window read is outside the gather, so it no longer overlaps the owner "
        "lookup"
    )
