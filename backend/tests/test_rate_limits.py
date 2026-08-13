"""P1-001: the endpoints that spend model calls are metered and identified."""

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
    """Each test gets a fresh window."""
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
    # A child reads this.
    assert "wait" in detail.lower() or "moment" in detail.lower()
    for jargon in ("rate", "quota", "bucket", "window", "429"):
        assert jargon not in detail.lower(), f"{jargon!r} leaked into user-facing copy"


def test_two_callers_do_not_share_a_window(client, monkeypatch):
    """One caller exhausting the limit must not lock everyone else out."""

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


def test_chat_is_metered_without_requiring_a_session(client):
    """Anonymous questioning stays supported, and stays counted."""
    limit = get_settings().chat_messages_per_window
    body = {"message": "What is ASPIRE?"}

    # Fill the window.
    for _ in range(limit):
        assert client.post("/v2/chat/stream", json=body).status_code == 401

    refused = client.post("/v2/chat/stream", json=body)
    assert refused.status_code == 429
    # The limiter runs first, so a throttled caller gets 429 rather than 401.
    assert refused.status_code != 401
    assert "Retry-After" in refused.headers
