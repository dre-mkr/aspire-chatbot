"""One bounded retry helper, for the calls that leave this process.

Nothing in `app/` retried anything. `tenacity` is installed, as a transitive
dependency, and imported nowhere; the only backoff in the repo was one retry on
the Valkey client. Every model call, every embedding, every reranker round trip
was one attempt and then a refusal -- so a single dropped connection turned a
good answer into "The assistant is temporarily unavailable", which is the
likeliest reading of "The assistant could not be reached" during the 11 Aug
demo.

Only idempotent work belongs here. Asking a model the same question twice is
safe; writing a ticket twice is not.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Attempts in total, not retries after the first.
ATTEMPTS = 3

#: Seconds before the second attempt; doubled for the third.
BACKOFF = 0.4

#: Substrings that mean asking again cannot help. Matched against the exception
#: text because the providers raise their own classes and this module refuses to
#: import six vendor SDKs to name them. A wrong guess here costs one wasted
#: retry, which is the safe direction to be wrong in.
PERMANENT = (
    "invalid_api_key",
    "incorrect api key",
    "does not have access to model",
    "unauthorized",
    "permission",
    "authentication",
    "content_policy",
    "invalid_request_error",
)


def _permanent(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    return any(marker in text for marker in PERMANENT)


async def with_retry(
    call: Callable[[], Awaitable[T]],
    *,
    what: str,
    attempts: int = ATTEMPTS,
    backoff: float = BACKOFF,
) -> T:
    """Run `call`, trying again on a transient failure.

    `what` names the call in the log, because a retry that nobody can see is a
    latency mystery later.
    """
    last: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except asyncio.CancelledError:
            # The reader closed the tab. Not ours to retry.
            raise
        except Exception as error:  # noqa: BLE001 - deliberately broad, see below
            last = error
            if _permanent(error) or attempt == attempts:
                break
            delay = backoff * (2 ** (attempt - 1))
            logger.warning(
                "%s failed (attempt %d of %d): %s: %s. Retrying in %.1fs.",
                what,
                attempt,
                attempts,
                type(error).__name__,
                error,
                delay,
            )
            await asyncio.sleep(delay)

    assert last is not None
    logger.warning(
        "%s failed after %d attempt(s): %s: %s",
        what,
        attempts if not _permanent(last) else 1,
        type(last).__name__,
        last,
    )
    raise last


def retrying(what: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """`with_retry` as a decorator, for the invoke helpers."""

    def wrap(function: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        async def called(*args: Any, **kwargs: Any) -> Any:
            return await with_retry(lambda: function(*args, **kwargs), what=what)

        called.__name__ = getattr(function, "__name__", "called")
        called.__doc__ = function.__doc__
        return called

    return wrap
