"""Rate limiting for the endpoints that spend money."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.auth import Principal, chat_principal, client_ip, hash_ip
from app.config import get_settings


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int


class SlidingWindowLimiter:
    """Hits per (bucket, caller) inside a moving window. The voice limiter wraps this."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, caller: str, *, limit: int, window: int) -> RateDecision:
        now = time.monotonic()
        key = (bucket, caller)

        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()

            if len(hits) >= limit:
                # Room frees up when the oldest hit falls out of the window.
                return RateDecision(False, max(1, int(window - (now - hits[0])) + 1))

            hits.append(now)
            return RateDecision(True, 0)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = SlidingWindowLimiter()


def get_limiter() -> SlidingWindowLimiter:
    return _limiter


def caller_id(request: Request, principal: Principal | None) -> str:
    """Who to count against: the proven identity, else the address."""
    if principal is not None:
        return f"u:{principal.user_id}"
    return f"ip:{hash_ip(client_ip(request))[:32]}"


def _enforce(bucket: str, request: Request, principal: Principal | None, limit: int) -> None:
    settings = get_settings()
    decision = get_limiter().check(
        bucket,
        caller_id(request, principal),
        limit=limit,
        window=settings.chat_rate_window_seconds,
    )
    if decision.allowed:
        return
    raise HTTPException(
        status_code=429,
        # A child reads this.
        detail="You're asking questions faster than I can answer. Wait a moment, then try again.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def graph_rate_limit(request: Request, session_id: str, user_id: str | None) -> None:
    """Meter a graph turn.

    `session_id` is deliberately NOT a key. It arrives in the body of
    `/v2/session` and is signed into the token unread, so metering against it
    let a caller reset their own budget by minting a new token with a different
    one -- the bucket was keyed on the value the caller chooses. It stays in the
    signature because the caller passes it and because a future keyed-on-server
    -minted-id scheme would want it, but a client-controlled string cannot be
    the thing that counts requests.

    Falling through to the address instead does not lump a school behind one
    NAT into a single bucket: a visitor who has called `/api/auth/anonymous`
    carries a real `sub`, so `u:` applies to them. Only a caller with no
    account at all shares the address bucket, which is the abuse case.
    """
    settings = get_settings()
    if user_id:
        caller = f"u:{user_id}"
    else:
        caller = f"ip:{hash_ip(client_ip(request))[:32]}"

    decision = get_limiter().check(
        "chat",
        caller,
        limit=settings.chat_messages_per_window,
        window=settings.chat_rate_window_seconds,
    )
    if decision.allowed:
        return
    raise HTTPException(
        status_code=429,
        detail="You're asking questions faster than I can answer. Wait a moment, then try again.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def session_mint_rate_limit(request: Request) -> None:
    """Meter `/v2/session`, which had no limit of any kind.

    Minting is cheap but not free -- each call reads the account, derives
    claims and signs a token -- and an unmetered mint endpoint is also the
    supply of tokens for everything downstream that IS metered.

    Keyed on the address on purpose, including for a signed-in caller: the
    thing being limited is how fast tokens can be produced from one place, not
    how busy one account is.
    """
    settings = get_settings()
    decision = get_limiter().check(
        "session",
        f"ip:{hash_ip(client_ip(request))[:32]}",
        limit=settings.graph_sessions_per_window,
        window=settings.chat_rate_window_seconds,
    )
    if decision.allowed:
        return
    raise HTTPException(
        status_code=429,
        detail="Too many sessions started from here. Wait a moment, then try again.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


async def title_rate_limit(
    request: Request, principal: Principal | None = Depends(chat_principal)
) -> Principal:
    """Meter a title request, and require an identity for it."""
    if principal is None:
        raise HTTPException(status_code=401, detail="A valid session is required.")
    _enforce("title", request, principal, get_settings().title_requests_per_window)
    return principal
