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
