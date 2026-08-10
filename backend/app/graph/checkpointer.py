"""Where a conversation's graph state lives between turns."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.config import get_settings

logger = logging.getLogger(__name__)

#: The saver, its pool, and whether `setup()` has run.
_saver: Any | None = None
_pool: Any | None = None
_setup_done = False
#: Set once the pool has failed to open.
_unavailable = False


# ── what may come back out of a checkpoint ─────────────────────────────────── langgraph's msgpack layer recon…


def _models_reachable_from(*roots: Any) -> set[type]:
    """Every pydantic model reachable from these annotations, transitively."""
    from pydantic import BaseModel

    def models_in(annotation: Any):
        from typing import get_args

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield annotation
        for arg in get_args(annotation):
            yield from models_in(arg)

    found: set[type] = set()
    pending = [root for root in roots]
    while pending:
        for model in models_in(pending.pop()):
            if model in found:
                continue
            found.add(model)
            pending.extend(
                field.annotation for field in model.model_fields.values()
            )
    return found


def allowed_checkpoint_types() -> list[tuple[str, str]]:
    """`(module, name)` for everything ASPIRE puts in a checkpoint."""
    from app.agents.register.schema import Application
    from app.context.session_context import SessionContext
    from app.graph.state import Citation, KBChunk
    from app.schemas.directives import UIDirective

    # `SessionContext` is a root because `AspireState.context` holds one and the checkpoint round-trips it.
    models = _models_reachable_from(
        KBChunk, Citation, UIDirective, Application, SessionContext
    )
    return sorted((model.__module__, model.__name__) for model in models)


def install_windows_event_loop_policy() -> bool:
    """Make psycopg's async mode usable on Windows."""
    import sys

    if sys.platform != "win32":
        return False

    import asyncio

    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is None:  # pragma: no cover - not reachable on win32
        return False
    if isinstance(asyncio.get_event_loop_policy(), policy):
        return False
    asyncio.set_event_loop_policy(policy())
    return True


def _proactor_loop_in_use() -> bool:
    """Whether the running loop is one psycopg cannot connect on."""
    import sys

    if sys.platform != "win32":
        return False

    import asyncio

    proactor = getattr(asyncio, "ProactorEventLoop", None)
    if proactor is None:  # pragma: no cover - not reachable on win32
        return False
    try:
        return isinstance(asyncio.get_running_loop(), proactor)
    except RuntimeError:  # pragma: no cover - always called from async code
        return False


def psycopg_dsn(url: str) -> str:
    """The configured database URL in the form psycopg accepts."""
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0] or "postgresql"
    if scheme == "postgres":
        scheme = "postgresql"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


async def get_checkpointer() -> Any | None:
    """The process-wide checkpointer, opening its pool on first use."""
    global _saver, _pool, _setup_done, _unavailable

    if _saver is not None:
        return _saver
    if _unavailable:
        return None

    settings = get_settings()
    if not settings.database_url:
        logger.info(
            "No DATABASE_URL, so the graph runs without a checkpointer: each turn "
            "starts from a fresh state and nothing resumes."
        )
        return None

    # Checked before psycopg is even imported: on a loop it cannot use, there is nothing to import it for.
    if _proactor_loop_in_use():
        _unavailable = True
        logger.error(
            "The graph is running on a ProactorEventLoop, which psycopg cannot "
            "use, so this process will run WITHOUT conversation persistence. "
            "This is not a database problem -- the same DSN connects in under a "
            "second on a SelectorEventLoop. uvicorn picks the loop with an "
            "explicit `loop_factory`, which no event-loop policy can override; "
            "start the API with `python -m app.serve` (see that module) rather "
            "than `python -m uvicorn app.main:app`."
        )
        return None

    # Imported here rather than at module scope so that a deployment without a database -- and the test suite -- do…
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from psycopg_pool import AsyncConnectionPool
    from psycopg.rows import dict_row

    dsn = psycopg_dsn(settings.database_url)

    pool = AsyncConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=settings.checkpointer_pool_size,
        # `open=False` plus an explicit `open()` rather than letting the constructor connect: the constructor's implici…
        open=False,
        # Verify the connection before handing it out.
        check=AsyncConnectionPool.check_connection,
        # `check` alone makes the failure survivable; this is what makes it rare.
        max_lifetime=settings.checkpointer_max_lifetime,
        kwargs={
            "autocommit": True,
            "prepare_threshold": None,
            "row_factory": dict_row,
        },
    )

    try:
        await pool.open(wait=True, timeout=settings.checkpointer_connect_timeout)
    except Exception:
        # Remembered, not retried.
        _unavailable = True
        await pool.close()
        logger.error(
            "The checkpointer could not open a connection pool, so this process "
            "will run WITHOUT conversation persistence. On Windows the usual "
            "cause is the ProactorEventLoop -- see "
            "`install_windows_event_loop_policy`.",
            exc_info=True,
        )
        return None

    _pool = pool
    # Passing an explicit allowlist is what turns the warning off, and it also flips the hook from "import whatever…
    _saver = AsyncPostgresSaver(
        _pool,
        serde=JsonPlusSerializer(
            allowed_msgpack_modules=allowed_checkpoint_types()
        ),
    )

    if not _setup_done:
        await _saver.setup()
        _setup_done = True
        logger.info("Checkpointer tables are present in Postgres.")

    return _saver


async def close_checkpointer() -> None:
    """Release the pool at shutdown."""
    global _saver, _pool, _setup_done, _unavailable

    if _pool is not None:
        await _pool.close()
    _saver = None
    _pool = None
    _setup_done = False
    _unavailable = False


async def delete_thread(session_id: str) -> bool:
    """Forget everything the graph holds about one conversation."""
    saver = await get_checkpointer()
    if saver is None:
        return False
    await saver.adelete_thread(session_id)
    return True


def thread_config(session_id: str, **extra: Any) -> dict[str, Any]:
    """The `config` a graph invocation needs to find its thread."""
    return {"configurable": {"thread_id": session_id, **extra}}
