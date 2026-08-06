"""Rate limiting for the endpoints that spend money.

`/chat`, `/chat/stream` and `/api/title` each cost at least one model call, and
until now none of them was metered at all. The only limits in the service were
anonymous *session creation* and the voice layer, so a single caller could spend
the programme's budget as fast as the network allowed -- and `/api/title` did not
even require an identity.

## Why in-process rather than Valkey

Two reasons, and both are specific to this deployment rather than general
advice.

The API runs `--workers 1` by design (conversation memory is an in-process
`InMemorySaver`), so a per-process window IS the whole service's window. There is
no second worker for the count to be split across.

And the Valkey instance is shared with an unrelated application, with no memory
ceiling and `noeviction` set. The existing Valkey-backed limiter in `sessions.py`
also fails OPEN when the cache is unreachable -- which means the control
disappears exactly when the system is under the pressure that would cause someone
to reach for it. An in-process counter cannot fail open, because there is nothing
to be unreachable.

The tradeoff is honest and worth stating: the window resets on deploy or crash.
That is acceptable for abuse dampening on a single-worker service. It would not
be acceptable as a billing control, and if this ever runs multi-worker the
counters must move to Valkey *and* be made to fail closed.

## What identifies a caller

The signed principal when there is one, falling back to a keyed hash of the
client address. Anonymous questioning is a supported path and must stay one, so
the fallback has to work -- but it means the limit for unauthenticated callers is
per-address, and an address is shared by a school.  The per-caller limits below
are set with that in mind: generous enough for a classroom, tight enough that a
script is noticed.
"""

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
    """Same algorithm as the voice limiter, without its settings coupling.

    Deliberately not shared code with `app/voice/limiter.py`: that one is bound
    to `VoiceSettings` and its own bucket names, and merging them would make one
    module answer to two configs for the sake of thirty lines.
    """

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
    """Who to count against: the proven identity, else the address.

    Hashed either way so the counter keys carry no address and nothing
    identifying reaches a log or a traceback.
    """
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
        # A child reads this. It says what happened and what to do, and nothing
        # about buckets, windows or quotas.
        detail="You're asking questions faster than I can answer. Wait a moment, then try again.",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


async def chat_rate_limit(
    request: Request, principal: Principal | None = Depends(chat_principal)
) -> Principal | None:
    """Meter a message send, and hand the principal on to the route.

    Returned rather than discarded so the route depends on this instead of
    resolving `chat_principal` a second time.
    """
    _enforce("chat", request, principal, get_settings().chat_messages_per_window)
    return principal


def graph_rate_limit(request: Request, session_id: str, user_id: str | None) -> None:
    """Meter a graph turn. Raises 429, or returns.

    Not a FastAPI dependency, because the identity it counts against is inside
    the graph session token and that is decoded in the route body rather than
    injected. Same limiter, same bucket and same window as the rest of the chat
    surface -- deliberately the same bucket, so a caller cannot double their
    budget by having two kinds of token.

    Counted against the signed user id when there is one, then the session id,
    then the address. The session id is the middle rung and it matters: an
    anonymous reader has a signed session but no account, and metering them by
    address would put a whole school on one counter.
    """
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
    """Meter a title request, and require an identity for it.

    `/api/title` is the only endpoint in the product that required no identity at
    all, while accepting up to 28,000 characters and spending a model call per
    request -- the cheapest thing here to abuse. Anonymous identities are free and
    the client already holds one before it can have an answer to name, so
    requiring a session costs a real user nothing.
    """
    if principal is None:
        raise HTTPException(status_code=401, detail="A valid session is required.")
    _enforce("title", request, principal, get_settings().title_requests_per_window)
    return principal
