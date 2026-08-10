"""Setup for the registration suite."""

from __future__ import annotations

import os

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)
# A published Fernet key.
os.environ.setdefault(
    "PII_ENCRYPTION_KEY", "dGVzdC1vbmx5LWtleS1ub3QtZm9yLXByb2R1Y3Rpb24tMDE="
)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_database(monkeypatch):
    """Registration tests run against the in-memory draft, not Postgres."""
    from contextlib import asynccontextmanager

    from app.agents.register import store

    @asynccontextmanager
    async def _none():
        yield None

    monkeypatch.setattr(store, "session", _none, raising=False)

    # `store` imports `session` inside each function, so the module-level patch above is not enough on its own -- p…
    import app.db as db_module

    monkeypatch.setattr(db_module, "session", _none)
    yield
