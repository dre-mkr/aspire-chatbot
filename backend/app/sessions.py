"""Getting a session without having an account.

A first-time visitor must be able to open the app and ask a question. No modal,
no interstitial, no "create an account to continue". So the very first thing the
client does is come here for an identity, and that identity is a real row that
owns real conversations.

## The one rule

`POST /api/auth/anonymous` **always creates a new user**, even when the caller
sends a `device_id` that already exists in the table.

That is not a missed optimisation. Looking the device up and returning a session
for whoever owns it would mean "hand me a device id and I will hand you their
conversations", which is the exact hole this whole change closes. The device id
is written down for abuse investigation and is never read back to authenticate.

The consequence is worth stating plainly: a browser that loses its token loses
its anonymous history, even if it still has the device id. That is the honest
cost of not having a credential, and it is what registering fixes.

## Abuse

Anonymous access removes the usual lever -- there is no address to ban -- so the
limit is the lever. Sessions are capped per address per hour, counted in Valkey
where it is available and permitted where it is not: a broken cache must not
lock everybody out of a product whose whole point is being open.
"""

from __future__ import annotations

import logging
import os
import re
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

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: A client-minted id: a UUID, or the `t-<base36>-<base36>` fallback used where
#: `crypto.randomUUID` is unavailable (it needs a secure context).
_DEVICE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class AnonymousRequest(BaseModel):
    #: Optional. The session does not depend on it and is not keyed by it; it is
    #: recorded so that a burst of sessions can be attributed to one browser.
    device_id: str | None = Field(default=None, max_length=64)


class SessionResponse(BaseModel):
    token: str
    user_id: uuid.UUID
    account_type: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    expires_in: int


def to_session(user: User, token: str) -> SessionResponse:
    return SessionResponse(
        token=token,
        user_id=user.id,
        account_type=user.account_type,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        expires_in=int(TOKEN_TTL.total_seconds()),
    )


async def _within_limit(ip: str) -> bool:
    """Whether this address may create another anonymous session this hour.

    Fails open. A cache outage must not stop a child opening the app; the cap
    exists to blunt scripted abuse, and the cost of missing some of it for an
    hour is far below the cost of refusing everybody.
    """
    client = cache.get_client()
    if client is None:
        return True

    settings = get_settings()
    # The namespace is overridable so concurrent test runs cannot count against
    # each other. Two pytest runs overlapping on the shared Valkey made this
    # cap's own test fail while passing in isolation (P11-001), and CI now runs
    # pytest on every push -- so two PRs would flake each other on an abuse
    # control, which reads as a real regression and is not. Unset in production,
    # where the plain namespace is what is wanted.
    prefix = os.environ.get("ASPIRE_CACHE_NAMESPACE", "")
    key = f"aspire:{prefix}anon-sessions:{hash_ip(ip)}"
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 3600)
        return count <= settings.anonymous_sessions_per_ip_per_hour
    except Exception:
        logger.warning("Rate-limit check failed; allowing the session.", exc_info=True)
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
        # Enough to investigate a burst, and no more: which identity, from which
        # (hashed) source, seeded by which browser. No address, no user agent.
        logger.info(
            "anonymous session created user=%s ip_hash=%s device=%s",
            user.id,
            hash_ip(ip)[:12],
            (device_id or "none")[:8],
        )
        return to_session(user, token)


@router.get("/session", response_model=SessionResponse | None)
async def read_session(
    principal: Principal | None = Depends(optional_principal),
) -> SessionResponse | None:
    """Who the caller is, as the server sees them.

    Returns null rather than 401 for a missing or expired token: "you are nobody
    yet" is a normal state for this product, not an error. The client uses it to
    decide whether to ask for an anonymous session, and to settle the auth
    control's state before first paint so it never renders one state and swaps.
    """
    if principal is None or not database_enabled():
        return None

    async with session() as db:
        if db is None:
            return None
        user = await db.get(User, principal.user_id)
        # A token whose epoch has been superseded is dead: the identity was
        # claimed, or signed out. Refused here rather than anywhere else, so
        # every route that resolves a session gets the check for free.
        if user is None or user.session_epoch != principal.session_epoch:
            return None
        return to_session(user, "")


async def resolve(principal: Principal | None) -> User | None:
    """The live user behind a verified token, or None.

    The epoch check is the revocation mechanism: claiming an anonymous identity
    and signing out both bump it, which retires every token already issued
    without a denylist to maintain.
    """
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
