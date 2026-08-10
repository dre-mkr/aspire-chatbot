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
    """Same algorithm as the voice limiter, without its settings coupling."""

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


async def chat_rate_limit(
    request: Request, principal: Principal | None = Depends(chat_principal)
) -> Principal | None:
    """Meter a message send, and hand the principal on to the route."""
    _enforce("chat", request, principal, get_settings().chat_messages_per_window)
    return principal


def graph_rate_limit(request: Request, session_id: str, user_id: str | None) -> None:
    """Meter a graph turn."""
    settings = get_settings()
    if user_id:
        caller = f"u:{user_id}"
    elif session_id:
        caller = f"s:{session_id}"
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


async def title_rate_limit(
    request: Request, principal: Principal | None = Depends(chat_principal)
) -> Principal:
    """Meter a title request, and require an identity for it."""
    if principal is None:
        raise HTTPException(status_code=401, detail="A valid session is required.")
    _enforce("title", request, principal, get_settings().title_requests_per_window)
    return principal
