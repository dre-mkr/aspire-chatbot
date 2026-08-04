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

import hashlib
import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import redis.asyncio as redis

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
    return f"aspire:answer:v1:{digest}"


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
    """Process-wide Valkey client, or None when none is configured."""
    url = valkey_url()
    if not url:
        return None
    return redis.from_url(url, encoding="utf-8", decode_responses=True)


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

_HITS = "aspire:cache:hits"
_MISSES = "aspire:cache:misses"


async def record(hit: bool) -> None:
    if not cache_enabled():
        return
    try:
        await get_client().incr(_HITS if hit else _MISSES)
    except Exception:
        pass  # accounting must never affect the request


async def stats() -> dict[str, float | int | bool]:
    """Hits, misses and the rate. Reported on /health."""
    if not cache_enabled():
        return {"enabled": False, "hits": 0, "misses": 0, "hit_rate": 0.0}
    try:
        hits = int(await get_client().get(_HITS) or 0)
        misses = int(await get_client().get(_MISSES) or 0)
    except Exception:
        return {"enabled": True, "hits": 0, "misses": 0, "hit_rate": 0.0}

    total = hits + misses
    return {
        "enabled": True,
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 4) if total else 0.0,
    }


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
