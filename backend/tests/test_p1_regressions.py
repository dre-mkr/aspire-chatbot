"""P1 regression tests — written BEFORE any fix exists."""

from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


# ── P0-004 — the question is recorded before it is answered ─────────────────


def test_open_conversation_records_the_question(monkeypatch):
    """A first turn whose answer fails must still leave a conversation behind."""
    calls: list[str] = []

    class _FakeSession:
        pass

    @asynccontextmanager
    async def _fake_session():
        yield _FakeSession()

    async def _fake_ensure(db, thread_id, **kwargs):
        calls.append("ensure_conversation")

    async def _fake_append(db, thread_id, *, role, content, extra=None):
        calls.append(f"append_turn:{role}")

    from app import turn as turn_service

    monkeypatch.setattr(turn_service, "database_enabled", lambda: True)
    monkeypatch.setattr(turn_service, "session", _fake_session)
    monkeypatch.setattr(turn_service, "ensure_conversation", _fake_ensure)
    monkeypatch.setattr(turn_service, "append_turn", _fake_append)

    record = turn_service.TurnRecord(
        thread_id="thread-1", question="Am I eligible for ASPIRE?", reply=""
    )
    asyncio.run(turn_service.open_conversation(record))

    assert calls == ["ensure_conversation", "append_turn:user"], (
        "P0-004: the conversation row and the question must both be written "
        "BEFORE the graph runs, so a failed answer still leaves something to "
        "reopen."
    )


def test_the_stream_starts_the_conversation_write_before_the_graph(monkeypatch):
    """And it starts it before the graph, not after."""
    from app.api import stream

    # Matched on the source text, because the ordering is what this regression is about.
    source = inspect.getsource(stream._events)
    started = source.index("asyncio.create_task(turn_service.open_conversation")
    graph_runs = source.index("async for chunk in graph.astream")
    assert started < graph_runs, (
        "the conversation write must be in flight before the graph runs"
    )


# ── P1-001 — the LLM endpoints are unauthenticated and unmetered ────────────


def test_title_endpoint_requires_a_session(monkeypatch):
    """`/api/title` is a model call behind no auth and no rate limit."""

    async def _no_model_call(message, answer, language="en"):
        return "Stubbed title"

    monkeypatch.setattr(main, "suggest_title", _no_model_call)

    response = TestClient(app).post(
        "/api/title",
        json={"message": "hello", "answer": "hi there", "language": "en"},
    )

    assert response.status_code == 401, (
        "P1-001: `/api/title` answers anyone. Expected 401 without a session; "
        f"got {response.status_code} — and with the stub removed, that response "
        "is a model call the caller never had to identify themselves to spend."
    )


def _llm_handlers():
    """The handlers of every endpoint that spends a model call."""
    from app.api.stream import chat_stream_v2, widget_interaction
    from app.main import title

    return {
        "/v2/chat/stream": chat_stream_v2,
        "/v2/widget/interaction": widget_interaction,
        "/api/title": title,
    }


@pytest.mark.parametrize(
    "route", ["/v2/chat/stream", "/v2/widget/interaction", "/api/title"]
)
def test_llm_routes_are_rate_limited(route):
    """Every endpoint that spends a model call must be metered per caller."""
    source = inspect.getsource(_llm_handlers()[route])

    assert "limit" in source.lower() or "_meter" in source, (
        f"P1-001: {route} has no rate limiting of any kind. Its handler never "
        "consults a limiter, and no limiting middleware is installed "
        "(main.py adds only CORSMiddleware)."
    )


def test_the_stream_meters_before_the_response_opens():
    """A 429 has to be a 429, not an error event inside a 200."""
    from app.api.stream import chat_stream_v2

    source = inspect.getsource(chat_stream_v2)
    assert source.index("_meter(") < source.index("StreamingResponse("), (
        "the rate limit must be enforced before the response is opened"
    )


# ── P1-002 — blocking filesystem work on the event loop ────────────────────


@pytest.mark.xfail(strict=True, reason="open finding; remove this marker with the fix")
def test_voice_cache_writes_do_not_block_the_event_loop():
    """`async def speak` does synchronous filesystem work, including a full scan."""
    from app.voice import router as voice_router

    source = inspect.getsource(voice_router.speak)

    assert "to_thread" in source or "run_in_threadpool" in source, (
        "P1-002: `speak` calls `cache.get`/`cache.put` directly on the event "
        "loop. The eviction sweep is O(number of cached clips) syscalls on "
        "every synthesis. Dispatch the cache I/O to a thread."
    )
