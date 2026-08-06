"""The session token: what it carries, and what it refuses to carry.

The first test in this file is a regression for a live outage-class bug, and it
is worth reading before the others.

`mint_session_token` set `"sub": user_id` unconditionally, so an anonymous
session -- no account, which is the DEFAULT path and the one a child on a school
tablet takes -- was signed with `"sub": null`. Minting succeeded. Decoding then
raised `InvalidSubjectError` (RFC 7519 requires `sub` to be a StringOrURI, and
PyJWT enforces it), `decode_session_token` swallowed it into its blanket `None`,
and the very next request answered `unauthenticated`.

Both halves looked correct in isolation, which is why nothing caught it: the
mint returned a well-formed JWT and the decode failed closed exactly as designed.
Only a round trip shows it.
"""

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
    """The claims the access matrix reads must survive the wire exactly.

    A band that decoded to something else would not fail loudly -- it would
    route a fourteen-year-old to a different agent set, quietly.
    """
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
    """The two realms share a signing key and must not share a door.

    `auth.mint_token` proves who somebody is. It carries no age band, so
    accepting one here would mean inventing one -- which is the single worst
    thing this module could do.
    """
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
    """A claim the server mints must be one `hydrate` refuses from a body.

    The two lists drifting apart is how a new claim becomes spoofable: it would
    be signed by the server AND accepted from the request, and the request wins
    wherever the body is read first.
    """
    minted = {"persona", "age_band", "account_status", "user_id", "session_id", "device_id"}
    assert minted <= set(CLIENT_FORBIDDEN_FIELDS)
