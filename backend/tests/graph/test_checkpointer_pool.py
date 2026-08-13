"""How the checkpointer's pool survives the far end hanging up."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.config import get_settings  # noqa: E402
from app.graph import checkpointer  # noqa: E402

pytest.importorskip("psycopg_pool", reason="no database configured in this deployment")
# Imported for real BEFORE monkeypatching: langgraph subscripts the pool at import.
pytest.importorskip("langgraph.checkpoint.postgres.aio")


@pytest.fixture
def pool_kwargs(monkeypatch):
    """The kwargs `get_checkpointer` builds its pool with, without connecting."""
    captured: dict = {}

    from psycopg_pool import AsyncConnectionPool

    class RecordingPool:
        # The real callable, because the code under test reaches for it through this stub.
        check_connection = AsyncConnectionPool.check_connection

        # Kept subscriptable so an import treating the class as a generic still works.
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, **kwargs):
            captured.update(kwargs)
            # `check` is compared by identity below, so the stub must not replace it.
            self.check = kwargs.get("check")

        async def open(self, **_):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(
        "psycopg_pool.AsyncConnectionPool", RecordingPool, raising=True
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@example.invalid/db")
    monkeypatch.setattr(checkpointer, "_saver", None)
    monkeypatch.setattr(checkpointer, "_pool", None)
    monkeypatch.setattr(checkpointer, "_unavailable", False)
    monkeypatch.setattr(checkpointer, "_setup_done", True)
    monkeypatch.setattr(checkpointer, "_proactor_loop_in_use", lambda: False)
    get_settings.cache_clear()

    class _Saver:
        def __init__(self, pool, serde=None):
            self.pool = pool

        async def setup(self):  # pragma: no cover - _setup_done is True
            return None

    monkeypatch.setattr(
        "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver", _Saver, raising=True
    )

    yield captured, AsyncConnectionPool
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_the_pool_verifies_a_connection_before_handing_it_out(pool_kwargs):
    """Without `check`, a stale connection costs a turn instead of a round trip."""
    captured, AsyncConnectionPool = pool_kwargs

    await checkpointer.get_checkpointer()

    assert captured["check"] is AsyncConnectionPool.check_connection, (
        "the pool must verify a connection on checkout; psycopg's default is None, "
        "which hands out sockets the far end has already abandoned"
    )


@pytest.mark.anyio
async def test_connections_are_retired_before_the_far_end_drops_them(pool_kwargs):
    """`max_lifetime` has to beat the idle window, and `max_idle` cannot do it."""
    captured, _ = pool_kwargs

    await checkpointer.get_checkpointer()

    max_lifetime = captured["max_lifetime"]
    assert max_lifetime == get_settings().checkpointer_max_lifetime
    assert max_lifetime < 300.0, (
        f"max_lifetime={max_lifetime}s is not under Neon's five-minute idle "
        "window, so pooled connections go stale before they are retired"
    )


@pytest.mark.anyio
async def test_the_three_pgbouncer_settings_are_still_there(pool_kwargs):
    """Guards the connect kwargs against a careless edit to the pool call."""
    captured, _ = pool_kwargs

    await checkpointer.get_checkpointer()

    kwargs = captured["kwargs"]
    assert kwargs["autocommit"] is True
    assert kwargs["prepare_threshold"] is None
    assert kwargs["row_factory"].__name__ == "dict_row"
