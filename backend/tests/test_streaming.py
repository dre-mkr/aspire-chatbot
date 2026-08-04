"""What goes on the wire as the answer, and what must never.

Written after `/chat/stream` spent its life streaming the retriever's output in
place of the model's answer — every turn, first message and follow-up alike.
The transport was fine, the sources were fine, the follow-ups were fine. The
wrong string was being put on the wire.

The mechanism is worth stating because it is not obvious and it inverted the
selection exactly. The emitter tested `isinstance(content, str)` and streamed
whatever passed. With this provider an assistant message's content is a LIST of
typed blocks, so that test was false for all 127 chunks of the answer, and true
for precisely one thing per turn: the ToolMessage carrying the knowledge base
rows. A guard meant to be conservative dropped the answer and admitted the
context.

So these tests are about selection, not formatting, and they use a fake agent
rather than a real one: the bug had nothing to do with the model and everything
to do with which messages the emitter believes are prose.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessageChunk, ToolMessage  # noqa: E402

from app import main  # noqa: E402
from app.main import app, message_text  # noqa: E402

#: P0-010 -- see the `slow` marker note in pyproject.toml.
pytestmark = pytest.mark.slow

#: What a retrieved row looks like once the retriever has serialised it. These
#: exact strings are what a user saw in the assistant bubble.
CONTEXT_DUMP = (
    "Category: Overview\n"
    "Question: What is the ASPIRE Programme?\n"
    "Answer: ASPIRE is a national financial education initiative.\n"
    "id: ASP-003\n"
    "subcategory: Purpose\n"
    "keywords: goal|purpose|mission|aim\n"
    "audience: general\n"
    "source_url: https://aspire.gov.kn/\n"
    "as_of: 2026-07-30"
)

#: Any of these in the visible answer means context reached the screen.
METADATA_SENTINELS = ("id: ASP-", "as_of:", "subcategory:", "keywords:", "source_url:")

ANSWER = "**ASPIRE** is a savings and investment programme for young people."


class TestMessageText:
    """The one function both readers share, so they cannot diverge again."""

    def test_a_plain_string_is_itself(self):
        assert message_text("hello") == "hello"

    def test_typed_blocks_are_joined(self):
        assert (
            message_text(
                [
                    {"type": "reasoning", "summary": []},
                    {"type": "text", "text": "one "},
                    {"type": "text", "text": "two"},
                ]
            )
            == "one two"
        )

    def test_reasoning_blocks_are_not_prose(self):
        # They carry the model's private working. Shipping it would be a leak
        # dressed up as an answer.
        assert message_text([{"type": "reasoning", "summary": ["thinking"]}]) == ""

    def test_an_unexpected_shape_is_dropped_and_logged(self, caplog):
        """Never `str()`. That is how a Document reaches a reader."""
        from langchain_core.documents import Document

        with caplog.at_level("WARNING"):
            assert message_text(Document(page_content=CONTEXT_DUMP)) == ""
        assert "not text or content blocks" in caplog.text
        assert "Document" in caplog.text

    def test_a_dict_is_dropped_too(self, caplog):
        with caplog.at_level("WARNING"):
            assert message_text({"answer": "hello"}) == ""
        assert "dict" in caplog.text


def _fake_agent(chunks):
    """An agent whose stream is exactly the chunks given."""

    class Agent:
        async def astream(self, _inputs, config=None, stream_mode=None):
            for chunk in chunks:
                yield chunk, {}

    return lambda _simple=False: Agent()


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _frames(response) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_the_streamed_answer_is_the_answer_and_not_the_context(client, monkeypatch):
    """The regression this file exists for.

    The tool call comes first, then its output, then the answer — the real
    order, because the emitter's mistake depended on it: a ToolMessage arrives
    after a tool has run, which is exactly when the buffer is willing to release.
    """
    tool_call = AIMessageChunk(
        content=[],
        tool_call_chunks=[
            {"name": "search_knowledge_base", "args": "{}", "id": "call-1", "index": 0}
        ],
        id="msg-1",
    )
    tool_result = ToolMessage(content=CONTEXT_DUMP, tool_call_id="call-1", id="msg-2")
    answer = [
        AIMessageChunk(content=[{"type": "text", "text": part}], id="msg-3")
        for part in ("**ASPIRE** is a savings ", "and investment programme ", "for young people.")
    ]

    monkeypatch.setattr(main, "get_agent", _fake_agent([tool_call, tool_result, *answer]))
    monkeypatch.setattr(main, "suggest_follow_ups", _no_follow_ups)

    response = client.post(
        "/chat/stream",
        json={"message": "What is the ASPIRE Programme?", "thread_id": "t-stream-1"},
    )
    assert response.status_code == 200

    frames = _frames(response)
    streamed = "".join(f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT")

    assert streamed == ANSWER, streamed
    for sentinel in METADATA_SENTINELS:
        assert sentinel not in streamed, f"{sentinel!r} reached the reader"
    # And the whole dump, not just its markers.
    assert CONTEXT_DUMP not in streamed


def test_the_turn_is_announced_with_the_text_that_was_sent(client, monkeypatch):
    """`reply` is what gets persisted and what the client reconciles against.

    It was read off the LAST element of the collected chunks, which on this path
    is one chunk of a streamed message rather than a whole message — so it was
    empty, every turn, and conversations were being stored with no assistant
    text in them.
    """
    answer = [
        AIMessageChunk(content=[{"type": "text", "text": part}], id="msg-1")
        for part in ("**ASPIRE** is a savings ", "and investment programme ", "for young people.")
    ]
    monkeypatch.setattr(main, "get_agent", _fake_agent(answer))
    monkeypatch.setattr(main, "suggest_follow_ups", _no_follow_ups)

    response = client.post(
        "/chat/stream", json={"message": "What is ASPIRE?", "thread_id": "t-stream-2"}
    )
    done = next(f for f in _frames(response) if f["type"] == "CUSTOM")
    assert done["value"]["reply"] == ANSWER


def test_a_tool_result_alone_streams_nothing(client, monkeypatch):
    """The failing case, reduced.

    A turn whose only string-valued content is a tool result must produce no
    prose at all. Before the fix this was the entire visible answer.
    """
    tool_call = AIMessageChunk(
        content=[],
        tool_call_chunks=[
            {"name": "search_knowledge_base", "args": "{}", "id": "call-1", "index": 0}
        ],
        id="msg-1",
    )
    tool_result = ToolMessage(content=CONTEXT_DUMP, tool_call_id="call-1", id="msg-2")

    monkeypatch.setattr(main, "get_agent", _fake_agent([tool_call, tool_result]))
    monkeypatch.setattr(main, "suggest_follow_ups", _no_follow_ups)

    response = client.post(
        "/chat/stream", json={"message": "What is ASPIRE?", "thread_id": "t-stream-3"}
    )
    frames = _frames(response)
    streamed = "".join(f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT")
    assert streamed == ""


def test_the_message_closes_before_the_follow_ups_are_generated(client, monkeypatch):
    """The prose ends when the model stops writing, not when the turn finishes.

    Follow-ups are a second model call and persistence is a database round trip.
    Both happen after the last token and took two to four seconds against the
    real service. While they ran, the client could not tell a finished answer
    from one still being written, so it held the last word back for the whole of
    it — the answer visibly completed itself seconds late.

    Asserted by ordering rather than by timing: `TEXT_MESSAGE_END` must come
    before anything the follow-up call produces. A clock would make this flaky
    for the sake of measuring what the order already proves.
    """
    answer = [
        AIMessageChunk(content=[{"type": "text", "text": part}], id="msg-1")
        for part in ("ASPIRE helps young people ", "build savings.")
    ]

    async def _slow_follow_ups(_message, _reply):
        return ["Who is eligible?"]

    monkeypatch.setattr(main, "get_agent", _fake_agent(answer))
    monkeypatch.setattr(main, "suggest_follow_ups", _slow_follow_ups)

    response = client.post(
        "/chat/stream", json={"message": "What is ASPIRE?", "thread_id": "t-stream-4"}
    )
    kinds = [f["type"] for f in _frames(response)]

    assert "TEXT_MESSAGE_END" in kinds
    # Exactly one: `done` must not close a message `text_end` already closed.
    assert kinds.count("TEXT_MESSAGE_END") == 1
    assert kinds.index("TEXT_MESSAGE_END") < kinds.index("CUSTOM")
    # And the answer itself is unchanged by having been closed earlier.
    frames = _frames(response)
    streamed = "".join(f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT")
    assert streamed == "ASPIRE helps young people build savings."


def test_the_turn_is_announced_before_the_chips_are_written(client, monkeypatch):
    """Sources and the action row must not wait on a second model call.

    `aspire.turn` carries everything derivable the moment the model stops
    writing -- the reply, the sources, which card opened. Follow-up chips are the
    one thing that is not: they cost another model call, which measured two to
    five seconds against the real service.

    They used to travel together, so the client could not settle the turn until
    the chips existed. The answer sat finished on screen with no sources, no copy
    or Ask-again row and no chips, waiting on work that none of them needed.

    The order of the frames is the contract, and it is what this asserts.
    """
    answer = [
        AIMessageChunk(content=[{"type": "text", "text": part}], id="msg-1")
        for part in ("ASPIRE helps young people ", "build savings.")
    ]

    async def _chips(_message, _reply):
        return ["Who is eligible?", "How do I apply?"]

    monkeypatch.setattr(main, "get_agent", _fake_agent(answer))
    monkeypatch.setattr(main, "suggest_follow_ups", _chips)

    # No `thread_id`: an OPENING turn. Follow-up chips are generated for the
    # first turn of a conversation only (P8-002) -- they cost a full model call
    # and their value is front-loaded -- so this is the turn on which the
    # two-frame contract is observable at all. The contract itself is unchanged:
    # whenever chips exist, they arrive in their own frame, after the turn.
    response = client.post("/chat/stream", json={"message": "What is ASPIRE?"})
    frames = _frames(response)
    customs = [f for f in frames if f["type"] == "CUSTOM"]

    assert [f["name"] for f in customs] == ["aspire.turn", "aspire.follow_ups"]

    turn = customs[0]["value"]
    assert turn["reply"] == "ASPIRE helps young people build savings."
    # Empty here on purpose. The chips are not late, they are separate.
    assert turn["follow_ups"] == []

    assert customs[1]["value"]["follow_ups"] == ["Who is eligible?", "How do I apply?"]

    # The run closes once, after everything.
    kinds = [f["type"] for f in frames]
    assert kinds.count("RUN_FINISHED") == 1
    assert kinds[-1] == "RUN_FINISHED"


def test_a_failure_after_the_answer_does_not_retract_it(client, monkeypatch):
    """Persistence is bookkeeping, and the reader already has the answer.

    Once `aspire.turn` has gone out the answer is on screen and settled. A
    database write failing after that is a real fault and is logged as one, but
    letting it raise would turn a correct answer into an error message -- the
    reader would watch a complete reply be replaced by "something went wrong".
    """
    answer = [AIMessageChunk(content=[{"type": "text", "text": "EC$500."}], id="msg-1")]

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(main, "get_agent", _fake_agent(answer))
    monkeypatch.setattr(main, "suggest_follow_ups", _no_follow_ups)
    monkeypatch.setattr(main, "_persist_turn", _explode)

    response = client.post(
        "/chat/stream", json={"message": "How much?", "thread_id": "t-stream-7"}
    )
    frames = _frames(response)
    kinds = [f["type"] for f in frames]

    assert "RUN_ERROR" not in kinds
    turn = next(f for f in frames if f.get("name") == "aspire.turn")
    assert turn["value"]["reply"] == "EC$500."
    assert kinds[-1] == "RUN_FINISHED"


def test_a_card_turn_closes_no_message_at_all(client, monkeypatch):
    """A turn with no prose must not announce a message that never started.

    `text_end` closes the message only if one was opened, so the silent path
    stays silent: a game turn's narration is dropped before it crosses the wire,
    and an empty `TEXT_MESSAGE_END` would tell the client to settle a turn that
    has no text to settle.
    """
    tool_call = AIMessageChunk(
        content=[{"type": "text", "text": "Let me start that for you."}],
        tool_call_chunks=[
            {"name": "start_game", "args": "{}", "id": "call-1", "index": 0}
        ],
        id="msg-1",
    )

    monkeypatch.setattr(main, "get_agent", _fake_agent([tool_call]))
    monkeypatch.setattr(main, "suggest_follow_ups", _no_follow_ups)

    response = client.post(
        "/chat/stream", json={"message": "Can we play a game?", "thread_id": "t-stream-5"}
    )
    kinds = [f["type"] for f in _frames(response)]

    assert "TEXT_MESSAGE_START" not in kinds
    assert "TEXT_MESSAGE_END" not in kinds
    assert "TEXT_MESSAGE_CONTENT" not in kinds


async def _no_follow_ups(_message, _reply):
    """Follow-ups are a second model call and are not what these tests measure."""
    return []


def test_a_continuing_turn_does_not_pay_for_chips(client, monkeypatch):
    """P8-002: follow-ups are an opening-turn affordance, not a per-turn cost.

    They were generated on every non-card turn -- a third model call each time,
    roughly a 2x multiplier on per-turn model calls for a UI affordance whose
    value is entirely front-loaded. A reader on turn one does not know what to
    ask; by turn twelve they have been asking.

    Asserted by counting calls rather than by looking at the frames, because the
    saving IS the call not happening. A version that generated the chips and
    then dropped them would pass a frame assertion and cost exactly as much.
    """
    answer = [
        AIMessageChunk(content=[{"type": "text", "text": "Yes."}], id="msg-1")
    ]
    calls = []

    async def _chips(message, reply):
        calls.append(message)
        return ["Who is eligible?"]

    monkeypatch.setattr(main, "get_agent", _fake_agent(answer))
    monkeypatch.setattr(main, "suggest_follow_ups", _chips)

    response = client.post(
        "/chat/stream",
        json={"message": "And what about savings?", "thread_id": "t-stream-continuing"},
    )
    customs = [f for f in _frames(response) if f["type"] == "CUSTOM"]

    assert calls == [], "a continuing turn spent a model call on follow-up chips"

    # The frame still arrives, carrying nothing. Deliberate: the wire shape is
    # the same on every turn, so the client has one code path rather than two
    # and "no chips" is a value rather than an absence to time out on.
    assert [f["name"] for f in customs] == ["aspire.turn", "aspire.follow_ups"]
    assert customs[1]["value"]["follow_ups"] == []


# --- the question must be sent exactly once (P13-004) --------------------


def _run_db(coro) -> None:
    """Run one database coroutine and leave nothing pooled behind it.

    The dispose is the point. The engine is process-wide and its asyncpg
    connections bind to whichever loop opened them, so a test that seeds on one
    `asyncio.run` loop and cleans up on another hands the second loop a socket
    belonging to the first and dies with "Event loop is closed" -- which is
    exactly how this test first failed, masking the assertion it was written to
    make. Disposing means the next caller, on whatever loop, opens a fresh one.
    """
    import asyncio

    from app.db import dispose

    async def go():
        try:
            await coro
        finally:
            await dispose()

    asyncio.run(go())


def _capturing_agent(chunks, captured: list):
    """A fake agent that records the messages it was asked to answer."""

    class Agent:
        async def astream(self, inputs, config=None, stream_mode=None):
            captured.append(list(inputs["messages"]))
            for chunk in chunks:
                yield chunk, {}

    return lambda _simple=False: Agent()


def test_a_continuing_turn_sends_the_question_exactly_once(client, monkeypatch):
    """The bug: `_open_conversation` wrote the question, then history read it back.

    Ordering `_open_conversation` before `_prepare_messages` meant the window read
    returned the question this very turn had just recorded, and `build_prompt`
    appended it again -- so the model received the same sentence twice, on every
    turn past the opening one.

    Asserted on the messages the agent is actually handed, because that is the
    only place the duplicate was ever visible. Nothing about the response shape
    changed when it was there, which is why it survived this long.
    """
    import uuid as _uuid

    from app.db import database_enabled, session
    from app.db.repository import append_turn, ensure_conversation

    if not database_enabled():
        pytest.skip("history comes from Postgres; nothing to duplicate without it")

    thread_id = f"t-dup-{_uuid.uuid4()}"
    question = "And what about withdrawals?"

    async def seed():
        async with session() as db:
            await ensure_conversation(db, thread_id, language="en")
            await append_turn(db, thread_id, role="user", content="What is ASPIRE?")
            await append_turn(db, thread_id, role="assistant", content="A savings programme.")

    async def clean():
        from sqlalchemy import text

        async with session() as db:
            await db.execute(
                text("DELETE FROM messages WHERE conversation_id=:t"), {"t": thread_id}
            )
            await db.execute(
                text("DELETE FROM conversations WHERE id=:t"), {"t": thread_id}
            )

    _run_db(seed())
    try:
        captured: list[list] = []
        answer = [AIMessageChunk(content=[{"type": "text", "text": "Yes."}], id="m-1")]
        monkeypatch.setattr(main, "get_agent", _capturing_agent(answer, captured))

        response = client.post(
            "/chat/stream", json={"message": question, "thread_id": thread_id}
        )
        assert response.status_code == 200

        assert captured, "the agent was never invoked"
        contents = [m.content for m in captured[0]]
        assert contents.count(question) == 1, (
            f"the question was sent {contents.count(question)} times: {contents}"
        )
        # And the prior turn is still there -- the fix must not cost the history.
        assert "What is ASPIRE?" in contents
        assert "A savings programme." in contents
    finally:
        _run_db(clean())


def test_history_is_read_before_the_question_is_recorded(client, monkeypatch):
    """Structural guard on the ordering, independent of any database.

    The behavioural test above needs Postgres. This one does not, so the ordering
    stays pinned even where the integration test skips.
    """
    import inspect

    # Asserted where the guarantee now lives. P13-004 enforced it by call order
    # inside `chat_stream`; P13-005 moved it into `_prepare_messages`, which reads
    # the window and only then invokes `after_history` -- the hook both endpoints
    # use to put the question-write in flight.
    #
    # Two earlier drafts of this test broke on unrelated edits: the first pinned
    # exact argument lists, the second assumed the write was `await`ed at the call
    # site rather than launched as a task. So this matches the two call NAMES and
    # only their relative order, which is the property and nothing else.
    source = inspect.getsource(main._prepare_messages)
    read = source.index("_load_history(")
    record = source.index("after_history(")
    assert read < record, (
        "the question is recorded before the window is read again; the read will "
        "return this turn's question and it will be sent to the model twice"
    )


# --- helpers for the cache tests (P13-006) --------------------------------


async def _ready(value):
    """An already-decided awaitable, so `_cached_reply` can be a plain value."""
    return value


async def _noop(*_args, **_kwargs):
    """Swallows any signature. Used where the call is not what is being tested."""
    return None

# --- the response cache, on the transport the client uses (P13-006) -------


def _cached(reply="ASPIRE Day is a sign-up drive.", sources=None, follow_ups=None):
    from app.schemas import ChatResponse, Source

    return ChatResponse(
        reply=reply,
        thread_id="a-fresh-id-from-the-cache",
        sources=[Source(**s) for s in (sources or [{"content": "row", "metadata": {"id": "ASP-184"}}])],
        follow_ups=follow_ups if follow_ups is not None else ["What is ASPIRE?"],
    )


def test_a_cache_hit_streams_the_answer_without_a_model_call(client, monkeypatch):
    """P12-001: the cache existed on `/chat` while the client used `/chat/stream`.

    The assertion that matters is `calls == []`. A version that consulted the
    cache and then ran the agent anyway would produce identical frames and cost
    exactly as much, which is the failure this is written against.
    """
    calls: list = []

    def _exploding_agent(_simple=False):
        calls.append(1)
        raise AssertionError("the agent ran on a cache hit")

    monkeypatch.setattr(main, "get_agent", _exploding_agent)
    monkeypatch.setattr(main, "_cached_reply", lambda _request: _ready(_cached()))
    monkeypatch.setattr(main, "_open_conversation", _noop)
    monkeypatch.setattr(main, "_persist_turn", _noop)

    response = client.post("/chat/stream", json={"message": "What is ASPIRE Day?"})
    assert response.status_code == 200

    frames = _frames(response)
    kinds = [f["type"] for f in frames]
    assert calls == [], "the agent was invoked on a cache hit"

    # The full envelope, in order, exactly as a computed turn produces.
    assert kinds[0] == "RUN_STARTED"
    assert "TEXT_MESSAGE_START" in kinds
    assert "TEXT_MESSAGE_END" in kinds
    assert kinds[-1] == "RUN_FINISHED"

    streamed = "".join(f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT")
    assert streamed == "ASPIRE Day is a sign-up drive."

    turn = next(f for f in frames if f.get("name") == "aspire.turn")
    assert turn["value"]["reply"] == "ASPIRE Day is a sign-up drive."
    assert turn["value"]["sources"][0]["metadata"]["id"] == "ASP-184"
    # Never a card: cards are not cacheable, and replaying one would render a
    # card for a flow no server-side session was opened for.
    assert turn["value"]["game_started"] is None
    assert turn["value"]["eligibility_started"] is None

    chips = next(f for f in frames if f.get("name") == "aspire.follow_ups")
    assert chips["value"]["follow_ups"] == ["What is ASPIRE?"]


def test_a_cache_hit_reports_the_thread_id_it_will_be_stored_under(client, monkeypatch):
    """The client continues the conversation with this id, so it must be the one
    the turn is persisted under -- not the throwaway id `_cached_reply` mints."""
    recorded: dict = {}

    async def _capture_open(request, thread_id, owner_id):
        recorded["opened"] = thread_id

    async def _capture_persist(request, thread_id, **kwargs):
        recorded["persisted"] = thread_id
        recorded["reply"] = kwargs["reply"]

    monkeypatch.setattr(main, "get_agent", _fake_agent([]))
    monkeypatch.setattr(main, "_cached_reply", lambda _request: _ready(_cached()))
    monkeypatch.setattr(main, "_open_conversation", _capture_open)
    monkeypatch.setattr(main, "_persist_turn", _capture_persist)

    response = client.post("/chat/stream", json={"message": "What is ASPIRE Day?"})
    turn = next(f for f in _frames(response) if f.get("name") == "aspire.turn")
    announced = turn["value"]["thread_id"]

    assert announced != "a-fresh-id-from-the-cache", (
        "the id from _cached_reply leaked to the client; it is never persisted"
    )
    assert recorded["opened"] == announced
    assert recorded["persisted"] == announced
    assert recorded["reply"] == "ASPIRE Day is a sign-up drive."


def test_a_cache_hit_is_still_recorded_in_postgres(client, monkeypatch):
    """The bug `/chat` has and this path must not.

    `/chat` returns its cached reply and stops, so a cached first turn leaves no
    conversation and no messages. Here the client has already committed the chat
    to the rail and the address bar, so an unrecorded conversation is a chat on
    screen with a dead end behind it.
    """
    persisted: list[str] = []

    async def _note(name, *args, **kwargs):
        persisted.append(name)

    monkeypatch.setattr(main, "get_agent", _fake_agent([]))
    monkeypatch.setattr(main, "_cached_reply", lambda _request: _ready(_cached()))
    monkeypatch.setattr(
        main, "_open_conversation", lambda *a, **k: _note("open", *a, **k)
    )
    monkeypatch.setattr(main, "_persist_turn", lambda *a, **k: _note("persist", *a, **k))

    client.post("/chat/stream", json={"message": "What is ASPIRE Day?"})
    assert persisted == ["open", "persist"], (
        "a cached turn must be recorded, and the question before the answer"
    )


def test_a_continuing_turn_never_consults_the_cache(client, monkeypatch):
    """Mid-thread questions depend on what came before, so two identical strings
    in two conversations are not the same question."""
    asked: list = []

    async def _watch(request):
        asked.append(request.thread_id)
        return None

    answer = [AIMessageChunk(content=[{"type": "text", "text": "Yes."}], id="m-1")]
    monkeypatch.setattr(main, "get_agent", _fake_agent(answer))
    monkeypatch.setattr(main, "suggest_follow_ups", _no_follow_ups)
    monkeypatch.setattr(main, "_cached_reply", _watch)

    client.post(
        "/chat/stream", json={"message": "And savings?", "thread_id": "t-continuing"}
    )
    # `_cached_reply` is consulted but returns None for a thread_id -- the guard
    # lives inside it, and this pins that the streaming path relies on it rather
    # than reimplementing the rule.
    assert asked == ["t-continuing"]


def test_the_streaming_path_populates_the_cache(client, monkeypatch):
    """The other half of P12-001: only `/chat` ever wrote to the cache, so the
    only writer was the transport nobody used and the cache stayed empty."""
    written: list[dict] = []

    async def _put(query, payload, **kwargs):
        written.append({"query": query, **payload})

    answer = [
        AIMessageChunk(content=[{"type": "text", "text": "A savings programme."}], id="m-1")
    ]
    monkeypatch.setattr(main, "get_agent", _fake_agent(answer))
    monkeypatch.setattr(main, "suggest_follow_ups", _no_follow_ups)
    monkeypatch.setattr(main, "_open_conversation", _noop)
    monkeypatch.setattr(main, "_persist_turn", _noop)
    monkeypatch.setattr(main.response_cache, "put_answer", _put)
    monkeypatch.setattr(main.response_cache, "release_lease", _noop)

    client.post("/chat/stream", json={"message": "What is ASPIRE?"})

    assert len(written) == 1, "the computed answer was not cached"
    assert written[0]["query"] == "What is ASPIRE?"
    assert written[0]["reply"] == "A savings programme."
