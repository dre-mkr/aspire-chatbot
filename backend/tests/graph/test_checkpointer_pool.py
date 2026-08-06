"""How the checkpointer's pool survives the far end hanging up.

Neon suspends a quiet compute and closes its connections. A pool cannot be told
about a close it did not perform, so the dead socket stays in the queue looking
healthy. The first statement of the next turn is the saver reading the thread
back -- `AsyncPostgresSaver.aget_tuple`, before any node runs -- so the whole
turn dies there and the reader is told the assistant is unavailable:

    WARNING psycopg.pool: discarding closed connection: <AsyncConnection [BAD]>
    ERROR app.api.stream: v2 turn failed for session c85f3105-...
    psycopg.OperationalError: consuming input failed:
    SSL connection has been closed unexpectedly

Two distinct cases hide behind that log, and only one was ever handled:

  * the far end closes **cleanly**, psycopg processes the FIN and marks the
    connection closed. psycopg_pool already discards those on checkout -- that
    is the `discarding closed connection` warning, which is the pool working.
  * the connection dies with **no FIN reaching psycopg**, so `conn.closed` stays
    False. The pool hands it out, and the failure lands on first use. Verified
    against the live endpoint by severing the socket beneath psycopg: without
    `check` the next checkout raised `consuming input failed`, with it the
    checkout succeeded.

So the fix is `check` on the pool, plus a `max_lifetime` short enough that
connections are retired before they go stale. `max_idle` cannot do the second
job and it is the intuitive place to reach for -- it only closes connections
ABOVE `min_size`, so the one baseline connection a low-traffic process reuses
every turn is exactly the one it never touches.

These tests are pure: no database and no network. They assert the pool is
*configured* for this, because the failure it prevents needs a suspended
serverless compute to reproduce and cannot be provoked in a unit test.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.config import get_settings  # noqa: E402
from app.graph import checkpointer  # noqa: E402

pytest.importorskip("psycopg_pool", reason="no database configured in this deployment")
# Imported for real, and BEFORE any monkeypatching, because langgraph subscripts
# `AsyncConnectionPool` at import time (`_ainternal.Conn`). A stub installed
# first is not a generic and that import fails with `not subscriptable`.
pytest.importorskip("langgraph.checkpoint.postgres.aio")


@pytest.fixture
def pool_kwargs(monkeypatch):
    """The kwargs `get_checkpointer` builds its pool with, without connecting.

    The pool is captured at construction and never opened: `open()` is stubbed
    out, so this needs no database. `DATABASE_URL` is forced to a syntactically
    valid DSN so the "no database" early return is not what is being tested.
    """
    captured: dict = {}

    from psycopg_pool import AsyncConnectionPool

    class RecordingPool:
        # The real callable, because the code under test reaches for
        # `AsyncConnectionPool.check_connection` through this name. A stub method
        # here would make the identity assertion below vacuous.
        check_connection = AsyncConnectionPool.check_connection

        # Kept subscriptable so this stub cannot break an import that treats the
        # real class as a generic, whatever the import order turns out to be.
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, **kwargs):
            captured.update(kwargs)
            # `check` is compared by identity against the real callable below,
            # so the stub must not replace it.
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
    """Without `check`, a stale connection costs a turn instead of a round trip.

    Identity against `AsyncConnectionPool.check_connection` rather than "is not
    None": a truthy-but-wrong value would pass a looser assertion and still let
    dead connections through.
    """
    captured, AsyncConnectionPool = pool_kwargs

    await checkpointer.get_checkpointer()

    assert captured["check"] is AsyncConnectionPool.check_connection, (
        "the pool must verify a connection on checkout; psycopg's default is None, "
        "which hands out sockets the far end has already abandoned"
    )


@pytest.mark.anyio
async def test_connections_are_retired_before_the_far_end_drops_them(pool_kwargs):
    """`max_lifetime` has to beat the idle window, and `max_idle` cannot do it.

    Neon's default suspend is five minutes of quiet. A `max_lifetime` at or above
    that means the baseline connection is routinely older than the far end's
    patience, and `check` -- the backstop -- becomes the common path.
    """
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
    """Guards the connect kwargs against a careless edit to the pool call.

    These are documented at length in the module under test; this only asserts
    they survived, because each fails in production and in no test.
    """
    captured, _ = pool_kwargs

    await checkpointer.get_checkpointer()

    kwargs = captured["kwargs"]
    assert kwargs["autocommit"] is True
    assert kwargs["prepare_threshold"] is None
    assert kwargs["row_factory"].__name__ == "dict_row"
