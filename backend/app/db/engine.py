"""The async engine, and the one place that knows how to reach Postgres."""

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

# Neon's pooled endpoint carries this in its host.
POOLED_HOST_MARKER = "-pooler"


def _normalise(url: str) -> str:
    """Force the asyncpg driver, whatever form the URL arrived in."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def _strip_libpq_only_params(url: str) -> str:
    """Drop query parameters asyncpg does not accept."""
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
    """`ssl: require` everywhere except a loopback address."""
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
    """The process-wide engine, or None when no database is configured."""
    settings = get_settings()
    if not settings.database_url:
        return None

    if POOLED_HOST_MARKER not in settings.database_url:
        # Loud but not fatal: a one-off script may use the direct endpoint, serving traffic may not.
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
        # Neon drops idle connections when it scales down.
        pool_recycle=280,
        pool_pre_ping=True,
        connect_args={
            # pgbouncer in transaction mode cannot hold prepared statements across checkouts.
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


# Set when the database answers but has not been migrated.
_SCHEMA_MISSING = False

# The tables whose absence turns persistence off without stopping the service.
REQUIRED_TABLES = ("conversations", "messages")


def database_enabled() -> bool:
    """Whether conversations will actually be persisted."""
    return get_engine() is not None and not _SCHEMA_MISSING


async def check_schema() -> bool:
    """Verify the tables exist, and latch persistence off if they do not."""
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
    """One transactional session, or None when there is no database."""
    # `database_enabled`, not just "is there a URL": an unmigrated database still has an engine.
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
    """Open one connection at startup so a user does not pay the cold start."""
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
