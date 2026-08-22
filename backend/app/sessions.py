"""Getting a session without having an account."""

from __future__ import annotations

import logging
import os
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import cache
from app.auth import (
    ACCOUNT_ANONYMOUS,
    Principal,
    TOKEN_TTL,
    client_ip,
    hash_ip,
    mint_token,
    optional_principal,
)
from app.config import get_settings
from app.db import database_enabled, session
from app.db.models import User

logger = logging.getLogger(__name__)


async def _record_cap_bypass() -> None:
    """Count a session admitted without its cap being checked."""
    client = cache.get_client()
    if client is None:
        return
    try:
        key = f"{cache.namespace()}session-cap-bypass:{int(time.time()) // 3600}"
        await client.incr(key)
        await client.expire(key, 7 * 3600)
    except Exception:
        # Accounting must never be the reason a session is refused.
        pass

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: A client-minted id: a UUID, or the `t-<base36>-<base36>` fallback used without randomUUID.
_DEVICE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class AnonymousRequest(BaseModel):
    #: Optional.
    device_id: str | None = Field(default=None, max_length=64)


class SessionResponse(BaseModel):
    token: str
    user_id: uuid.UUID
    account_type: str
    email: str | None = None
    display_name: str | None = None
    #: The given name the reader typed at sign-up, on its own.
    #:
    #: Sent SEPARATELY from `display_name`, which is `first last` joined and is
    #: whatever the reader put in those boxes. The client greets a returning
    #: reader by name, and deriving that name by splitting the display name is a
    #: guess: "T. Onu" yields "T.", an organisation account yields a shouted
    #: acronym, and an email-prefix display name yields an address. The product
    #: then addresses somebody by a name they do not have, in the first line
    #: they read.
    #:
    #: The column has been on `users` since sign-up was written. It was simply
    #: never returned, so the client had nothing to use but the joined string.
    first_name: str | None = None
    avatar_url: str | None = None
    expires_in: int
    #: Who the account is for, as chosen at sign-up.
    role: str = "participant"
    #: The persona this account resolves to, so the client can show the right one at once.
    persona: str = "stella"
    #: The band that persona answers at, which is NOT derivable from the persona.
    #:
    #: `stella` carries two voices -- Skye at 5-8 and Kaleb at 9-12 -- and the
    #: client had no way to tell them apart, so both readers were shown the same
    #: face. The band is computed here already, three lines down, to choose the
    #: persona; it was simply never returned.
    age_band: str = "5-8"


def to_session(user: User, token: str) -> SessionResponse:
    from app.graph.account import YOUNGEST_BAND, band_for, persona_for

    # `band_for` now reads a missing date of birth as the youngest band, so this
    # branch no longer has to correct it -- it is kept for the role, which an
    # anonymous row must not carry over from anywhere else. The two endpoints
    # that describe a signed-out visitor used to disagree here; they no longer do.
    if user.account_type == ACCOUNT_ANONYMOUS:
        band, role = YOUNGEST_BAND, "participant"
    else:
        band = band_for(user.date_of_birth, is_minor=bool(user.is_minor))
        role = user.role

    return SessionResponse(
        token=token,
        user_id=user.id,
        account_type=user.account_type,
        email=user.email,
        display_name=user.display_name,
        # Anonymous rows have no name and must not borrow one.
        first_name=user.first_name if user.account_type != ACCOUNT_ANONYMOUS else None,
        avatar_url=user.avatar_url,
        expires_in=int(TOKEN_TTL.total_seconds()),
        role=role,
        persona=persona_for(band, role),
        age_band=band,
    )


async def _within_limit(ip: str) -> bool:
    """Whether this address may create another anonymous session this hour."""
    client = cache.get_client()
    if client is None:
        return True

    settings = get_settings()
    # The namespace is overridable so concurrent test runs cannot count against each other.
    prefix = os.environ.get("ASPIRE_CACHE_NAMESPACE", "")
    key = f"aspire:{prefix}anon-sessions:{hash_ip(ip)}"
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 3600)
        return count <= settings.anonymous_sessions_per_ip_per_hour
    except Exception:
        # A deliberate decision: fail OPEN, and make it visible.
        logger.warning("Rate-limit check failed; allowing the session.", exc_info=True)
        await _record_cap_bypass()
        return True


@router.post("/anonymous", response_model=SessionResponse)
async def create_anonymous_session(
    body: AnonymousRequest, request: Request
) -> SessionResponse:
    """A brand-new anonymous identity, and a token proving it."""
    if not database_enabled():
        raise HTTPException(
            status_code=503, detail="Sessions are unavailable. Please try again shortly."
        )

    ip = client_ip(request)
    if not await _within_limit(ip):
        logger.warning("Anonymous session cap reached for %s", hash_ip(ip))
        raise HTTPException(
            status_code=429,
            detail="Too many sessions from this connection. Please try again later.",
        )

    device_id = body.device_id if body.device_id and _DEVICE_RE.match(body.device_id) else None

    async with session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="Sessions are unavailable.")

        # Always a new row. Never a lookup by device_id -- see the module note.
        user = User(
            id=uuid.uuid4(),
            account_type=ACCOUNT_ANONYMOUS,
            device_id=device_id,
            session_epoch=1,
            created_ip_hash=hash_ip(ip),
        )
        db.add(user)
        await db.flush()
        token = mint_token(user.id, user.account_type, user.session_epoch)
        # Enough to investigate a burst and no more: identity, hashed source, hashed device.
        logger.info(
            "anonymous session created user=%s ip_hash=%s device_hash=%s",
            user.id,
            hash_ip(ip)[:12],
            hash_ip(device_id)[:12] if device_id else "none",
        )
        return to_session(user, token)


@router.get("/session", response_model=SessionResponse | None)
async def read_session(
    principal: Principal | None = Depends(optional_principal),
) -> SessionResponse | None:
    """Who the caller is, as the server sees them."""
    if principal is None or not database_enabled():
        return None

    async with session() as db:
        if db is None:
            return None
        user = await db.get(User, principal.user_id)
        # A token whose epoch has been superseded is dead: the identity was claimed, or signed out.
        if user is None or user.session_epoch != principal.session_epoch:
            return None
        return to_session(user, "")


async def resolve(principal: Principal | None) -> User | None:
    """The live user behind a verified token, or None."""
    if principal is None or not database_enabled():
        return None
    async with session() as db:
        if db is None:
            return None
        user = await db.get(User, principal.user_id)
        if user is None or user.session_epoch != principal.session_epoch:
            return None
        return user


async def owner_id_for(principal: Principal | None) -> uuid.UUID | None:
    """The id to file records under, or None for a caller with no identity."""
    user = await resolve(principal)
    return user.id if user else None


__all__ = ["router", "select", "to_session", "resolve", "owner_id_for", "SessionResponse"]
