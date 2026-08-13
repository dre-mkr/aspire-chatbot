"""The session token: what it carries, and what it refuses to carry."""

from __future__ import annotations

import uuid

import pytest

from app.graph.identity import (
    CLIENT_FORBIDDEN_FIELDS,
    TOKEN_TYPE,
    decode_session_token,
    mint_session_token,
)


def _mint(**over):
    fields = {
        "session_id": "s-1",
        "user_id": None,
        "device_id": "d-1",
        "persona": "stella",
        "age_band": "5-8",
        "account_status": "prospect",
        "locale": "en",
    }
    fields.update(over)
    return mint_session_token(**fields)


def test_an_anonymous_session_survives_a_round_trip():
    """The regression. Asking a question has never required an account."""
    claims = decode_session_token(_mint(user_id=None))

    assert claims is not None, (
        "an anonymous session token decoded to None -- every unauthenticated "
        "caller would be told to sign in again on their first message"
    )
    assert claims.user_id is None
    assert claims.session_id == "s-1"


def test_a_signed_in_session_carries_its_user():
    user_id = str(uuid.uuid4())
    claims = decode_session_token(_mint(user_id=user_id))

    assert claims is not None
    assert claims.user_id == user_id


@pytest.mark.parametrize(
    ("band", "persona", "status"),
    [
        ("5-8", "stella", "prospect"),
        ("9-12", "orion", "beneficiary"),
        ("13-15", "orion", "applicant"),
        ("16-18", "orion", "beneficiary"),
        ("adult", "aurora", "guardian"),
    ],
)
def test_every_band_round_trips(band: str, persona: str, status: str):
    """The claims the access matrix reads must survive the wire exactly."""
    claims = decode_session_token(
        _mint(age_band=band, persona=persona, account_status=status)
    )

    assert claims is not None
    assert (claims.age_band, claims.persona, claims.account_status) == (
        band,
        persona,
        status,
    )


def test_an_account_token_is_not_a_session_token():
    """The two realms share a signing key and must not share a door."""
    from app.auth import ACCOUNT_ANONYMOUS, mint_token

    account = mint_token(uuid.uuid4(), ACCOUNT_ANONYMOUS, 1)
    assert decode_session_token(account) is None


def test_rubbish_decodes_to_nothing():
    for token in (None, "", "not-a-jwt", "a.b.c"):
        assert decode_session_token(token) is None


def test_the_token_type_is_pinned():
    """A rename here would silently invalidate every session in flight."""
    assert TOKEN_TYPE == "aspire.session"


def test_every_minted_claim_is_a_forbidden_body_field():
    """A claim the server mints must be one `hydrate` refuses from a body."""
    minted = {"persona", "age_band", "account_status", "user_id", "session_id", "device_id"}
    assert minted <= set(CLIENT_FORBIDDEN_FIELDS)


class TestProvenIdentityCrossesTheToken:
    """`user_id` cannot answer "is this a member": a signed-out visitor has one too."""

    def test_an_unproven_session_round_trips_as_anonymous(self):
        token = mint_session_token(
            session_id="s-1",
            user_id="0f8e0f57-0000-4000-8000-000000000000",
            device_id="d-1",
            persona="aurora",
            age_band="adult",
            account_status="prospect",
            identity_proven=False,
        )
        claims = decode_session_token(token)
        assert claims is not None
        assert claims.identity_proven is False
        # It still carries the id, so the visitor's chats remain claimable.
        assert claims.user_id == "0f8e0f57-0000-4000-8000-000000000000"
        assert claims.is_anonymous is True

    def test_a_member_session_is_proven(self):
        token = mint_session_token(
            session_id="s-2",
            user_id="0f8e0f57-0000-4000-8000-000000000001",
            device_id="d-1",
            persona="aurora",
            age_band="adult",
            account_status="guardian",
        )
        claims = decode_session_token(token)
        assert claims is not None
        assert claims.identity_proven is True
        assert claims.is_anonymous is False
