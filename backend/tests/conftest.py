"""Shared setup for the database-backed suites."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production-32b+")

# Give this run its own Valkey namespace.
os.environ.setdefault("ASPIRE_CACHE_NAMESPACE", f"test-{uuid.uuid4().hex[:8]}:")

# ── connections are never pooled across tests ────────────────────────────────
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
    """Make `/chat` and `/chat/stream` see a cache miss unless a test says otherwise."""
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
    """Clear the per-IP anonymous session counter between tests."""
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
        # No Valkey, or it is unhappy.
        pass

    yield
