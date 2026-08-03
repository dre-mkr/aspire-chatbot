"""The IDOR that migration 0006 exists to close, as a test that fails without it.

Until today, authorisation read an `X-Aspire-Device` header and believed it.
That header is not a secret: the client sends it on every request and keeps it
in the browser's own storage. Anyone holding somebody else's device id could
read their conversations.

The rule now is that a device id seeds the creation of an anonymous identity and
is never accepted as proof of one. Everything below is a way of trying to break
that rule and failing.

These tests talk to the real app through a TestClient. They need a database, and
skip cleanly without one, because a security test that silently passes when it
could not run is worse than no test.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import database_enabled  # noqa: E402
from app.main import app  # noqa: E402

pytestmark = pytest.mark.skipif(
    not database_enabled(), reason="These are database-backed security tests."
)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def anonymous(client: TestClient, device_id: str | None = None) -> dict:
    body = {"device_id": device_id} if device_id else {}
    response = client.post("/api/auth/anonymous", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def make_conversation(client: TestClient, token: str, message: str) -> str:
    """One real turn, so there is something worth stealing."""
    thread_id = str(uuid.uuid4())
    response = client.post(
        "/chat",
        json={"message": message, "thread_id": thread_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code in (200, 502), response.text
    return thread_id


# ── the vulnerability itself ─────────────────────────────────────────────────


def test_device_header_alone_authorises_nothing(client: TestClient):
    """The old credential, presented on its own, is now worth nothing."""
    victim = anonymous(client, device_id=str(uuid.uuid4()))
    make_conversation(client, victim["token"], "What is an index fund?")

    # Exactly the request that used to work.
    stolen = client.get(
        "/api/conversations", headers={"X-Aspire-Device": victim["user_id"]}
    )
    assert stolen.status_code == 401

    # And with the device id the attacker would actually have seen.
    stolen_again = client.get(
        "/api/conversations", headers={"X-Aspire-Device": str(uuid.uuid4())}
    )
    assert stolen_again.status_code == 401


def test_a_device_id_cannot_be_exchanged_for_its_owners_session(client: TestClient):
    """Presenting somebody's device id must not mint a session for them.

    This is the subtler shape of the same hole: not reading their data directly,
    but asking the session endpoint to hand over an identity that already owns
    it. The endpoint always creates a new row, so the attacker gets a stranger's
    empty session rather than the victim's full one.
    """
    device = str(uuid.uuid4())
    victim = anonymous(client, device_id=device)
    make_conversation(client, victim["token"], "How do I start saving?")

    attacker = anonymous(client, device_id=device)  # the same seed
    assert attacker["user_id"] != victim["user_id"]

    listing = client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {attacker['token']}"}
    )
    assert listing.status_code == 200
    assert listing.json()["conversations"] == []


def test_one_identity_cannot_read_anothers_conversation(client: TestClient):
    """Even knowing the exact conversation id."""
    victim = anonymous(client)
    thread_id = make_conversation(client, victim["token"], "What is compound interest?")

    attacker = anonymous(client)
    response = client.get(
        f"/api/conversations/{thread_id}",
        headers={"Authorization": f"Bearer {attacker['token']}"},
    )
    # 404, not 403: "not yours" and "does not exist" must be indistinguishable,
    # or the API becomes an oracle for which conversation ids are real.
    assert response.status_code == 404


def test_one_identity_cannot_rename_anothers_conversation(client: TestClient):
    victim = anonymous(client)
    thread_id = make_conversation(client, victim["token"], "Explain interest")

    attacker = anonymous(client)
    response = client.patch(
        f"/api/conversations/{thread_id}",
        json={"title": "owned", "title_source": "manual"},
        headers={"Authorization": f"Bearer {attacker['token']}"},
    )
    assert response.status_code == 404


# ── the token itself ─────────────────────────────────────────────────────────


def test_unsigned_and_tampered_tokens_are_refused(client: TestClient):
    victim = anonymous(client)
    token = victim["token"]

    header, payload, signature = token.split(".")
    forged = f"{header}.{payload}.{'a' * len(signature)}"
    assert (
        client.get(
            "/api/conversations", headers={"Authorization": f"Bearer {forged}"}
        ).status_code
        == 401
    )

    # `alg: none`, the classic. PyJWT refuses it, but assert rather than assume.
    import base64
    import json

    none_alg = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
        + "."
        + payload
        + "."
    )
    assert (
        client.get(
            "/api/conversations", headers={"Authorization": f"Bearer {none_alg}"}
        ).status_code
        == 401
    )

    assert client.get("/api/conversations").status_code == 401
    assert (
        client.get(
            "/api/conversations", headers={"Authorization": "Bearer not-a-token"}
        ).status_code
        == 401
    )


def test_a_valid_token_reads_only_its_own_conversations(client: TestClient):
    """The positive case, so the tests above are not passing vacuously."""
    user = anonymous(client)
    thread_id = make_conversation(client, user["token"], "What is an index fund?")

    listing = client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {user['token']}"}
    )
    assert listing.status_code == 200
    ids = [c["thread_id"] for c in listing.json()["conversations"]]
    assert thread_id in ids

    detail = client.get(
        f"/api/conversations/{thread_id}",
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert detail.status_code == 200
    assert any(m["role"] == "user" for m in detail.json()["messages"])


# ── chat stays open to everybody ─────────────────────────────────────────────


def test_chat_works_with_no_identity_at_all(client: TestClient):
    """Part 1: sign-up is never required, and neither is a session.

    A turn with no Authorization header must still be answered. The conversation
    is simply stored unowned and appears in nobody's list.
    """
    response = client.post(
        "/chat", json={"message": "What is an index fund?", "thread_id": str(uuid.uuid4())}
    )
    assert response.status_code in (200, 502)
    assert response.status_code != 401
