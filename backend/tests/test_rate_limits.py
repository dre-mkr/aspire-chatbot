"""P1-001: the endpoints that spend model calls are metered and identified.

The regression test in `test_p1_regressions.py` is structural -- it asserts a
limiter is wired into the handler. This one asserts the behaviour: that the limit
actually refuses, that it refuses with something a child can read, and that a
turn is never billed to nobody.

No model calls: every path here is stubbed or rejected before the agent runs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import ACCOUNT_ANONYMOUS, mint_token
from app.config import get_settings
from app.limits import get_limiter
from app.main import app

#: P0-010 -- see the `slow` marker note in pyproject.toml.
pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _clean_limiter():
    """Each test gets a fresh window.

    The limiter is process-wide by design (app/limits.py explains why), which
    makes it shared state between tests exactly as the session cap is -- and that
    one taught us the lesson the hard way when two suites raced (P11-001).
    """
    get_limiter().reset()
    yield
    get_limiter().reset()


@pytest.fixture
def client():
    return TestClient(app)


def test_title_refuses_without_a_session(client):
    """No identity, no model call. `/api/title` used to answer anybody."""
    response = client.post(
        "/api/title", json={"message": "hi", "answer": "there", "language": "en"}
    )
    assert response.status_code == 401


def test_title_is_metered_per_caller(client, monkeypatch):
    """The limit refuses once the window is full, and says so usefully."""

    async def _no_model_call(message, answer, language="en"):
        return "Stubbed"

    monkeypatch.setattr(main, "suggest_title", _no_model_call)

    import uuid

    token = mint_token(uuid.uuid4(), ACCOUNT_ANONYMOUS, 1)
    headers = {"Authorization": f"Bearer {token}"}
    body = {"message": "hi", "answer": "there", "language": "en"}
    limit = get_settings().title_requests_per_window

    for i in range(limit):
        assert client.post("/api/title", json=body, headers=headers).status_code == 200, (
            f"request {i + 1} of {limit} should still be inside the window"
        )

    refused = client.post("/api/title", json=body, headers=headers)
    assert refused.status_code == 429
    assert refused.headers.get("Retry-After"), "a 429 must say when to come back"

    detail = refused.json()["detail"]
    # A child reads this. It should say what happened and what to do, and
    # nothing about buckets, windows or quotas.
    assert "wait" in detail.lower() or "moment" in detail.lower()
    for jargon in ("rate", "quota", "bucket", "window", "429"):
        assert jargon not in detail.lower(), f"{jargon!r} leaked into user-facing copy"


def test_two_callers_do_not_share_a_window(client, monkeypatch):
    """One caller exhausting the limit must not lock everyone else out.

    The counter is keyed per identity, so a busy user cannot deny the service to
    the next person -- which is the failure mode that turns a cost control into
    an outage.
    """

    async def _no_model_call(message, answer, language="en"):
        return "Stubbed"

    monkeypatch.setattr(main, "suggest_title", _no_model_call)

    import uuid

    body = {"message": "hi", "answer": "there", "language": "en"}
    limit = get_settings().title_requests_per_window

    busy = {"Authorization": f"Bearer {mint_token(uuid.uuid4(), ACCOUNT_ANONYMOUS, 1)}"}
    for _ in range(limit):
        client.post("/api/title", json=body, headers=busy)
    assert client.post("/api/title", json=body, headers=busy).status_code == 429

    fresh = {"Authorization": f"Bearer {mint_token(uuid.uuid4(), ACCOUNT_ANONYMOUS, 1)}"}
    assert client.post("/api/title", json=body, headers=fresh).status_code == 200


def test_chat_is_metered_without_requiring_a_session(client, monkeypatch):
    """Anonymous questioning stays supported, and stays counted.

    Asking a question has never required identifying yourself and must not start
    to. The limit therefore falls back to the caller's address -- which is why it
    is sized for a school rather than for one child.
    """
    calls = {"n": 0}

    class _Agent:
        async def ainvoke(self, *args, **kwargs):
            calls["n"] += 1
            raise AssertionError("the agent must not run once the window is full")

    limit = get_settings().chat_messages_per_window
    body = {"message": "What is ASPIRE?"}

    # Fill the window without spending anything: the agent raising is fine here,
    # it only has to prove the request got past the limiter.
    for _ in range(limit):
        client.post("/chat", json=body)

    monkeypatch.setattr(main, "get_agent", lambda *a, **k: _Agent())
    refused = client.post("/chat", json=body)

    assert refused.status_code == 429
    assert calls["n"] == 0, "a refused turn must never reach the model"
