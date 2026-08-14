"""The two links an email can carry, and where each one is redeemable.

`_redeem` matches on the token's PURPOSE as well as its hash, and nothing
tested that. Both email links were broken as a result, in opposite ways:

  - the confirm-your-email link landed on `/verify`, which called
    `signin-link/redeem` -- a `purpose="verify"` token against a
    `purpose="signin_link"` lookup, so it missed every time and the reader was
    told "That link has been used", which was not true.
  - the passwordless sign-in link landed on `/signin?token=…`, whose
    `validateSearch` dropped `token` entirely, so the fifteen-minute token was
    never presented to anything at all.

`POST /api/auth/verify` existed the whole time and had no caller.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.db import database_enabled  # noqa: E402
from app.main import app  # noqa: E402

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not database_enabled(), reason="needs a database"),
]

STRONG = "seaview7392pass"


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _register(client: TestClient) -> str:
    """An account, and its id."""
    email = f"links.{uuid.uuid4().hex[:10]}@ecse.kn"
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": STRONG,
            "role": "guardian",
            "first_name": "Amara",
            "last_name": "Tester",
            # Comfortably adult: `_role_problem` refuses a guardian who is not.
            "date_of_birth": "1988-06-10",
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["user_id"]


async def _issue_for(user_id: str, purpose: str) -> str:
    """A real one-time token of the given purpose, straight from the module."""
    from sqlalchemy import select

    from app.accounts import _issue
    from app.db import session
    from app.db.models import User

    async with session() as db:
        user = (
            await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        ).scalar_one()
        token = await _issue(db, user, purpose)
        await db.commit()
    return token


@pytest.mark.asyncio
async def test_a_verify_token_is_redeemable_where_the_email_sends_it(client):
    """`/verify` posts here now. It used to post to the sign-in endpoint."""
    user_id = _register(client)
    token = await _issue_for(user_id, "verify")

    response = client.post("/api/auth/verify", json={"token": token})

    assert response.status_code == 200, response.text
    assert response.json()["token"]


@pytest.mark.asyncio
async def test_a_verify_token_is_refused_by_the_sign_in_endpoint(client):
    """
    The exact shape of the bug, pinned.

    This is what `/verify` was doing, and why confirming an address was
    impossible: right token, wrong door.
    """
    user_id = _register(client)
    token = await _issue_for(user_id, "verify")

    response = client.post("/api/auth/signin-link/redeem", json={"token": token})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_a_sign_in_token_is_redeemable_and_single_use(client):
    """`/signin?token=…` presents this now; it used to discard it."""
    user_id = _register(client)
    token = await _issue_for(user_id, "signin_link")

    first = client.post("/api/auth/signin-link/redeem", json={"token": token})
    assert first.status_code == 200, first.text

    again = client.post("/api/auth/signin-link/redeem", json={"token": token})
    assert again.status_code == 400, "a one-time token was accepted twice"


@pytest.mark.asyncio
async def test_a_sign_in_token_is_refused_by_the_verify_endpoint(client):
    """The other direction, so neither door is a way into the other."""
    user_id = _register(client)
    token = await _issue_for(user_id, "signin_link")

    response = client.post("/api/auth/verify", json={"token": token})

    assert response.status_code == 400
