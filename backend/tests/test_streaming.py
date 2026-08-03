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


async def _no_follow_ups(_message, _reply):
    """Follow-ups are a second model call and are not what these tests measure."""
    return []
