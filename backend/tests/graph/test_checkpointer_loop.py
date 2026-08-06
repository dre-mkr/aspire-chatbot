"""The event loop the checkpointer needs, and how it is chosen.

psycopg's async mode cannot run on Windows' `ProactorEventLoop`, and the
checkpointer is psycopg. That constraint was known and the fix that was in place
did not work: `install_windows_event_loop_policy()` sets an event-loop POLICY,
and uvicorn 0.52 does not use one --

    # uvicorn/server.py
    asyncio_run(self.serve(), loop_factory=self.config.get_loop_factory())

    # uvicorn/loops/asyncio.py
    if sys.platform == "win32" and not use_subprocess:
        return asyncio.ProactorEventLoop

An explicit `loop_factory` bypasses the policy, so the call was inert for the
loop the API actually served on, however early it ran.

What that cost, measured live before the fix: the pool timed out after 30 s,
`get_checkpointer` returned None, and the graph ran with **no persistence at
all** -- every turn starting from a fresh state. The answers still looked right,
so it read as a slow database rather than as a product with no memory. After the
fix, the same thread wrote 34 checkpoints and 64 blobs, and the query rewriter
picked up context from a previous turn.

These tests are pure: no database, no uvicorn, no Windows required.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.graph import checkpointer  # noqa: E402

win32_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the Proactor loop only exists on Windows"
)


# ── detecting the loop that cannot work ──────────────────────────────────────


@pytest.mark.anyio
async def test_a_selector_loop_is_not_flagged():
    """The good case must not trip the guard, or it disables persistence.

    anyio runs this on whatever loop the suite uses; on Linux there is no
    Proactor loop at all, so this asserts the guard is inert there too.
    """
    if sys.platform == "win32":
        running = asyncio.get_running_loop()
        if isinstance(running, asyncio.ProactorEventLoop):
            pytest.skip("this session's loop is a Proactor one; see the module docstring")

    assert checkpointer._proactor_loop_in_use() is False


@win32_only
def test_a_proactor_loop_is_flagged():
    """The whole point: recognise it BEFORE paying a 30-second pool timeout.

    Without this, the failure is a `PoolTimeout` logged as "could not open a
    connection pool" -- which sends you to Neon, the DSN and the network, in
    that order, for a problem that is none of them.
    """

    async def probe() -> bool:
        return checkpointer._proactor_loop_in_use()

    assert asyncio.run(probe(), loop_factory=asyncio.ProactorEventLoop) is True


@win32_only
def test_the_guard_short_circuits_instead_of_waiting():
    """Returns None quickly rather than after `checkpointer_connect_timeout`.

    Measured: 0.47 s on a Proactor loop against 30 s before the guard existed.
    The bound here is loose because it is asserting "did not wait for the pool",
    not a performance figure.
    """
    from app.config import get_settings

    if not get_settings().database_url:
        pytest.skip("with no DATABASE_URL the function returns None before the guard")

    checkpointer._saver = None
    checkpointer._pool = None
    checkpointer._unavailable = False
    try:

        async def probe():
            loop = asyncio.get_running_loop()
            start = loop.time()
            saver = await checkpointer.get_checkpointer()
            return saver, loop.time() - start

        saver, elapsed = asyncio.run(probe(), loop_factory=asyncio.ProactorEventLoop)

        assert saver is None
        assert elapsed < get_settings().checkpointer_connect_timeout, (
            f"took {elapsed:.1f}s, so it waited for the pool rather than "
            "recognising the loop"
        )
    finally:
        checkpointer._saver = None
        checkpointer._pool = None
        checkpointer._unavailable = False


# ── the entry point that actually chooses the loop ───────────────────────────


def test_serve_uses_a_loop_psycopg_can_connect_on():
    """`app.serve` supplies the factory, because nothing else gets to.

    Asserted on the factory rather than by starting a server: the property that
    matters is which loop class is produced, and that is decidable without
    binding a port.
    """
    from app.serve import _selector_loop

    loop = _selector_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
        if sys.platform == "win32":
            assert not isinstance(loop, asyncio.ProactorEventLoop)
    finally:
        loop.close()


def test_serve_does_not_shell_out_to_the_broken_command():
    """A regression guard on the documentation as much as the code.

    `python -m uvicorn app.main:app` is the invocation that silently loses
    persistence on Windows. If this module ever goes back to delegating to it,
    the bug returns with no symptom.
    """
    import inspect

    from app import serve

    source = inspect.getsource(serve)
    assert "loop_factory=_selector_loop" in source
