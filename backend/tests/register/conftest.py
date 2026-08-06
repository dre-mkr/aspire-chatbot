"""Setup for the registration suite.

`PII_ENCRYPTION_KEY` is set here to a fixed, published, test-only value. It has
to be set at all because `store.save_slot` REFUSES to persist a sensitive slot
without one -- which is the behaviour under test as much as anything else, and
`TestPIISplit` would be meaningless against a store that quietly fell back to
plaintext.

Fixed rather than generated per run so a failure is reproducible: a test that
encrypts with a new key every time cannot be re-run against the row it wrote.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)
# A published Fernet key. Safe precisely because it is published: nothing
# encrypted with it is a secret, and a test suite that needed a real key would
# be a test suite nobody could run.
os.environ.setdefault(
    "PII_ENCRYPTION_KEY", "dGVzdC1vbmx5LWtleS1ub3QtZm9yLXByb2R1Y3Rpb24tMDE="
)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_database(monkeypatch):
    """Registration tests run against the in-memory draft, not Postgres.

    The slot loop's persistence is exercised by its own unit tests; these are
    about the CONVERSATION -- which slot comes next, what a re-ask says, what an
    edit changes. Letting them write to a real database would make them depend
    on a migration state and on network latency, and would leave rows behind.

    Patched at `app.db.session` so the store's own `if db is None` branch is the
    one taken, which is a code path a deployment without Postgres also takes.
    """
    from contextlib import asynccontextmanager

    from app.agents.register import store

    @asynccontextmanager
    async def _none():
        yield None

    monkeypatch.setattr(store, "session", _none, raising=False)

    # `store` imports `session` inside each function, so the module-level patch
    # above is not enough on its own -- patch the source too.
    import app.db as db_module

    monkeypatch.setattr(db_module, "session", _none)
    yield
