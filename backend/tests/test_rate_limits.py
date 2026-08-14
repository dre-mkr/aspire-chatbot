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


# ── the mint endpoint, which had no limit at all ─────────────────────────────


def test_minting_a_session_is_metered(client, monkeypatch):
    """
    `/v2/session` was unmetered, and it is where every metered endpoint's
    token comes from.
    """
    import uuid as uuid_module

    monkeypatch.setattr(get_settings(), "graph_sessions_per_window", 3, raising=False)

    codes = [
        client.post("/v2/session", json={"session_id": str(uuid_module.uuid4())}).status_code
        for _ in range(5)
    ]

    assert codes[:3] == [200, 200, 200], codes
    assert codes[-1] == 429, codes


def test_a_turn_is_not_metered_against_the_id_the_caller_chose(monkeypatch):
    """
    Rotating `session_id` used to hand a caller a fresh budget.

    The bucket was keyed `s:{session_id}` for anyone without an account, and
    `session_id` arrives in the body of `/v2/session` unread -- so the value
    being counted was the one the caller picks. Minting a new token with a new
    id reset the count.

    Asserted against `graph_rate_limit` rather than by driving real turns. The
    end-to-end version worked, but tripping a 429 mid-stream left the Postgres
    checkpointer holding a lock bound to that test's event loop, and the next
    file to run inherited the wreckage. The property here is which key the
    bucket uses; the transport is not part of it.
    """
    import uuid as uuid_module

    from fastapi import HTTPException

    from app.limits import graph_rate_limit

    monkeypatch.setattr(get_settings(), "chat_messages_per_window", 2, raising=False)

    class _Request:
        client = type("C", (), {"host": "203.0.113.7"})()
        headers: dict[str, str] = {}

    request = _Request()
    refused = 0
    for _ in range(4):
        try:
            # A new id every time, which is exactly what re-minting gave you.
            graph_rate_limit(request, str(uuid_module.uuid4()), None)
        except HTTPException as exc:
            assert exc.status_code == 429
            refused += 1

    assert refused, (
        "four turns under a limit of two were all allowed; the bucket is keyed "
        "on something the caller controls"
    )


def test_an_account_is_still_metered_on_its_own_id(monkeypatch):
    """
    Dropping the `s:` key must not push signed-in readers into one bucket.

    A school visit is many children behind one NAT address, and each of them
    has called `/api/auth/anonymous`, so each carries a real `sub` and meters
    against `u:` -- not against the address they share.
    """
    from fastapi import HTTPException

    from app.limits import graph_rate_limit

    monkeypatch.setattr(get_settings(), "chat_messages_per_window", 2, raising=False)

    class _Request:
        client = type("C", (), {"host": "203.0.113.8"})()
        headers: dict[str, str] = {}

    request = _Request()
    for index in range(6):
        # Six turns from six accounts at one address: nobody is refused.
        graph_rate_limit(request, "shared-thread", f"user-{index}")

    with pytest.raises(HTTPException):
        for _ in range(4):
            graph_rate_limit(request, "shared-thread", "user-0")


# ── what may be signed into a token ──────────────────────────────────────────


def test_a_guessable_session_id_is_replaced(client):
    """
    The id is the conversation's address, and it was accepted verbatim.

    The database still holds 56 conversations whose id is under thirty
    characters -- `probe-stream-1` among them -- and any caller naming one of
    those could pick up a thread that has no owner.
    """
    response = client.post("/v2/session", json={"session_id": "probe-stream-1"})

    assert response.status_code == 200
    assert response.json()["session_id"] != "probe-stream-1"
    assert len(response.json()["session_id"]) >= 16


def test_a_thread_id_a_real_client_makes_is_kept(client):
    """
    Not a UUID requirement: `newThreadId` falls back to `t-<base36>-<base36>`
    when `crypto.randomUUID` is missing -- an older Safari on a school tablet,
    or a plain-HTTP staging box. Rejecting those would lock out the audience.
    """
    import uuid as uuid_module

    for wanted in (str(uuid_module.uuid4()), "t-m1k2j3h4-a9b8c7d6"):
        response = client.post("/v2/session", json={"session_id": wanted})
        assert response.status_code == 200
        assert response.json()["session_id"] == wanted, wanted


def test_a_junk_device_id_does_not_become_a_signed_claim(client):
    """`/api/auth/anonymous` always checked this shape; this endpoint did not."""
    import uuid as uuid_module

    from app.graph.identity import decode_session_token

    response = client.post(
        "/v2/session",
        json={"session_id": str(uuid_module.uuid4()), "device_id": "x" * 500},
    )

    assert response.status_code == 200
    claims = decode_session_token(response.json()["token"])
    assert claims is not None
    assert claims.device_id == "unknown"
