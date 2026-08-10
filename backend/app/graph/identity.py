"""The signed session token the graph trusts, and nothing else."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.auth import ALGORITHM, GRACE, _secret

logger = logging.getLogger(__name__)

#: Distinguishes this from the account token minted by `auth.mint_token`.
TOKEN_TYPE = "aspire.session"

#: Matches `auth.TOKEN_TTL`.
TOKEN_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class SessionClaims:
    """A verified session."""

    session_id: str
    user_id: str | None
    device_id: str
    persona: str
    age_band: str
    account_status: str
    locale: str

    @property
    def is_anonymous(self) -> bool:
        return self.user_id is None


def mint_session_token(
    *,
    session_id: str,
    user_id: str | None,
    device_id: str,
    persona: str,
    age_band: str,
    account_status: str,
    locale: str = "en",
    ttl: timedelta = TOKEN_TTL,
) -> str:
    """Sign a session's identity."""
    now = datetime.now(timezone.utc)
    claims = {
        "typ": TOKEN_TYPE,
        "sid": session_id,
        "did": device_id,
        "per": persona,
        "band": age_band,
        "acc": account_status,
        "loc": locale,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    # OMITTED rather than set to null for an anonymous session.
    if user_id:
        claims["sub"] = str(user_id)

    return jwt.encode(claims, _secret(), algorithm=ALGORITHM)


def decode_session_token(token: str | None, *, grace: timedelta = GRACE) -> SessionClaims | None:
    """Verify a token and return its claims, or None."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            leeway=grace,
            options={"require": ["typ", "sid", "did", "per", "band", "acc", "exp"]},
        )
    except Exception:
        return None

    if claims.get("typ") != TOKEN_TYPE:
        # An account token presented where a session token belongs.
        return None

    user_id = claims.get("sub")
    return SessionClaims(
        session_id=str(claims["sid"]),
        user_id=str(user_id) if user_id else None,
        device_id=str(claims["did"]),
        persona=str(claims["per"]),
        age_band=str(claims["band"]),
        account_status=str(claims["acc"]),
        locale=str(claims.get("loc") or "en"),
    )


#: Body fields a client is never allowed to set, because each of them is an identity claim the server mints.
CLIENT_FORBIDDEN_FIELDS: tuple[str, ...] = (
    "persona",
    "age_band",
    "account_status",
    "user_id",
    "session_id",
    "device_id",
    "allowed_agents",
)
