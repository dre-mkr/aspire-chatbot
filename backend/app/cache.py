"""Valkey: the response cache, and the connection the queue shares.

Valkey implements the Redis 7.2 command set, so redis-py and arq are unchanged
from their Redis usage — there is no Valkey-specific client and none is wanted.

This is a NORMALIZED EXACT-MATCH cache, not a semantic one. Semantic caching
needs the valkey-search module for the FT.* commands, which is a deployment
dependency, and the traffic here does not justify it: the knowledge base is 332
rows of programme FAQ and the repeat questions are near-identical strings, which
normalisation already collapses. Anything genuinely needing similarity should
ask pgvector, which is right there and exact about what it is doing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import redis.asyncio as redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from app.config import get_settings

logger = logging.getLogger(__name__)

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalise(query: str) -> str:
    """Collapse the trivial ways of writing the same question.

    Casefold rather than lower: it is the Unicode-correct operation, and this
    text arrives in three languages. NFKC first, so visually identical strings
    typed on different keyboards normalise together.

    Accents are deliberately KEPT. Stripping them would fold "años" into "anos",
    and in Spanish that is a different word — a cache that answers the wrong
    question quickly is worse than one that misses.
    """
    text = unicodedata.normalize("NFKC", query)
    text = _PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text)
    return text.casefold().strip()


@lru_cache(maxsize=1)
def corpus_fingerprint() -> str:
    """A short digest of the knowledge base the answers were built from.

    Part of every cache key, so re-ingesting an edited corpus retires every
    answer derived from the old one atomically. Without it a cached answer
    outlives the fact it was based on for up to RESPONSE_CACHE_TTL_SECONDS --
    six hours by default, on a government FAQ where a correction is usually the
    reason for the edit.

    Cached for the process: the CSV does not change under a running service, and
    ingest is a separate command that restarts it.
    """
    path = get_settings().resolved(get_settings().knowledge_base_csv)
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    except OSError:
        # No corpus to fingerprint is not a reason to stop answering. A constant
        # simply means the cache behaves as it did before this existed.
        logger.warning("Could not fingerprint %s; caching without one.", path)
        return "nocorpus"
    return digest


def namespace() -> str:
    """`aspire:` in production, `aspire:<something>:` under a test run.

    Mirrors the override in `sessions.py`, which exists because two overlapping
    pytest runs shared one Valkey and counted against each other (P11-001). Any
    key this module invents needs the same treatment, or the same flake comes
    back through the metrics instead of the session cap.
    """
    prefix = os.environ.get("ASPIRE_CACHE_NAMESPACE", "")
    return f"aspire:{prefix}"


def cache_key(
    query: str,
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
) -> str:
    """The key for one answer.

    LANGUAGE IS PART OF THE KEY AND IS NOT OPTIONAL. A cached English answer
    served into a Spanish session is the single worst failure this cache can
    have: silent, plausible-looking, and wrong for the person reading it.
    Persona and account status are in for the same reason — they change what the
    assistant is allowed to say, so an answer cached for one must never reach
    another.

    Hashed, so a long question cannot produce an unbounded key and no user text
    leaks into logs or `KEYS` output.
    """
    material = json.dumps(
        {
            "q": normalise(query),
            "lang": (language or "en").lower(),
            "persona": persona or "",
            "status": account_status or "",
            # See `corpus_fingerprint`: an edited knowledge base must not keep
            # serving answers built from the old one.
            "kb": corpus_fingerprint(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    # Namespaced, which it was not until P13-006 -- `namespace()` existed, said
    # "any key this module invents needs the same treatment", and was used by the
    # metrics counters and by nothing else. Answer keys and the lease keys derived
    # from them sat in the shared production namespace, so a pytest run read and
    # wrote the live cache.
    #
    # That was invisible while `/chat/stream` never consulted the cache: tests
    # wrote entries nothing read back. Putting the cache on the transport the
    # client uses made it visible immediately -- `test_streaming.py` started
    # getting real production answers in place of its fake agent's.
    #
    # Changing the key retires every existing entry, which costs one cold turn per
    # distinct question and is the cheapest possible consequence.
    return f"{namespace()}answer:v1:{digest}"


def valkey_url() -> str | None:
    """The configured URL, with `localhost` pinned to IPv4.

    On Windows `localhost` resolves to `::1` before `127.0.0.1`. A Valkey bound
    only to IPv4 -- which is what a default container publish gives you -- leaves
    the IPv6 attempt hanging rather than refusing, and a client with a connect
    timeout gives up before it ever tries the address that works.

    That produced a genuinely confusing split: the response cache connected
    (redis-py sets no connect timeout, so it waited out the dead address) while
    arq timed out against the same server, on the same host, in the same
    process. Pinning the loopback name to the address that actually listens
    removes the difference rather than making one component wait longer.

    Only the bare name is rewritten. Any real host is left exactly as given.
    """
    url = get_settings().valkey_url
    if not url:
        return None
    return url.replace("://localhost:", "://127.0.0.1:").replace(
        "@localhost:", "@127.0.0.1:"
    )


@lru_cache(maxsize=1)
def get_client() -> redis.Redis | None:
    """Process-wide Valkey client, or None when none is configured.

    The timeouts and the retry policy are set EXPLICITLY, and that is the point
    (P2-001). `arq 0.28.0` pins `redis[hiredis]<6`, holding redis-py three
    majors back at 5.3.1 -- and the defaults differ across that gap in ways that
    matter here:

      redis-py 5  no socket timeout at all. That is the defect `valkey_url`
                  above documents working around: a dead address was waited out
                  rather than refused.
      redis-py 8  `socket_timeout` and `socket_connect_timeout` default to 5s,
                  and `retry` defaults to 10 attempts with backoff.

    Ten retries with backoff on a best-effort cache is the dangerous one: it
    turns "Valkey is down" into a multi-second stall on the request path, in a
    component whose entire contract is to degrade into a miss. So the policy is
    written down here rather than inherited, and the day arq widens its pin this
    client behaves identically before and after the upgrade.

    Two connect attempts, then give up. Every caller in this module already
    treats a failure as a miss.
    """
    url = valkey_url()
    if not url:
        return None
    return redis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
        retry=Retry(ExponentialBackoff(cap=0.2, base=0.05), retries=1),
        retry_on_timeout=False,
    )


def cache_enabled() -> bool:
    return get_client() is not None and get_settings().response_cache_enabled


async def get_answer(
    query: str,
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
) -> dict[str, Any] | None:
    """A previously cached answer, or None.

    Never raises. A cache that is down must degrade into a cache miss, because
    the alternative is an outage in a component whose whole job is to be an
    optimisation.
    """
    if not cache_enabled():
        return None

    key = cache_key(
        query, language=language, persona=persona, account_status=account_status
    )
    try:
        raw = await get_client().get(key)
    except Exception:
        logger.warning("Cache read failed; treating as a miss.", exc_info=True)
        return None

    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Discarding malformed cache entry at %s.", key)
        return None


async def put_answer(
    query: str,
    payload: dict[str, Any],
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
) -> None:
    """Cache one answer. Never raises, for the same reason as `get_answer`."""
    if not cache_enabled():
        return

    key = cache_key(
        query, language=language, persona=persona, account_status=account_status
    )
    try:
        await get_client().set(
            key,
            json.dumps(payload, ensure_ascii=False),
            ex=get_settings().response_cache_ttl_seconds,
        )
    except Exception:
        logger.warning("Cache write failed; the answer was still served.", exc_info=True)


# --- Hit-rate accounting ---------------------------------------------------
# Two counters, so the hit rate is measured rather than estimated. Kept in
# Valkey rather than process memory because the number has to survive a restart
# to mean anything over a day.
#
# Windowed, not lifetime. These used to be two bare `INCR`s with no TTL and no
# reset, so `/health` reported a hit rate accumulated since the service was
# first deployed -- a number that cannot answer "is the cache working now",
# because a bad week is invisible behind a good year. They were also, measured
# live, the only two `aspire:*` keys in the instance and the only ones with no
# expiry.
#
# One bucket per hour, each expiring after the window. `stats` sums the buckets
# still alive, so the rate always describes the last few hours and old buckets
# disappear without anything having to remember to delete them.

#: How many hourly buckets make up the reported window.
_WINDOW_HOURS = 6
#: Long enough that the oldest bucket in the window is still readable.
_BUCKET_TTL_SECONDS = (_WINDOW_HOURS + 1) * 3600


def _bucket(hit: bool, hour: int) -> str:
    return f"{namespace()}cache:{'hits' if hit else 'misses'}:{hour}"


def _current_hour() -> int:
    return int(time.time()) // 3600


async def record(hit: bool) -> None:
    if not cache_enabled():
        return
    try:
        key = _bucket(hit, _current_hour())
        pipe = get_client().pipeline()
        pipe.incr(key)
        # Re-set on every write rather than only on creation. `INCR` does not
        # touch the TTL, and a `SET NX` dance to do it once is two round trips
        # to save one cheap command.
        pipe.expire(key, _BUCKET_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        pass  # accounting must never affect the request


async def stats() -> dict[str, float | int | bool]:
    """Hits, misses and the rate over the last `_WINDOW_HOURS`. On /health."""
    if not cache_enabled():
        return {"enabled": False, "hits": 0, "misses": 0, "hit_rate": 0.0, "window_hours": _WINDOW_HOURS}

    hour = _current_hour()
    hours = [hour - offset for offset in range(_WINDOW_HOURS)]
    try:
        values = await get_client().mget(
            [_bucket(True, h) for h in hours] + [_bucket(False, h) for h in hours]
        )
    except Exception:
        return {"enabled": True, "hits": 0, "misses": 0, "hit_rate": 0.0, "window_hours": _WINDOW_HOURS}

    counts = [int(value or 0) for value in values]
    hits = sum(counts[:_WINDOW_HOURS])
    misses = sum(counts[_WINDOW_HOURS:])

    total = hits + misses
    return {
        "enabled": True,
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "window_hours": _WINDOW_HOURS,
    }


# --- Card-start rate -------------------------------------------------------
#
# P8-003: `GAMES_INSTRUCTIONS` (648 tok) and `ELIGIBILITY_INSTRUCTIONS` (331
# tok) are appended to the system prompt on EVERY turn whenever the modules are
# enabled -- 979 tokens, 54% of the fixed 1,800-token overhead, describing
# features most turns never use.
#
# The fix the finding proposes is conditional on a number nobody had: how often
# a card actually starts. Shortening those instructions, or putting the card
# tools behind a router turn, changes model behaviour on the two flows with the
# most test coverage in the product -- so it is not a change to make blind, and
# guessing the rate would be the same mistake in a different place.
#
# This is that number, on the same windowed buckets as the hit rate. When it is
# low, the case for a router turn is made; when it is high, the instructions are
# earning their tokens and the finding resolves as "measured, not worth it".
#
# Note for whoever reads it: with `chat_model` on an `openai:` prefix the static
# system prefix is already cached automatically above 1024 tokens, so the
# marginal cost of these instructions is lower than the raw count suggests.

async def record_turn(started_card: bool) -> None:
    if not cache_enabled():
        return
    try:
        hour = _current_hour()
        pipe = get_client().pipeline()
        for name in ("turns",) + (("cards",) if started_card else ()):
            key = f"{namespace()}{name}:{hour}"
            pipe.incr(key)
            pipe.expire(key, _BUCKET_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        pass


async def card_rate() -> dict[str, float | int]:
    """How many turns started a card, over the reported window."""
    if not cache_enabled():
        return {"turns": 0, "cards": 0, "card_rate": 0.0}
    hour = _current_hour()
    hours = [hour - offset for offset in range(_WINDOW_HOURS)]
    try:
        values = await get_client().mget(
            [f"{namespace()}turns:{h}" for h in hours]
            + [f"{namespace()}cards:{h}" for h in hours]
        )
    except Exception:
        return {"turns": 0, "cards": 0, "card_rate": 0.0}

    counts = [int(value or 0) for value in values]
    turns = sum(counts[:_WINDOW_HOURS])
    cards = sum(counts[_WINDOW_HOURS:])
    return {
        "turns": turns,
        "cards": cards,
        "card_rate": round(cards / turns, 4) if turns else 0.0,
    }


# --- Stampede protection ---------------------------------------------------
#
# A miss let every concurrent caller run the full agent: retrieval plus two
# model calls, each. The four landing starter chips are the highest-collision
# strings in the product -- a classroom tapping "What is the ASPIRE Programme?"
# against a cold cache is N simultaneous agent runs computing the same answer,
# all billed. Compounded by there being no rate limiting on `/chat` until P1-001.
#
# Single-flight: the first caller to a cold key takes a short lease and computes;
# the others wait briefly for it to land and serve the result. A loser that
# times out falls through and computes normally, because a slow answer is much
# better than no answer -- this is a cost optimisation, never a correctness gate.

#: Long enough for a slow turn, short enough that a crashed worker does not
#: block the next caller for meaningfully longer than computing would have.
_LEASE_SECONDS = 30
#: How long a loser waits before giving up and computing it itself.
_WAIT_SECONDS = 8.0
_POLL_SECONDS = 0.25


async def acquire_lease(key: str) -> bool:
    """True when this caller should compute. False means somebody else is."""
    if not cache_enabled():
        return True
    try:
        # `NX` is the whole mechanism: exactly one caller can create the key.
        return bool(await get_client().set(f"{key}:lease", "1", nx=True, ex=_LEASE_SECONDS))
    except Exception:
        # A cache that cannot answer must not stop anyone computing.
        return True


async def release_lease(key: str) -> None:
    if not cache_enabled():
        return
    try:
        await get_client().delete(f"{key}:lease")
    except Exception:
        pass


async def await_leader(key: str) -> dict[str, Any] | None:
    """Wait briefly for the caller holding the lease to write its answer."""
    if not cache_enabled():
        return None
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            raw = await get_client().get(key)
        except Exception:
            return None
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        try:
            # The leader died, or finished without caching. Either way there is
            # nothing left to wait for.
            if not await get_client().exists(f"{key}:lease"):
                return None
        except Exception:
            return None
    return None


async def ping() -> bool:
    """Verify Valkey answers, so a bad URL surfaces at boot and not mid-request."""
    client = get_client()
    if client is None:
        return False
    try:
        await client.ping()
        return True
    except Exception:
        logger.warning("Valkey did not respond to PING.", exc_info=True)
        return False
