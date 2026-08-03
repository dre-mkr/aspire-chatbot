from __future__ import annotations

from datetime import date

import pytest

from app.eligibility.engine import EligibilityEngine, set_engine
from app.eligibility.store import InMemorySessionStore, set_store

# Fixed so the reminder-year assertions do not rot. The audit was taken on this
# date and every "which year can they register" expectation is relative to it.
TODAY = date(2026, 8, 2)


@pytest.fixture
def store() -> InMemorySessionStore:
    return InMemorySessionStore(ttl_seconds=3600.0)


@pytest.fixture
def engine(store: InMemorySessionStore) -> EligibilityEngine:
    return EligibilityEngine(store=store, today=TODAY)


@pytest.fixture
def wired(engine: EligibilityEngine, store: InMemorySessionStore):
    """Install the test engine process-wide, for the router and tool tests."""
    set_store(store)
    set_engine(engine)
    yield engine
    set_engine(None)
    set_store(None)
