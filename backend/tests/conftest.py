"""Shared setup for the database-backed suites."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production-32b+")

# Give this run its own Valkey namespace.
#
# The per-IP session cap counts in Valkey, and that instance is shared -- with
# other test runs and, in this deployment, with an unrelated application. Two
# overlapping runs incremented the same counter, so `test_the_cap_eventually_
# refuses` failed in a full run and passed in isolation. CI now runs pytest on
# every push, so without this two PRs would flake each other on an abuse control.
os.environ.setdefault("ASPIRE_CACHE_NAMESPACE", f"test-{uuid.uuid4().hex[:8]}:")

# ── connections are never pooled across tests ────────────────────────────────
#
# The engine is a process-wide singleton, but almost every suite here drives it
# through its own event loop: `TestClient` opens one per test, and the
# plain-asyncio files open their own. An asyncpg connection belongs to the loop
# that created it, so a pooled connection checked out by a later loop is already
# invalid — and fails deep inside SQLAlchemy's checkout with "Event loop is
# closed", naming neither the pool nor the loop, in whichever test drew the
# unlucky connection.
#
# It hid for a long time because a pool this size usually returns the connection
# the same test just used. It only bites once a run is long enough for the pool
# to churn, which is to say only in a full run — the exact case where a failure
# is least legible.
#
# `NullPool` here rather than a fix in `app/db/engine.py`: pooling is right in
# the service, where there is one loop for the process's life. It is only wrong
# under pytest. This costs a connection per session and a few seconds a run.
try:
    from sqlalchemy.pool import NullPool

    from app.db import engine as _db_engine

    _build = _db_engine.create_async_engine

    def _unpooled(url, **kwargs):
        for pooled_only in ("pool_size", "max_overflow", "pool_recycle", "pool_pre_ping"):
            kwargs.pop(pooled_only, None)
        return _build(url, poolclass=NullPool, **kwargs)

    _db_engine.create_async_engine = _unpooled
except Exception:  # pragma: no cover - no database configured
    pass


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "no_cap_reset: leave the anonymous session counter alone"
    )
    config.addinivalue_line(
        "markers", "live_response_cache: let the endpoint consult the real cache"
    )


@pytest.fixture(autouse=True)
def _response_cache_always_misses(request, monkeypatch):
    """Make `/chat` and `/chat/stream` see a cache miss unless a test says otherwise.

    Added in P13-006, when the response cache moved onto `/chat/stream` -- the
    transport every test drives. Two problems appeared the moment it did, and both
    are about tests depending on state they did not set.

    The first was cross-run: `cache_key` did not use `namespace()`, so a pytest run
    read and wrote PRODUCTION answer keys. `test_streaming.py` started receiving
    real cached answers in place of its fake agent's. That is fixed in
    `app/cache.py`, properly, by namespacing the key.

    The second is within a run and cannot be fixed there: two tests that post the
    same opening question now share a cache entry, so the first to run computes and
    caches, and the second silently takes the replay path. Whichever assertion goes
    first wins, and the failure names neither the cache nor the other test.

    So the endpoint sees a miss by default. Tests about caching either patch
    `_cached_reply` themselves -- which beats this, being applied later -- or mark
    themselves `live_response_cache`. The cache's own unit tests are untouched:
    this patches the call site in `app.main`, not `app.cache`.
    """
    if request.node.get_closest_marker("live_response_cache"):
        yield
        return

    try:
        from app import main as _main

        async def _miss(_request):
            return None

        monkeypatch.setattr(_main, "_cached_reply", _miss)
    except Exception:  # pragma: no cover - app not importable in this suite
        pass

    yield


@pytest.fixture(autouse=True)
def _reset_anonymous_session_cap(request):
    """Clear the per-IP anonymous session counter between tests.

    The cap is real and it works — which is the problem here. Every test that
    asks for an anonymous session spends one of the thirty an address gets per
    hour, so a full run trips its own abuse control and every test after that
    fails with a 429 that looks like a regression and is not.

    Cleared per test rather than raised, so the limiter stays in the code path
    the tests exercise. `test_session_cap.py` opts out and asserts it still
    bites.

    Deliberately a SYNCHRONOUS client. Reaching for the app's shared async one
    meant an `asyncio.run` per test and a connection pool bound to a loop that
    is then closed — which surfaced as "Event loop is closed" in whichever test
    happened to run next, naming neither this fixture nor the real cause.
    """
    if request.node.get_closest_marker("no_cap_reset"):
        # The one suite testing the cap needs it to accumulate.
        yield
        return

    try:
        import redis as sync_redis

        from app.cache import valkey_url

        url = valkey_url()
        if url:
            client = sync_redis.Redis.from_url(url)
            try:
                for key in client.scan_iter("aspire:anon-sessions:*"):
                    client.delete(key)
            finally:
                client.close()
    except Exception:
        # No Valkey, or it is unhappy. The limiter fails open, so the tests run
        # unthrottled anyway and this is not worth failing a run over.
        pass

    yield
