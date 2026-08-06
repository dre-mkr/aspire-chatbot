"""The layer-2 semantic cache and the query-embedding cache (P14-B / P14-D).

Everything pure is tested pure: packing, truncation, cosine, key isolation.
The lookup itself runs against the namespaced test Valkey, exactly as the
layer-1 tests do since P13-006 -- and is skipped, not faked, when none answers.

The layer ships DISABLED (`semantic_cache_enabled=False`) on the strength of
`scripts/semantic_margin.py`: at the 0.95 threshold an adversarial near-pair
("aged 5 to 18" ~ "aged 5 to 12") measured 0.9645 cosine and would be served
the wrong answer, while every real paraphrase measured below 0.95. These tests
therefore exercise the machinery with the flag forced on, so the day somebody
flips it the behaviour is already pinned.
"""

from __future__ import annotations

import asyncio
import math
import os
import uuid

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")
# Isolate every run from production keys and from parallel runs (P11-001).
os.environ.setdefault("ASPIRE_CACHE_NAMESPACE", f"sem-test-{uuid.uuid4().hex[:8]}:")

from app import cache  # noqa: E402
from app.cache import (  # noqa: E402
    _pack_vector,
    _shelf_vector,
    _unpack_vector,
    embedding_key,
    semantic_shelf_key,
)


def _unit(seed: list[float], dims: int = 3072) -> list[float]:
    """A deterministic unit vector whose head carries the seed's direction."""
    vector = [0.0] * dims
    for index, value in enumerate(seed):
        vector[index] = value
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class TestVectorPlumbing:
    def test_pack_roundtrips(self):
        vector = [0.25, -1.5, 3.14159, 0.0]
        assert _unpack_vector(_pack_vector(vector)) == pytest.approx(vector)

    def test_shelf_vector_truncates_and_renormalises(self):
        vector = _unit([1.0, 1.0], dims=3072)
        shelf = _shelf_vector(vector)
        assert len(shelf) == cache._SEMANTIC_DIMS
        assert sum(v * v for v in shelf) == pytest.approx(1.0, abs=1e-6)

    def test_cosine_refuses_mismatched_shapes(self):
        # A dims change must read as "no match", never as a comparison of
        # prefixes that happen to align.
        assert cache._cosine([1.0, 0.0], [1.0]) == -1.0


class TestKeys:
    def test_embedding_key_separates_models(self):
        assert embedding_key("q", "text-embedding-3-large") != embedding_key(
            "q", "text-embedding-3-small"
        )

    def test_embedding_key_normalises_the_text(self):
        assert embedding_key("What IS it??", "m") == embedding_key("what is it", "m")

    def test_shelf_key_isolates_language_persona_status(self):
        base = semantic_shelf_key(language="en", persona=None, account_status=None)
        assert base != semantic_shelf_key(language="es", persona=None, account_status=None)
        assert base != semantic_shelf_key(language="en", persona="stella", account_status=None)
        assert base != semantic_shelf_key(language="en", persona=None, account_status="holder")

    def test_shelf_key_isolates_the_age_band(self):
        """P15-009, layer 2. `orion` is the persona for 9-12, 13-15 AND 16-18,
        whose word caps are 70, 180 and 180 -- so persona cannot stand in for
        band, and a hit here never reaches `safety_out` to be cut down."""
        nine = semantic_shelf_key(
            language="en", persona="orion", account_status="holder", age_band="9-12"
        )
        sixteen = semantic_shelf_key(
            language="en", persona="orion", account_status="holder", age_band="16-18"
        )
        assert nine != sixteen

    def test_the_shelf_entry_points_at_a_key_of_the_same_band(self):
        """The pointer and the shelf must agree, or the layer is dead on arrival.

        A band in the shelf key but not in the `cache_key` it stores would aim
        every entry at a key layer 1 never wrote -- a permanent, silent miss.
        """
        assert cache.cache_key(
            "q", language="en", persona="orion", account_status="holder", age_band="9-12"
        ) != cache.cache_key(
            "q", language="en", persona="orion", account_status="holder", age_band="16-18"
        )


def _valkey_answers() -> bool:
    """Probe with a THROWAWAY client on a throwaway loop.

    Pinging the shared client here would bind one of its pooled connections to
    this temporary loop, and the first test to reuse that connection on the
    real loop would die with "Event loop is closed".
    """
    url = cache.valkey_url()
    if not url:
        return False

    async def probe() -> bool:
        import redis.asyncio as redis

        client = redis.from_url(url, socket_connect_timeout=2.0, socket_timeout=2.0)
        try:
            return bool(await client.ping())
        finally:
            await client.aclose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(probe())
    except Exception:
        return False
    finally:
        loop.close()


needs_valkey = pytest.mark.skipif(
    not _valkey_answers(), reason="semantic lookup needs the test Valkey"
)


@pytest.fixture(autouse=True)
def _fresh_client_per_loop():
    """Each async test runs on its own event loop, and a redis connection made
    on one loop cannot be reused on the next -- it dies with "Event loop is
    closed". Clearing the process-wide client between tests makes every loop
    build its own."""
    cache.get_client.cache_clear()
    yield
    cache.get_client.cache_clear()


def _force_on(monkeypatch):
    settings = cache.get_settings()
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)
    monkeypatch.setattr(settings, "response_cache_enabled", True)


@needs_valkey
@pytest.mark.anyio
async def test_a_close_paraphrase_hits_and_a_distant_question_does_not(monkeypatch):
    _force_on(monkeypatch)

    query = f"what is the {uuid.uuid4().hex[:6]} programme"
    vector = _unit([1.0, 0.2, 0.1])
    await cache.put_answer(
        query, {"reply": "the answer"}, language="en", persona=None, account_status=None
    )
    await cache.semantic_register(
        query, vector, language="en", persona=None, account_status=None
    )

    close = _unit([1.0, 0.21, 0.1])  # cosine ~0.9999
    far = _unit([0.0, 1.0, 0.0])
    hit = await cache.semantic_lookup(close, language="en", persona=None, account_status=None)
    miss = await cache.semantic_lookup(far, language="en", persona=None, account_status=None)

    assert hit is not None and hit["reply"] == "the answer"
    assert hit["_semantic_cosine"] >= cache.get_settings().semantic_cache_threshold
    assert miss is None


@needs_valkey
@pytest.mark.anyio
async def test_the_shelf_never_crosses_a_language(monkeypatch):
    """The layer-1 property, carried over: an English answer must be
    unreachable from a Spanish session however close the embedding."""
    _force_on(monkeypatch)

    query = f"cross-lang {uuid.uuid4().hex[:6]}"
    vector = _unit([0.3, 1.0])
    await cache.put_answer(
        query, {"reply": "english"}, language="en", persona=None, account_status=None
    )
    await cache.semantic_register(
        query, vector, language="en", persona=None, account_status=None
    )

    assert (
        await cache.semantic_lookup(vector, language="es", persona=None, account_status=None)
    ) is None


@needs_valkey
@pytest.mark.anyio
async def test_the_shelf_never_crosses_an_age_band(monkeypatch):
    """P15-009 on layer 2, end to end rather than as a key comparison.

    A 180-word answer written for a sixteen-year-old, reachable by paraphrase
    from a nine-year-old's session, is the exact failure the band closes -- and
    `safety_out` cannot catch it, because a cache hit never reaches the gate.
    Registered at 16-18, looked up at 9-12 with an all-but-identical vector.
    """
    _force_on(monkeypatch)

    query = f"cross-band {uuid.uuid4().hex[:6]}"
    vector = _unit([1.0, 0.4])
    for band in ("16-18", "9-12"):
        await cache.put_answer(
            query,
            {"reply": f"written for {band}"},
            language="en",
            persona="orion",
            account_status="holder",
            age_band=band,
        )
    await cache.semantic_register(
        query,
        vector,
        language="en",
        persona="orion",
        account_status="holder",
        age_band="16-18",
    )

    near = _unit([1.0, 0.401])  # cosine ~1.0; only the band separates them
    assert (
        await cache.semantic_lookup(
            near,
            language="en",
            persona="orion",
            account_status="holder",
            age_band="9-12",
        )
    ) is None

    same = await cache.semantic_lookup(
        near,
        language="en",
        persona="orion",
        account_status="holder",
        age_band="16-18",
    )
    assert same is not None, "the same band must still hit, or this proves nothing"
    assert same["reply"] == "written for 16-18"


@needs_valkey
@pytest.mark.anyio
async def test_an_expired_answer_is_a_dead_pointer_not_a_hit(monkeypatch):
    _force_on(monkeypatch)

    query = f"expiring {uuid.uuid4().hex[:6]}"
    vector = _unit([0.7, 0.7])
    await cache.put_answer(
        query, {"reply": "gone soon"}, language="en", persona=None, account_status=None
    )
    await cache.semantic_register(
        query, vector, language="en", persona=None, account_status=None
    )
    # Simulate the answer's TTL firing while the shelf entry survives.
    await cache.get_client().delete(
        cache.cache_key(query, language="en", persona=None, account_status=None)
    )

    assert (
        await cache.semantic_lookup(vector, language="en", persona=None, account_status=None)
    ) is None


@needs_valkey
@pytest.mark.anyio
async def test_disabled_means_no_lookup_and_no_registration(monkeypatch):
    settings = cache.get_settings()
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)

    # A shelf of its own, so entries other tests registered cannot bleed in.
    persona = f"p-{uuid.uuid4().hex[:6]}"
    vector = _unit([1.0])
    assert (
        await cache.semantic_lookup(vector, language="en", persona=persona, account_status=None)
    ) is None
    # Registration under a disabled flag must write nothing.
    await cache.semantic_register(
        "q", vector, language="en", persona=persona, account_status=None
    )
    shelf = semantic_shelf_key(language="en", persona=persona, account_status=None)
    assert await cache.get_client().llen(shelf) == 0


@needs_valkey
@pytest.mark.anyio
async def test_embedding_cache_roundtrips_and_isolates_models(monkeypatch):
    settings = cache.get_settings()
    monkeypatch.setattr(settings, "embedding_cache_enabled", True)

    text = f"embedded {uuid.uuid4().hex[:6]}"
    vector = [0.5, -0.25, 1.0]
    await cache.put_embedding(text, "model-a", vector)

    assert await cache.get_embedding(text, "model-a") == pytest.approx(vector)
    assert await cache.get_embedding(text, "model-b") is None
