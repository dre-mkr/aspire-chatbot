"""Who is asking, proved rather than asserted.

This replaces the header-principal model in 0005, which read an
`X-Aspire-Device` value straight off the request and treated it as identity.
That was an IDOR. The device id is not a secret: it is sent on every request,
stored in the browser, and guessable in principle -- so anyone holding another
person's went straight to their conversations.

The rule this module exists to enforce, stated once:

    **A device id seeds the creation of an anonymous identity. It is never
    accepted as proof of one.**

Concretely, nothing here looks a user up by `device_id`. `POST
/api/auth/anonymous` always creates a NEW row, even when the caller presents a
device id that already exists, because the alternative -- "hand me a device id
and I will hand you a session for whoever owns it" -- is precisely the hole
being closed. `device_id` is stored for abuse investigation and nothing else.

Authorisation goes through a signed token and only a signed token.

## Tokens

A JWT signed with `SESSION_SECRET`, carrying the user's id, their account type,
and the `session_epoch` it was minted under. Revocation needs no denylist and no
shared cache: bumping a user's epoch refuses every token already issued for
them, which is what claiming an anonymous identity and signing out both do.

Short-lived, and refreshed by the client well before expiry. Expiry mid-stream
must never interrupt a reply, so `/chat` and `/chat/stream` accept a token that
has recently expired -- see `GRACE`. A read endpoint does not.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
#: How long a session lasts before the client must refresh it.
TOKEN_TTL = timedelta(days=30)
#: How long past expiry a token still satisfies the chat endpoints.
#:
#: A reply can take a minute; a token expiring during one must not turn into an
#: error the reader sees. Read endpoints get no grace -- they can simply be
#: retried after a refresh.
GRACE = timedelta(minutes=10)

ACCOUNT_ANONYMOUS = "anonymous"
ACCOUNT_REGISTERED = "registered"


@dataclass(frozen=True, slots=True)
class Principal:
    """A verified caller. Only ever produced by `_decode`."""

    user_id: uuid.UUID
    account_type: str
    session_epoch: int

    @property
    def is_anonymous(self) -> bool:
        return self.account_type == ACCOUNT_ANONYMOUS


#: Below this, HMAC-SHA256 offers less than its nominal strength (RFC 7518 3.2).
MIN_SECRET_BYTES = 32


def _secret() -> str:
    settings = get_settings()
    secret = getattr(settings, "session_secret", None)
    if not secret:
        # Refused rather than defaulted. A signing key with a fallback value is
        # a signing key an attacker also has.
        raise RuntimeError(
            "SESSION_SECRET is not set. Sessions cannot be signed without it."
        )
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        # The presence check above is not the strength check. A short key is
        # accepted by every JWT library and signs perfectly valid tokens, so
        # nothing downstream would ever complain -- and this key also feeds
        # `hash_ip`, so a weak one makes the address pseudonymisation weak too.
        # Refused at the same point and in the same way as an absent one.
        raise RuntimeError(
            f"SESSION_SECRET is {len(secret.encode('utf-8'))} bytes; it must be at "
            f"least {MIN_SECRET_BYTES}. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return secret


def mint_token(user_id: uuid.UUID, account_type: str, session_epoch: int) -> str:
    """A signed session for this identity."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "typ": account_type,
            "epo": session_epoch,
            "iat": int(now.timestamp()),
            "exp": int((now + TOKEN_TTL).timestamp()),
            "jti": uuid.uuid4().hex,
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def _decode(token: str, *, grace: timedelta = timedelta(0)) -> Principal | None:
    """Verify a token and return who it is for, or None.

    Returns None for every failure -- bad signature, wrong algorithm, expired,
    malformed. The caller decides whether that is a 401 or simply "no identity";
    it must never be told which of those went wrong, because the difference is
    only useful to somebody probing.
    """
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            leeway=grace,
            options={"require": ["sub", "typ", "epo", "exp"]},
        )
        return Principal(
            user_id=uuid.UUID(claims["sub"]),
            account_type=str(claims["typ"]),
            session_epoch=int(claims["epo"]),
        )
    except Exception:
        return None


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def optional_principal(
    authorization: str | None = Header(default=None),
) -> Principal | None:
    """The caller, or None if they presented nothing valid.

    None is a legitimate answer for the chat endpoints: asking a question has
    never required identifying yourself and must not start to. It is not a
    legitimate answer for anything that reads a person's own records.
    """
    token = _bearer(authorization)
    return _decode(token) if token else None


async def chat_principal(
    authorization: str | None = Header(default=None),
) -> Principal | None:
    """As above, but tolerant of a token that expired moments ago.

    A session ending mid-reply is our problem to solve silently, not an error to
    show somebody halfway through an answer. The client refreshes in the
    background; this keeps the turn alive while it does.
    """
    token = _bearer(authorization)
    return _decode(token, grace=GRACE) if token else None


async def require_principal(
    principal: Principal | None = Depends(optional_principal),
) -> Principal:
    """A verified caller, or 401. Every user-scoped read goes through this."""
    if principal is None:
        raise HTTPException(status_code=401, detail="A valid session is required.")
    return principal


# ── passwords ────────────────────────────────────────────────────────────────

#: bcrypt truncates silently at 72 bytes, which would make two different long
#: passwords equivalent. Rejected rather than truncated.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 10


def password_problem(password: str) -> str | None:
    """Why this password is not acceptable, or None.

    Length first and length mostly. Composition rules push people towards
    `Password1!` and away from the long ordinary phrases that are actually hard
    to guess, so this asks for length and refuses only the genuinely common.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "That password is too long. Use 72 characters or fewer."
    if password.lower() in _COMMON:
        return "That password is too easy to guess. Try something less common."
    return None


_COMMON = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "1234567890",
        "qwertyuiop",
        "letmein123",
        "iloveyou1",
        "aspire1234",
    }
)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time where it matters, and never short-circuits on a missing hash.

    An account with no password (an anonymous row, or one that only ever signed
    in another way) must cost the same to probe as a wrong password, or the
    timing says which addresses exist.
    """
    if not password_hash:
        bcrypt.checkpw(b"x", bcrypt.gensalt())
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# ── request context ──────────────────────────────────────────────────────────


def client_ip(request: Request) -> str:
    """The caller's address, trusting the proxy only for its last hop.

    `X-Forwarded-For` is client-controlled except for the entry the edge appends,
    so the rightmost value is the only one worth anything. Getting this wrong
    makes every per-IP limit trivially evadable by sending a header.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def hash_ip(ip: str) -> str:
    """A stable, non-reversible label for an address.

    Enough to see that one source opened four hundred sessions; not a record of
    where a child lives. Keyed with the signing secret so the hashes cannot be
    reversed with a rainbow table over the whole IPv4 space, which is small.
    """
    return hmac.new(_secret().encode("utf-8"), ip.encode("utf-8"), hashlib.sha256).hexdigest()
