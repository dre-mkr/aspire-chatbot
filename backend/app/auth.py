"""Who is asking, proved rather than asserted."""

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
TOKEN_TTL = timedelta(days=7)
#: How long past expiry a token still satisfies the chat endpoints.
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
        # Refused rather than defaulted.
        raise RuntimeError(
            "SESSION_SECRET is not set. Sessions cannot be signed without it."
        )
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        # The presence check above is not the strength check.
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
            # Kept, and deliberately not recorded -- see TOKEN_TTL.
            "jti": uuid.uuid4().hex,
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def _decode(token: str, *, grace: timedelta = timedelta(0)) -> Principal | None:
    """Verify a token and return who it is for, or None."""
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
    """The caller, or None if they presented nothing valid."""
    token = _bearer(authorization)
    return _decode(token) if token else None


async def chat_principal(
    authorization: str | None = Header(default=None),
) -> Principal | None:
    """As above, but tolerant of a token that expired moments ago."""
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

#: bcrypt truncates silently at 72 bytes, which would make two different long passwords equivalent.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 10


def password_problem(password: str) -> str | None:
    """Why this password is not acceptable, or None."""
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
    """Constant-time where it matters, and never short-circuits on a missing hash."""
    if not password_hash:
        bcrypt.checkpw(b"x", bcrypt.gensalt())
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# ── request context ──────────────────────────────────────────────────────────


def client_ip(request: Request) -> str:
    """The caller's address, trusting the proxy only for its last hop."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def hash_ip(ip: str) -> str:
    """A stable, non-reversible label for an address."""
    return hmac.new(_secret().encode("utf-8"), ip.encode("utf-8"), hashlib.sha256).hexdigest()
