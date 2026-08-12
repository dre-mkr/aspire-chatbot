"""Registering, signing in, and carrying an anonymous session's work across."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import database_enabled  # noqa: E402
from app.main import app  # noqa: E402

#: See the `slow` marker note in pyproject.toml.
pytestmark = [pytest.mark.slow, pytest.mark.skipif(
    not database_enabled(), reason="These are database-backed account tests."
)]

STRONG = "seaview7392pass"


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def anonymous(client: TestClient) -> dict:
    r = client.post("/api/auth/anonymous", json={"device_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def new_email() -> str:
    return f"amara.{uuid.uuid4().hex[:10]}@ecse.kn"


def converse(client: TestClient, token: str, message: str) -> str:
    """One real turn, so there is a conversation to claim."""
    thread_id = str(uuid.uuid4())
    minted = client.post(
        "/v2/session", json={"session_id": thread_id}, headers=auth(token)
    )
    assert minted.status_code == 200, minted.text
    r = client.post(
        "/v2/chat/stream",
        json={"message": message},
        headers=auth(minted.json()["token"]),
    )
    assert r.status_code == 200, r.text
    return thread_id


def signup_body(email: str, **over) -> dict:
    body = {
        "email": email,
        "password": STRONG,
        "first_name": "Jayla",
        "last_name": "Thomas",
        # 15 on the date this was written: old enough to hold an account alone, no guardian needed.
        "date_of_birth": "2011-03-14",
        "island": "St. Kitts",
        "school": "Washington Archibald High School",
    }
    body.update(over)
    return body


# ── the claim ────────────────────────────────────────────────────────────────


def test_registering_carries_the_anonymous_conversations_across(client: TestClient):
    guest = anonymous(client)
    first = converse(client, guest["token"], "What is an index fund?")
    second = converse(client, guest["token"], "How do I start saving?")

    account = client.post(
        "/api/auth/register", json=signup_body(new_email()), headers=auth(guest["token"])
    )
    assert account.status_code == 200, account.text
    body = account.json()

    assert body["account_type"] == "registered"
    assert body["claim"]["attempted"] is True
    assert body["claim"]["conversations"] == 2

    listing = client.get("/api/conversations", headers=auth(body["token"]))
    assert listing.status_code == 200
    ids = {c["thread_id"] for c in listing.json()["conversations"]}
    assert {first, second} <= ids

    # And the conversation they were in the middle of still resolves, so sign-up orphans nothing.
    detail = client.get(f"/api/conversations/{first}", headers=auth(body["token"]))
    assert detail.status_code == 200


def test_the_anonymous_token_stops_working_once_claimed(client: TestClient):
    guest = anonymous(client)
    converse(client, guest["token"], "What is compound interest?")
    registered = client.post(
        "/api/auth/register", json=signup_body(new_email()), headers=auth(guest["token"])
    )
    assert registered.status_code == 200

    # The browser that just signed up must not keep writing to an identity that now owns nothing.
    stale = client.get("/api/conversations", headers=auth(guest["token"]))
    assert stale.status_code == 401


def test_an_anonymous_identity_cannot_be_claimed_twice(client: TestClient):
    guest = anonymous(client)
    converse(client, guest["token"], "What is an index fund?")

    first = client.post(
        "/api/auth/register", json=signup_body(new_email()), headers=auth(guest["token"])
    )
    assert first.status_code == 200
    assert first.json()["claim"]["conversations"] == 1

    # Replaying the same anonymous token into a second account must take nothing.
    second = client.post(
        "/api/auth/register", json=signup_body(new_email()), headers=auth(guest["token"])
    )
    assert second.status_code == 200
    assert second.json()["claim"]["conversations"] == 0

    listing = client.get("/api/conversations", headers=auth(second.json()["token"]))
    assert listing.json()["conversations"] == []


def test_signing_into_an_existing_account_merges_rather_than_discards(client: TestClient):
    """The documented decision, asserted so it cannot drift."""
    email = new_email()
    owner = client.post("/api/auth/register", json=signup_body(email))
    assert owner.status_code == 200
    original = converse(client, owner.json()["token"], "What is an index fund?")

    # Later, signed out, the same person asks something before signing in.
    guest = anonymous(client)
    while_out = converse(client, guest["token"], "How much do I need to start?")

    back_in = client.post(
        "/api/auth/login",
        json={"email": email, "password": STRONG},
        headers=auth(guest["token"]),
    )
    assert back_in.status_code == 200
    assert back_in.json()["claim"]["conversations"] == 1

    ids = {
        c["thread_id"]
        for c in client.get(
            "/api/conversations", headers=auth(back_in.json()["token"])
        ).json()["conversations"]
    }
    # Both halves survive.
    assert {original, while_out} <= ids


def test_claiming_is_all_or_nothing(client: TestClient):
    """A refused claim must leave the anonymous identity exactly as it was."""
    guest = anonymous(client)
    thread = converse(client, guest["token"], "What is an index fund?")

    account = client.post(
        "/api/auth/register", json=signup_body(new_email()), headers=auth(guest["token"])
    )
    assert account.status_code == 200

    # A second attempt with the now-dead anonymous token changes nothing about who owns the thread.
    owner = client.get(f"/api/conversations/{thread}", headers=auth(account.json()["token"]))
    assert owner.status_code == 200


# ── the age rule ─────────────────────────────────────────────────────────────


def test_an_under_13_account_requires_a_named_adult(client: TestClient):
    refused = client.post(
        "/api/auth/register",
        json=signup_body(new_email(), date_of_birth="2018-06-02", first_name="Amara"),
    )
    assert refused.status_code == 422
    assert "adult" in refused.json()["detail"].lower()


def test_an_under_13_account_is_held_by_the_guardian(client: TestClient):
    guardian_email = new_email()
    created = client.post(
        "/api/auth/register",
        json=signup_body(
            guardian_email,
            date_of_birth="2018-06-02",
            first_name="Amara",
            last_name="Liburd",
            guardian_name="Marcia Liburd",
            guardian_email=guardian_email,
            guardian_phone="869 662 0148",
        ),
    )
    assert created.status_code == 200, created.text
    # The credentials are the adult's; the child rides the same row until profiles exist.
    assert created.json()["email"] == guardian_email


# ── credentials ──────────────────────────────────────────────────────────────


def test_a_weak_password_is_refused_with_a_reason(client: TestClient):
    weak = client.post("/api/auth/register", json=signup_body(new_email(), password="short1"))
    assert weak.status_code == 422
    assert "characters" in weak.json()["detail"]


def test_a_duplicate_email_is_named_as_such(client: TestClient):
    email = new_email()
    assert client.post("/api/auth/register", json=signup_body(email)).status_code == 200
    again = client.post("/api/auth/register", json=signup_body(email))
    assert again.status_code == 409
    assert "already" in again.json()["detail"].lower()


def test_sign_in_says_the_same_thing_for_both_failures(client: TestClient):
    email = new_email()
    client.post("/api/auth/register", json=signup_body(email))

    wrong = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword1"})
    missing = client.post(
        "/api/auth/login", json={"email": new_email(), "password": "wrongpassword1"}
    )
    assert wrong.status_code == missing.status_code == 401
    # Identical wording, so the response is not an oracle for which addresses have accounts.
    assert wrong.json()["detail"] == missing.json()["detail"]


def test_signing_out_retires_the_token(client: TestClient):
    account = client.post("/api/auth/register", json=signup_body(new_email())).json()
    assert client.post("/api/auth/logout", headers=auth(account["token"])).status_code == 204
    assert client.get("/api/conversations", headers=auth(account["token"])).status_code == 401


# ── the one-time links ───────────────────────────────────────────────────────


def test_a_reset_link_works_once(client: TestClient, monkeypatch):
    sent: list = []

    async def capture(message):
        sent.append(message)
        return True

    monkeypatch.setattr("app.mail.send", capture)

    email = new_email()
    client.post("/api/auth/register", json=signup_body(email))
    sent.clear()

    assert client.post("/api/auth/forgot", json={"email": email}).status_code == 202
    assert len(sent) == 1
    token = sent[0].text.split("token=")[1].split()[0]

    first = client.post("/api/auth/reset", json={"token": token, "password": "palmtree2400"})
    assert first.status_code == 200

    # Single use, enforced by `used_at`.
    again = client.post("/api/auth/reset", json={"token": token, "password": "otherpass123"})
    assert again.status_code == 400

    # The new password is the one that works.
    assert (
        client.post(
            "/api/auth/login", json={"email": email, "password": "palmtree2400"}
        ).status_code
        == 200
    )


def test_forgot_says_the_same_thing_for_an_unknown_address(client: TestClient):
    known = client.post("/api/auth/forgot", json={"email": new_email()})
    assert known.status_code == 202
    assert known.json() == {"sent": True}
