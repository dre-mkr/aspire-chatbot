"""Alembic environment, wired to the app's own settings and async engine."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db.engine import _normalise, _strip_libpq_only_params
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Alembic needs a database to migrate; set it "
            "in backend/.env (use Neon's POOLED connection string)."
        )
    return _strip_libpq_only_params(_normalise(settings.database_url))


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep autogenerate away from things it does not own."""
    if type_ == "index" and name and name.startswith("ix_documents_embedding"):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=_include_object,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(
        _url(),
        # Migrations go through the pooled host like everything else, so they need the same setting: pgbouncer in trans…
        connect_args={"statement_cache_size": 0, "ssl": "require"},
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
