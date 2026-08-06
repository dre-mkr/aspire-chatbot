"""P1 regression tests — written BEFORE any fix exists.

Every test here is expected to FAIL against the current code. Each states the
behaviour the service should have; the assertion message names the ledger id and
what happens today.

Marked `xfail(strict=True)` so the suite stays green while the bugs are open --
these document defects, they are not new breakage. `strict=True` matters: when a
fix lands the test starts passing, pytest reports XPASS as a FAILURE, and whoever
fixed it is told to remove the marker. A plain xfail would let the fix land
silently and leave a stale marker behind.

Deliberately free of real model calls and, where possible, of a real database:
these assert on structure and on contracts, so they run in any environment.
"""

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
    """A first turn whose answer fails must still leave a conversation behind.

    That is what `turn.open_conversation`'s own docstring promises, and it is
    what the client depends on: `use-conversation.ts` commits the chat to the
    URL and the rail synchronously, before sending, and `openPast` shows a
    "this question never got an answer" retry when it reopens a conversation
    whose last stored turn is the question. With nothing written, there is no
    conversation to reopen -- a committed chat with no route out.

    Repointed from `main._open_conversation`, which is gone with `/chat`. The
    function moved to `app/turn.py`; the guarantee did not move with it by
    accident, so it is asserted here rather than assumed.
    """
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
    """And it starts it before the graph, not after.

    `_events` creates the write as a task rather than awaiting it -- awaiting
    would put a Neon round trip in front of the first token -- so the ordering
    that matters is where the task is CREATED. A task created after
    `graph.astream` would not survive the graph raising, which is the exact case
    the guarantee is for.
    """
    from app.api import stream

    # Matched on the code rather than on the names: the docstring draws the same
    # ordering as a diagram, and a substring search would find that instead and
    # pass regardless of what the function does.
    source = inspect.getsource(stream._events)
    started = source.index("asyncio.create_task(turn_service.open_conversation")
    graph_runs = source.index("async for chunk in graph.astream")
    assert started < graph_runs, (
        "the conversation write must be in flight before the graph runs"
    )


# ── P1-001 — the LLM endpoints are unauthenticated and unmetered ────────────


def test_title_endpoint_requires_a_session(monkeypatch):
    """`/api/title` is a model call behind no auth and no rate limit.

    `main.py:871` takes only a `TitleRequest` — no `Depends(chat_principal)`,
    no limiter. It accepts up to 8,000 characters of `message` and 20,000 of
    `answer` and spends a model call per request. With `CORS_ALLOW_ORIGINS=["*"]`
    (P0-008) any page on the internet can drive it from a visitor's browser.

    This is the cheapest endpoint in the product to abuse and the only one with
    no identity requirement whatsoever.

    The model call is stubbed: a test that spends real tokens on every CI run
    would be its own small version of the problem being reported.
    """

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
    """The handlers of every endpoint that spends a model call.

    Imported rather than read off `app.routes`. This FastAPI version wraps an
    included router in an opaque `_IncludedRouter` and flattens it at request
    time, so `app.routes` lists four handlers and eight anonymous wrappers --
    and the routes that matter here all live on routers now that `/chat` is
    gone. A path lookup would silently find nothing and pass.
    """
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
    """Every endpoint that spends a model call must be metered per caller.

    The only rate limits in the service are anonymous session *creation*
    (`sessions.py:125`) and the voice layer (`voice/limiter.py`). Message send,
    which is the expensive path, has none — so a single caller can spend the
    programme's budget as fast as the network allows. The pack rates a missing
    limit on message send S1.
    """
    source = inspect.getsource(_llm_handlers()[route])

    assert "limit" in source.lower() or "_meter" in source, (
        f"P1-001: {route} has no rate limiting of any kind. Its handler never "
        "consults a limiter, and no limiting middleware is installed "
        "(main.py adds only CORSMiddleware)."
    )


def test_the_stream_meters_before_the_response_opens():
    """A 429 has to be a 429, not an error event inside a 200.

    `StreamingResponse` sends its status line before the body generator runs, so
    a limiter that raised inside `_events` would produce a truncated 200 that
    the client cannot tell apart from a short answer. `_meter` is called in the
    route handler, above the `return StreamingResponse(...)`, and this asserts
    that ordering rather than trusting it.
    """
    from app.api.stream import chat_stream_v2

    source = inspect.getsource(chat_stream_v2)
    assert source.index("_meter(") < source.index("StreamingResponse("), (
        "the rate limit must be enforced before the response is opened"
    )


# ── P1-002 — blocking filesystem work on the event loop ────────────────────


@pytest.mark.xfail(strict=True, reason="open finding; remove this marker with the fix")
def test_voice_cache_writes_do_not_block_the_event_loop():
    """`async def speak` does synchronous filesystem work, including a full scan.

    `voice/router.py:190` is an async handler. Line 212 calls `cache.get`, which
    does `path.read_bytes()` plus a `utime`; line 234 calls `cache.put`, which
    writes a temp file, renames it, and then calls `evict_if_needed` — and that
    globs `*.mp3` across the whole cache directory and `stat`s every entry
    (`voice/cache.py:89`).

    With `--workers 1` (deploy/aspire-api.service) every one of those syscalls
    is serialised against every other request in the process, including live
    chat turns.
    """
    from app.voice import router as voice_router

    source = inspect.getsource(voice_router.speak)

    assert "to_thread" in source or "run_in_threadpool" in source, (
        "P1-002: `speak` calls `cache.get`/`cache.put` directly on the event "
        "loop. The eviction sweep is O(number of cached clips) syscalls on "
        "every synthesis. Dispatch the cache I/O to a thread."
    )
