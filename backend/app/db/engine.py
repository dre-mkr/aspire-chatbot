"""The async engine, and the one place that knows how to reach Postgres.

Everything above this consumes `session()` and never sees a URL or a driver.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Neon's pooled endpoint carries this in its host. The direct endpoint is one
# Postgres backend per connection and will run out under a per-request session
# pool; the pooled one multiplexes through pgbouncer.
POOLED_HOST_MARKER = "-pooler"


def _normalise(url: str) -> str:
    """Force the asyncpg driver, whatever form the URL arrived in.

    Neon hands out `postgresql://...`, and psql also accepts `postgres://`.
    Either would make SQLAlchemy reach for psycopg2 and fail on an async engine
    with a message that never mentions the driver.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def _strip_libpq_only_params(url: str) -> str:
    """Drop query parameters asyncpg does not accept.

    Neon's copy-paste connection string ends in `?sslmode=require`, which is a
    libpq parameter. asyncpg rejects it outright, so the very first connection
    fails with `invalid dsn` on a URL the dashboard just handed you. TLS is not
    lost: `ssl` is passed through connect_args below.
    """
    base, _, query = url.partition("?")
    if not query:
        return url
    keep = [
        part
        for part in query.split("&")
        if part.split("=")[0] not in {"sslmode", "channel_binding", "options"}
    ]
    return f"{base}?{'&'.join(keep)}" if keep else base


#: Hosts where TLS is not required, because the socket never leaves the machine.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _ssl_mode(url: str) -> dict[str, str]:
    """`ssl: require` everywhere except a loopback address.

    This was an unconditional `"ssl": "require"`, which is right for Neon and
    wrong for everything else: a stock local Postgres, a CI service container and
    an offline developer all answer `rejected SSL upgrade` and there is no
    setting that turns it off. Combined with a README that never mentions a
    database at all, the practical requirement to run this project was a cloud
    account.

    Loopback only, deliberately. Anything with a real hostname keeps TLS whether
    or not it looks like Neon, so this cannot quietly downgrade a remote
    connection -- the failure mode worth protecting against is far worse than the
    inconvenience it removes.
    """
    host = urlsplit(url).hostname or ""
    if host.lower() in _LOOPBACK_HOSTS:
        logger.info(
            "Connecting to %s without TLS: the socket does not leave this machine.",
            host,
        )
        return {}
    return {"ssl": "require"}


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine | None:
    """The process-wide engine, or None when no database is configured.

    None is a supported state rather than a failure, and at this step it is the
    only state anything depends on: without `DATABASE_URL` the service runs
    exactly as it does today.
    """
    settings = get_settings()
    if not settings.database_url:
        return None

    if POOLED_HOST_MARKER not in settings.database_url:
        # Loud, and deliberately not fatal: a one-off script against the direct
        # endpoint is fine, serving traffic from it is not, and this is the only
        # moment anyone will be told the difference.
        logger.warning(
            "DATABASE_URL does not look like Neon's pooled endpoint (no %r in the "
            "host). The direct endpoint holds one backend per connection and will "
            "exhaust under concurrent requests -- use the pooled host.",
            POOLED_HOST_MARKER,
        )

    url = _strip_libpq_only_params(_normalise(settings.database_url))
    return create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Neon drops idle connections when it scales down. Without recycling,
        # the pool hands out sockets the far end already closed and the request
        # fails once before the pool notices.
        pool_recycle=280,
        pool_pre_ping=True,
        connect_args={
            # pgbouncer in transaction mode cannot hold prepared statements
            # across checkouts, which is asyncpg's default behaviour.
            "statement_cache_size": 0,
            **_ssl_mode(url),
        },
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession] | None:
    engine = get_engine()
    if engine is None:
        return None
    return async_sessionmaker(engine, expire_on_commit=False)


# Set when the database answers but has not been migrated. A process-wide latch
# rather than a per-request check, because the schema does not appear halfway
# through a run and probing for it every turn would be a query per message.
_SCHEMA_MISSING = False

# The tables whose absence turns persistence off without stopping the service.
#
# `documents` is deliberately NOT here, and no longer for the reason this comment
# used to give. It is not "only read, and an empty corpus still answers
# questions" -- since P13-002 the corpus IS the knowledge base and an empty one
# answers nothing. It is absent because this list drives a *degradation* latch:
# losing these means conversations stop being saved and chat carries on from
# in-process memory. Losing the corpus is fatal instead, and is enforced by
# `main._require_corpus`, which refuses to start rather than serving ungrounded
# answers. Two different failures, two different responses.
REQUIRED_TABLES = ("conversations", "messages")


def database_enabled() -> bool:
    """Whether conversations will actually be persisted.

    False when there is no URL *or* when the schema is not there. The second
    case used to be indistinguishable from the first right up until the first
    message of a conversation, which then failed with `relation "conversations"
    does not exist` -- a 500 for the user, on the happy path, over a deployment
    step nobody had been told about.
    """
    return get_engine() is not None and not _SCHEMA_MISSING


async def check_schema() -> bool:
    """Verify the tables exist, and latch persistence off if they do not.

    `to_regclass` returns NULL rather than raising for a missing relation, so
    this asks the question without needing an exception to answer it.
    """
    global _SCHEMA_MISSING

    engine = get_engine()
    if engine is None:
        return False

    try:
        async with engine.connect() as connection:
            missing = [
                table
                for table in REQUIRED_TABLES
                if (
                    await connection.execute(
                        text("SELECT to_regclass(:name)"), {"name": table}
                    )
                ).scalar()
                is None
            ]
    except Exception:
        logger.warning("Could not inspect the database schema.", exc_info=True)
        return False

    if missing:
        _SCHEMA_MISSING = True
        logger.error(
            "Database is reachable but not migrated: %s missing. Conversations "
            "will NOT be persisted for this process; chat still works, using "
            "in-process memory. Fix it by running, from the backend directory:\n"
            "    alembic upgrade head",
            ", ".join(missing),
        )
        return False

    _SCHEMA_MISSING = False
    logger.info("Database schema present; conversations will be persisted.")
    return True


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession | None]:
    """One transactional session, or None when there is no database.

    Callers branch on None rather than being handed a fake, so "we are not
    persisting" is visible at the call site instead of silently succeeding.
    """
    # `database_enabled`, not merely "is there a URL": an unmigrated database
    # has a perfectly good engine and a sessionmaker that will happily hand out
    # a session, and every statement run through it fails on a missing table.
    factory = get_sessionmaker() if database_enabled() else None
    if factory is None:
        yield None
        return

    async with factory() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def warm(settings: Settings | None = None) -> bool:
    """Open one connection at startup so a user does not pay the cold start.

    Neon scales to zero and the wake-up is visible -- always on the first
    message after an idle period. Warming here rather than disabling
    scale-to-zero keeps the compute bill at zero overnight and moves the cost to
    deploy time, where nobody is waiting.

    Best effort: a database that will not answer at boot must not stop the
    service from starting.
    """
    settings = settings or get_settings()
    engine = get_engine()
    if engine is None or not settings.database_warm_on_start:
        return False

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        logger.info("Database connection warmed.")
        return True
    except Exception:
        logger.warning("Could not warm the database connection.", exc_info=True)
        return False


async def dispose() -> None:
    engine = get_engine()
    if engine is not None:
        await engine.dispose()
