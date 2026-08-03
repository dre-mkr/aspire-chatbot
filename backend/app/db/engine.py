"""The async engine, and the one place that knows how to reach Postgres.

Everything above this consumes `session()` and never sees a URL or a driver.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.db.models import EMBEDDING_DIMENSIONS, dimensions_for

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
            "ssl": "require",
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

# The tables the request path writes to. `documents` is not here: it is only
# read, and a service with an empty corpus still answers questions.
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
    await check_embedding_dimensions()
    return True


async def check_embedding_dimensions() -> bool:
    """Warn if the embedding model and the `documents` column disagree.

    The column width is fixed when the migration runs; the model is fixed by a
    setting someone can change afterwards. Nothing else connects the two, so
    without this the mismatch is invisible until the first INSERT into
    `documents` -- and then it fails for every row, with an error about vector
    dimensions rather than about configuration.

    A warning rather than a hard failure: conversations do not touch this column
    and must keep working. Only ingest and retrieval care.
    """
    settings = get_settings()
    configured = dimensions_for(settings.embeddings_model)

    if configured is None:
        logger.warning(
            "Embedding model %r has no known dimension; cannot verify it matches "
            "the documents.embedding column (%d). Add it to "
            "EMBEDDING_MODEL_DIMENSIONS.",
            settings.embeddings_model,
            EMBEDDING_DIMENSIONS,
        )
        return False

    if configured != EMBEDDING_DIMENSIONS:
        logger.error(
            "EMBEDDING DIMENSION MISMATCH: %s produces %d-dimension vectors but "
            "documents.embedding is vector(%d). Every insert into `documents` "
            "will fail. Either set EMBEDDINGS_MODEL to a %d-dimension model, or "
            "add a migration that recreates the column at %d and re-embed the "
            "corpus -- the vectors themselves differ, so there is no in-place "
            "conversion.",
            settings.embeddings_model,
            configured,
            EMBEDDING_DIMENSIONS,
            EMBEDDING_DIMENSIONS,
            configured,
        )
        return False

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
