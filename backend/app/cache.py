"""Valkey: the response cache, and the connection the queue shares."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import struct
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
    """Collapse the trivial ways of writing the same question."""
    text = unicodedata.normalize("NFKC", query)
    text = _PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text)
    return text.casefold().strip()


@lru_cache(maxsize=1)
def corpus_fingerprint() -> str:
    """A short digest of the knowledge base the answers were built from.

    Covers the source registry as well as the CSV. A cached answer carries its
    citations, and `data/sources.yaml` decides what those citations are CALLED
    -- so renaming a source or adding a page title, without this, would leave
    every shelved answer citing it by the old name for the whole seven-day TTL,
    and `_replay` would write that stale wording permanently into conversation
    history on the way past.
    """
    settings = get_settings()
    path = settings.resolved(settings.knowledge_base_csv)
    try:
        digest = hashlib.sha256(Path(path).read_bytes())
    except OSError:
        # No corpus to fingerprint is not a reason to stop answering.
        logger.warning("Could not fingerprint %s; caching without one.", path)
        return "nocorpus"

    from app.sources import REGISTRY_PATH

    try:
        digest.update(REGISTRY_PATH.read_bytes())
    except OSError:
        # The registry only supplies wording; without it citations fall back to
        # their domain, which is a coherent state and not one to stop for.
        logger.warning("Could not fingerprint %s; caching without it.", REGISTRY_PATH)

    return digest.hexdigest()[:12]


def namespace() -> str:
    """`aspire:` in production, `aspire:<something>:` under a test run."""
    prefix = os.environ.get("ASPIRE_CACHE_NAMESPACE", "")
    return f"aspire:{prefix}"


def cache_key(
    query: str,
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
    age_band: str | None = None,
    simple_mode: bool = False,
) -> str:
    """The key for one answer."""
    material_parts: dict[str, Any] = {
        "q": normalise(query),
        "lang": (language or "en").lower(),
        "persona": persona or "",
        "status": account_status or "",
        "band": age_band or "",
        # An edited knowledge base must not keep serving answers built from the old one.
        "kb": corpus_fingerprint(),
    }
    # Present only when set, so ordinary answers keep the keys they already have.
    #
    # A simplified answer and a full one are different text for the same
    # question, and the cache is consulted before anything is generated -- so
    # without this, turning the control on serves back the answer it was turned
    # on to avoid. Adding the field unconditionally would have been tidier and
    # would have invalidated every entry on the shelf to record a `false`.
    if simple_mode:
        material_parts["simple"] = True
    material = json.dumps(material_parts, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    # Namespaced: `namespace()` exists so every key this module invents is scoped to it.
    return f"{namespace()}answer:v2:{digest}"


def valkey_url() -> str | None:
    """The configured URL, with `localhost` pinned to IPv4."""
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
    age_band: str | None = None,
    simple_mode: bool = False,
) -> dict[str, Any] | None:
    """A previously cached answer, or None."""
    if not cache_enabled():
        return None

    key = cache_key(
        query,
        language=language,
        persona=persona,
        account_status=account_status,
        age_band=age_band,
        simple_mode=simple_mode,
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
    age_band: str | None = None,
    simple_mode: bool = False,
) -> None:
    """Cache one answer. Never raises, for the same reason as `get_answer`."""
    if not cache_enabled():
        return

    key = cache_key(
        query,
        language=language,
        persona=persona,
        account_status=account_status,
        age_band=age_band,
        simple_mode=simple_mode,
    )
    try:
        await get_client().set(
            key,
            json.dumps(payload, ensure_ascii=False),
            ex=get_settings().response_cache_ttl_seconds,
        )
    except Exception:
        logger.warning("Cache write failed; the answer was still served.", exc_info=True)


# --- Hit-rate accounting ----------------------------------------------------

#: How many hourly buckets make up the reported window.
_WINDOW_HOURS = 6


def _bucket(hit: bool, hour: int) -> str:
    return f"{namespace()}cache:{'hits' if hit else 'misses'}:{hour}"


def _current_hour() -> int:
    return int(time.time()) // 3600


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


# --- Query-embedding cache ---
# Embedding a query is a ~400 ms network round trip, so the vector is cached.

def _pack_vector(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


def _unpack_vector(packed: str) -> list[float]:
    raw = base64.b64decode(packed.encode("ascii"))
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def embedding_key(text: str, model: str) -> str:
    digest = hashlib.sha256(f"{model}\x00{normalise(text)}".encode()).hexdigest()[:32]
    return f"{namespace()}embed:v1:{digest}"


def _embedding_cache_on() -> bool:
    # Deliberately NOT gated on `response_cache_enabled`: the two are independent trade-offs.
    return get_client() is not None and get_settings().embedding_cache_enabled


async def get_embedding(text: str, model: str) -> list[float] | None:
    """A previously computed query embedding, or None. Never raises."""
    if not _embedding_cache_on():
        return None
    try:
        raw = await get_client().get(embedding_key(text, model))
    except Exception:
        logger.warning("Embedding-cache read failed; treating as a miss.", exc_info=True)
        return None
    if not raw:
        return None
    try:
        return _unpack_vector(raw)
    except Exception:
        logger.warning("Discarding malformed embedding-cache entry.")
        return None


async def put_embedding(text: str, model: str, vector: list[float]) -> None:
    """Store one query embedding. Never raises."""
    if not _embedding_cache_on():
        return
    try:
        await get_client().set(
            embedding_key(text, model),
            _pack_vector(vector),
            ex=get_settings().embedding_cache_ttl_seconds,
        )
    except Exception:
        logger.warning("Embedding-cache write failed.", exc_info=True)


# --- Translation cache ---
#
# The corpus is English. All 801 rows, no locale column, and the follow-up chips
# and source labels are lifted from it verbatim -- so a reader who wrote Spanish
# got a Spanish answer under English chips and an English "Where this came
# from". The answer is generated and follows the reader; retrieved text cannot.
#
# Translating on the way out is cheap ONLY because the same few hundred corpus
# questions come back over and over. Cached by exact text, so the cost converges
# to nothing: the second reader to see a chip pays no model call for it.


def translation_key(text: str, language: str) -> str:
    digest = hashlib.sha256(f"{language}\x00{text.strip()}".encode()).hexdigest()[:32]
    return f"{namespace()}xlate:v1:{digest}"


def _translation_cache_on() -> bool:
    return get_client() is not None


async def get_translation(text: str, language: str) -> str | None:
    """A previously translated string, or None. Never raises."""
    if not _translation_cache_on():
        return None
    try:
        raw = await get_client().get(translation_key(text, language))
    except Exception:
        logger.warning("Translation-cache read failed; treating as a miss.", exc_info=True)
        return None
    if not raw:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)


async def put_translation(text: str, language: str, translated: str) -> None:
    """Store one translation. Never raises.

    No TTL. A translation of a fixed corpus string does not go stale, and the
    whole point is that it is paid for once.
    """
    if not _translation_cache_on():
        return
    try:
        await get_client().set(translation_key(text, language), translated)
    except Exception:
        logger.warning("Translation-cache write failed.", exc_info=True)


# --- Semantic response cache, layer 2 ---
# Layer 1 collapses different spellings; this layer catches paraphrases by embedding distance.

_SEMANTIC_DIMS = 384


def _shelf_vector(vector: list[float]) -> list[float]:
    head = vector[:_SEMANTIC_DIMS]
    norm = math.sqrt(sum(component * component for component in head)) or 1.0
    return [component / norm for component in head]


def _cosine(a: list[float], b: list[float]) -> float:
    # Both sides are unit vectors by construction, so the dot product is the cosine.
    if len(a) != len(b):
        return -1.0
    return sum(x * y for x, y in zip(a, b))


#: LAYER 2 IS OFF AND HAS NO CALLER.
def semantic_shelf_key(
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
    age_band: str | None = None,
    simple_mode: bool = False,
) -> str:
    parts: dict[str, Any] = {
        "lang": (language or "en").lower(),
        "persona": persona or "",
        "status": account_status or "",
        "band": age_band or "",
        "kb": corpus_fingerprint(),
    }
    # A simplified answer sits on its own shelf, for the same reason it gets its
    # own key: a near-paraphrase must not fetch the version the reader turned off.
    if simple_mode:
        parts["simple"] = True
    material = json.dumps(parts, sort_keys=True)
    digest = hashlib.sha256(material.encode()).hexdigest()[:32]
    # v2 with the band, mirroring the `answer:` bump.
    return f"{namespace()}semindex:v2:{digest}"


def semantic_enabled() -> bool:
    return cache_enabled() and get_settings().semantic_cache_enabled


async def semantic_lookup(
    vector: list[float],
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
    age_band: str | None = None,
    simple_mode: bool = False,
) -> dict[str, Any] | None:
    """The cached answer of the nearest same-audience question, if close enough."""
    if not semantic_enabled():
        return None

    probe = _shelf_vector(vector)
    shelf = semantic_shelf_key(
        language=language,
        persona=persona,
        account_status=account_status,
        age_band=age_band,
        simple_mode=simple_mode,
    )
    try:
        entries = await get_client().lrange(shelf, 0, -1)
    except Exception:
        logger.warning("Semantic-shelf read failed; treating as a miss.", exc_info=True)
        return None

    threshold = get_settings().semantic_cache_threshold
    best_key: str | None = None
    best_cosine = -1.0
    for raw in entries:
        try:
            entry = json.loads(raw)
            cosine = _cosine(probe, _unpack_vector(entry["v"]))
        except Exception:
            continue
        if cosine > best_cosine:
            best_cosine = cosine
            best_key = entry.get("k")

    if best_key is None or best_cosine < threshold:
        return None

    try:
        raw = await get_client().get(best_key)
    except Exception:
        return None
    if not raw:
        # The answer expired out from under its index entry: a dead pointer, which is a miss.
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    logger.info(
        "semantic cache hit (cosine=%.4f, threshold=%.2f, language=%s)",
        best_cosine,
        threshold,
        language,
    )
    payload["_semantic_cosine"] = round(best_cosine, 4)
    return payload


async def semantic_register(
    query: str,
    vector: list[float],
    *,
    language: str,
    persona: str | None,
    account_status: str | None,
    age_band: str | None = None,
    simple_mode: bool = False,
) -> None:
    """Add this turn's query to the shelf its future paraphrases will search."""
    if not semantic_enabled():
        return

    entry = json.dumps(
        {
            "v": _pack_vector(_shelf_vector(vector)),
            "k": cache_key(
                query,
                language=language,
                persona=persona,
                account_status=account_status,
                age_band=age_band,
                simple_mode=simple_mode,
            ),
        }
    )
    shelf = semantic_shelf_key(
        language=language,
        persona=persona,
        account_status=account_status,
        age_band=age_band,
        simple_mode=simple_mode,
    )
    try:
        pipe = get_client().pipeline()
        # Newest first; the trim keeps the shelf at its cap by dropping the oldest.
        pipe.lpush(shelf, entry)
        pipe.ltrim(shelf, 0, get_settings().semantic_cache_max_entries - 1)
        pipe.expire(shelf, get_settings().response_cache_ttl_seconds)
        await pipe.execute()
    except Exception:
        logger.warning("Semantic-shelf write failed.", exc_info=True)


# --- Flush on knowledge-base reload ---
# Belt and braces, not the primary defence: the corpus fingerprint already keys answers.

#: Every key version this cache has ever written, live and retired.
_FLUSH_PREFIXES = (
    "answer:v2:",
    "answer:v1:",  # retired
    "semindex:v2:",
    "semindex:v1:",  # retired alongside it
    "embed:v1:",
)


async def flush_answers() -> int:
    """Delete every cached answer, semantic shelf and embedding. Returns count."""
    client = get_client()
    if client is None:
        return 0
    deleted = 0
    try:
        for prefix in _FLUSH_PREFIXES:
            async for key in client.scan_iter(match=f"{namespace()}{prefix}*", count=200):
                await client.delete(key)
                deleted += 1
    except Exception:
        logger.warning("Cache flush failed part-way (deleted %d).", deleted, exc_info=True)
    return deleted
