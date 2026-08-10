"""Where a conversation's graph state lives between turns.

LangGraph's `AsyncPostgresSaver`, pointed at the same Neon database everything
else uses, with `thread_id = session_id`. One session is one thread, forever;
resuming a half-finished registration three days later is the same operation as
continuing a sentence, because both are "load thread, run graph, save thread".

## Why psycopg here and asyncpg everywhere else

`app/db/engine.py` runs SQLAlchemy on asyncpg. The checkpointer library is
written against psycopg 3 and there is no asyncpg backend for it. Rather than
fight that, this module keeps its own connection pool: the two never share a
connection, never share a transaction, and cannot deadlock against each other.

The cost is a second pool against the same database, which on a pooled Neon
endpoint is a handful of pgbouncer client slots. The alternative -- reimplementing
the saver on asyncpg -- is a correctness surface nobody wants to own.

## Three psycopg options that are not optional

`autocommit=True`, `prepare_threshold=None` and `row_factory=dict_row` are all
required, and two of them are required *by pgbouncer* rather than by the saver:

  * **autocommit** -- the saver manages its own transactions with explicit
    `BEGIN`/`COMMIT`. Leaving psycopg's implicit transaction on wraps those in
    an outer one, and on a pooled endpoint an idle-in-transaction connection is
    a connection pgbouncer will not hand back to the pool.

  * **prepare_threshold=None** -- disables server-side prepared statements.
    pgbouncer in transaction pooling mode multiplexes many clients over few
    server connections, so a statement prepared on one round trip is very often
    not there on the next. The symptom is a `prepared statement "_pg3_0" does
    not exist` error under load and never in development, which is the worst
    possible place to learn this.

  * **row_factory=dict_row** -- the saver indexes rows by column name.

## The far end hangs up, and the pool is the last to know

Neon suspends a quiet compute and closes its connections. A connection pool
has no way to hear about that -- it did not perform the close -- so a dead
socket sits in the queue marked healthy until something tries to use it. The
first statement of a turn is the saver reading the thread back, so the whole
turn dies before a node runs. `get_checkpointer` sets both halves of the fix:
`check` (verify on checkout, so a stale connection costs a round trip instead
of a turn) and `max_lifetime` (retire connections early, so `check` rarely has
anything to catch). Neither is a psycopg default.

## One Windows-only trap, documented because it costs an hour to find

psycopg's async mode cannot run on asyncio's `ProactorEventLoop`, which is the
default on Windows for both `asyncio.run` and uvicorn. The error names the loop
and not the cause, and it arrives as a connection failure, so it reads as "the
database is unreachable". `install_windows_event_loop_policy()` below fixes it
in one call; production is Linux and is unaffected either way.

## Failure is a real state, not an exception to swallow

`get_checkpointer()` returns None when `DATABASE_URL` is unset. That is a
supported deployment (the whole test suite runs in it) and means the graph runs
with no persistence: every turn starts from a fresh state. Callers must handle
None. What is *not* supported is a configured database that fails to connect --
that raises, at startup, because a service that silently forgets every
conversation looks exactly like a service that is working.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.config import get_settings

logger = logging.getLogger(__name__)

#: The saver, its pool, and whether `setup()` has run. Module-level because the
#: checkpointer is process-wide by construction -- it owns a connection pool, and
#: building a second one per request would defeat the point of pooling.
_saver: Any | None = None
_pool: Any | None = None
_setup_done = False
#: Set once the pool has failed to open. Stops every subsequent request paying
#: the same connection timeout -- see `get_checkpointer`.
_unavailable = False


# ── what may come back out of a checkpoint ───────────────────────────────────
#
# langgraph's msgpack layer reconstructs an object by importing a module and
# calling a name out of it, which is code execution driven by whatever is in the
# checkpoint row. Today it does that for ANY type and logs
#
#   Deserializing unregistered type app.graph.state.KBChunk from checkpoint.
#   This will be blocked in a future version.
#
# on each one. Two reasons not to leave that until the upgrade forces it:
#
#   * The failure is SILENT. A blocked type is not an error -- the ext hook
#     returns the raw payload, so a `KBChunk` comes back as a plain dict. The
#     first thing to notice would be `merge_citations` raising AttributeError on
#     `citation.kb_id`, one layer away from anything that names the cause.
#   * The default is "import anything the row asks for". An allowlist is the
#     control that makes checkpoint rows data again, and this is a database a
#     conversation writes to on every turn.
#
# Measured on the live checkpoint tables (2,568 blobs, 3,152 writes) rather than
# guessed at: `KBChunk` x560, `Citation` x24, `EscalatedDirective` x108, and the
# langchain message types, which are already on langgraph's own safe list. The
# report named only the first two -- `EscalatedDirective` was found by counting.
#
# So the list is DERIVED rather than typed out. Reaching it by walking the real
# annotations means a new directive, or a new field on an existing one, is
# allowlisted by existing, and cannot be forgotten -- which matters because the
# consequence of forgetting is a dict where a model should be, not a crash. Only
# the models actually reachable from checkpointed state are included; this is
# still an allowlist, not `app.*`.


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
    """`(module, name)` for everything ASPIRE puts in a checkpoint.

    langgraph's `SAFE_MSGPACK_TYPES` already covers the langchain messages,
    builtins, `uuid`, `datetime` and friends, and is merged in by the library --
    so this only has to name ours.
    """
    from app.agents.register.schema import Application
    from app.context.session_context import SessionContext
    from app.graph.state import Citation, KBChunk
    from app.schemas.directives import UIDirective

    # `SessionContext` is a root because `AspireState.context` holds one and the
    # checkpoint round-trips it. Left out, langgraph logged
    #
    #     Blocked deserialization of app.context.session_context.SessionContext
    #
    # once per resumed turn and handed the node `None`. Nothing failed -- every
    # agent falls back to a history-free prompt -- so the visible symptom was an
    # assistant that forgot the conversation whenever a turn resumed from the
    # checkpoint, which is every turn after the first.
    #
    # `Turn`, `ApplicationRef` and `TicketRef` arrive transitively through the
    # annotations; `_models_reachable_from` walks them.
    models = _models_reachable_from(
        KBChunk, Citation, UIDirective, Application, SessionContext
    )
    return sorted((model.__module__, model.__name__) for model in models)


def install_windows_event_loop_policy() -> bool:
    """Make psycopg's async mode usable on Windows. No-op everywhere else.

    Returns whether it changed anything, so a caller can log it once at startup
    rather than leaving a developer to discover the constraint through a
    connection error that blames the network.

    ## This does NOT help under uvicorn, and that is not a bug here

    Setting the POLICY only affects loops built through the policy. uvicorn
    0.52 does not use one -- `Server.run()` is

        asyncio_run(self.serve(), loop_factory=self.config.get_loop_factory())

    and on win32 without `--reload`/`--workers>1` that factory is
    `asyncio.ProactorEventLoop`, called directly. An explicit `loop_factory`
    bypasses the policy entirely, so this function is inert there however early
    it runs. `app/serve.py` is the entry point that actually fixes it, by
    supplying the loop factory itself.

    Still called, and still useful, for every caller that DOES go through the
    policy: `asyncio.run` in the scripts, the eval harness, and pytest-anyio.
    """
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
    """Whether the running loop is one psycopg cannot connect on.

    Checked BEFORE opening the pool, because the failure without it is a
    30-second `PoolTimeout` reported as "the checkpointer could not open a
    connection pool" -- which reads as an unreachable database and sends you to
    Neon, the DSN and the network in that order. psycopg's own error says the
    real cause, but `pool.open(wait=True)` retries connections internally and
    surfaces the timeout instead, so the useful message never reaches the log.

    Measured on this machine: the same DSN opens in 0.8 s on a Selector loop and
    times out after the full 30 s on a Proactor one.
    """
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
    """The configured database URL in the form psycopg accepts.

    `DATABASE_URL` is written for SQLAlchemy, so it usually carries a driver
    suffix (`postgresql+asyncpg://`). psycopg wants a plain libpq URI. Only the
    scheme is touched: every query parameter is preserved, which matters because
    Neon's URL carries `sslmode=require` and dropping it turns a TLS connection
    into a refused one.

    Note the deliberate asymmetry with `db/engine.py`, which *strips*
    `channel_binding` because asyncpg rejects it. psycopg is libpq underneath
    and accepts it, so nothing is stripped here.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0] or "postgresql"
    if scheme == "postgres":
        scheme = "postgresql"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


async def get_checkpointer() -> Any | None:
    """The process-wide checkpointer, opening its pool on first use.

    Returns None when no database is configured. `setup()` -- which creates the
    checkpoint tables if they are absent -- runs exactly once, on the first
    call, and is idempotent: it is `CREATE TABLE IF NOT EXISTS` plus the saver's
    own migration ledger, so calling it against an up-to-date schema is a few
    catalogue reads and nothing else.

    Running it here rather than in a migration is a considered trade. The
    checkpoint schema belongs to the library and changes when the library does;
    encoding it in an alembic revision would mean hand-transcribing somebody
    else's DDL and re-transcribing it on every upgrade. Alembic owns *our*
    tables; the saver owns its own.
    """
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

    # Checked before psycopg is even imported: on a loop it cannot use, there is
    # nothing to import it for. Falling through here costs 30 seconds per process
    # start and then reports the database as unreachable, which it is not.
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

    # Imported here rather than at module scope so that a deployment without a
    # database -- and the test suite -- does not need psycopg installed at all.
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from psycopg_pool import AsyncConnectionPool
    from psycopg.rows import dict_row

    dsn = psycopg_dsn(settings.database_url)

    pool = AsyncConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=settings.checkpointer_pool_size,
        # `open=False` plus an explicit `open()` rather than letting the
        # constructor connect: the constructor's implicit open is deprecated in
        # psycopg-pool 3.2 and emits a warning on every process start.
        open=False,
        # Verify the connection before handing it out. Without this the pool's
        # idea of "open" is only ever its own bookkeeping, and the other end of
        # this socket is a serverless endpoint that suspends a quiet compute and
        # hangs up. Nothing tells the pool, so a dead connection stays in the
        # queue looking healthy, gets checked out, and raises
        #
        #   psycopg.OperationalError: consuming input failed:
        #   SSL connection has been closed unexpectedly
        #
        # on the first statement of the next turn -- which is
        # `AsyncPostgresSaver.aget_tuple`, before any node has run, so the whole
        # turn fails and the reader is told the assistant is unavailable. The
        # cost is one round trip per checkout; a failed check is not an error,
        # the pool discards that connection and opens a fresh one.
        check=AsyncConnectionPool.check_connection,
        # `check` alone makes the failure survivable; this is what makes it rare.
        #
        # `max_idle` cannot do it. It only closes connections ABOVE `min_size`
        # (`_shrink_pool`: `if self._nconns > self._min_size`), so the one
        # baseline connection -- exactly the one a low-traffic process reuses
        # every turn -- is never recycled by it and idles until the far end
        # hangs up. `max_lifetime` applies to every connection including that
        # one, so it is the knob that actually retires a stale socket before a
        # turn finds it.
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
        # Remembered, not retried. Without this the next request pays the same
        # thirty-second timeout, and the one after that, so a misconfiguration
        # that should surface once as a clear log line instead surfaces as a
        # service that appears to hang.
        #
        # The turn still runs -- without persistence -- because a reader waiting
        # on an answer is owed one, and losing the ability to resume the
        # conversation is our problem rather than theirs.
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
    # Passing an explicit allowlist is what turns the warning off, and it also
    # flips the hook from "import whatever the row names" to "import these".
    # See `allowed_checkpoint_types` for how the list is derived and why it is
    # not a literal.
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
    """Release the pool at shutdown.

    Resets the module state as well as closing the pool, so a process that
    closes and re-opens (the tests do) gets a working checkpointer rather than a
    saver holding a closed pool -- a failure that surfaces as a connection error
    on the first turn after a restart and names nothing useful.
    """
    global _saver, _pool, _setup_done, _unavailable

    if _pool is not None:
        await _pool.close()
    _saver = None
    _pool = None
    _setup_done = False
    _unavailable = False


async def delete_thread(session_id: str) -> bool:
    """Forget everything the graph holds about one conversation.

    Returns whether there was a checkpointer to ask. False means no database is
    configured, which is the supported no-persistence deployment -- there was
    nothing stored, so there is nothing to delete and that is not a failure.

    This exists because the checkpoint is a *second copy of the transcript*. The
    saver keeps the thread's whole message list, plus whatever the nodes put
    beside it -- retrieved documents, a half-finished registration, the running
    summary. Deleting `conversations` and its `messages` and stopping there
    would leave all of that in Postgres under the same thread id, so a delete
    the reader was told had happened would have removed the copy they can see
    and kept the copy the model reads.

    Nothing here checks ownership, deliberately: a thread id is guessable in
    principle and this call cannot be the thing that decides. The caller must
    have established the conversation is theirs -- `app.conversations` does it
    by putting the owner in the DELETE's WHERE clause and only reaching this
    line if a row actually went.
    """
    saver = await get_checkpointer()
    if saver is None:
        return False
    await saver.adelete_thread(session_id)
    return True


def thread_config(session_id: str, **extra: Any) -> dict[str, Any]:
    """The `config` a graph invocation needs to find its thread.

    One function so that `thread_id = session_id` is stated in exactly one
    place. It is the identity the checkpointer keys on, and getting it wrong
    does not raise -- it silently starts a new conversation, or worse, resumes
    somebody else's.

    `extra` becomes additional `configurable` entries, which is how per-request
    context (locale, persona) reaches tools without passing through the model.
    """
    return {"configurable": {"thread_id": session_id, **extra}}
