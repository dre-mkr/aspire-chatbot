"""The event loop the checkpointer needs, and how it is chosen."""

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
    """The good case must not trip the guard, or it disables persistence."""
    if sys.platform == "win32":
        running = asyncio.get_running_loop()
        if isinstance(running, asyncio.ProactorEventLoop):
            pytest.skip("this session's loop is a Proactor one; see the module docstring")

    assert checkpointer._proactor_loop_in_use() is False


@win32_only
def test_a_proactor_loop_is_flagged():
    """The whole point: recognise it BEFORE paying a 30-second pool timeout."""

    async def probe() -> bool:
        return checkpointer._proactor_loop_in_use()

    assert asyncio.run(probe(), loop_factory=asyncio.ProactorEventLoop) is True


@win32_only
def test_the_guard_short_circuits_instead_of_waiting():
    """Returns None quickly rather than after `checkpointer_connect_timeout`."""
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
    """`app.serve` supplies the factory, because nothing else gets to."""
    from app.serve import _selector_loop

    loop = _selector_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
        if sys.platform == "win32":
            assert not isinstance(loop, asyncio.ProactorEventLoop)
    finally:
        loop.close()


def test_serve_does_not_shell_out_to_the_broken_command():
    """A regression guard on the documentation as much as the code."""
    import inspect

    from app import serve

    source = inspect.getsource(serve)
    assert "loop_factory=_selector_loop" in source
