"""The anonymous session cap, asserted rather than assumed."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")

from fastapi.testclient import TestClient  # noqa: E402

from app import cache  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import database_enabled  # noqa: E402
from app.main import app  # noqa: E402

#: P0-010 -- see the `slow` marker note in pyproject.toml.
pytestmark = [pytest.mark.slow, pytest.mark.skipif(
    not database_enabled(), reason="These are database-backed session tests."
)]


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.mark.no_cap_reset
def test_the_cap_eventually_refuses(client: TestClient):
    """One address cannot mint identities forever."""
    if cache.get_client() is None:
        pytest.skip("The cap is counted in Valkey, which is not configured here.")

    limit = get_settings().anonymous_sessions_per_ip_per_hour
    statuses = []
    for _ in range(limit + 5):
        statuses.append(
            client.post("/api/auth/anonymous", json={"device_id": str(uuid.uuid4())}).status_code
        )

    assert 200 in statuses, "the first sessions should be granted"
    assert 429 in statuses, "the cap should eventually refuse"
    # And it refuses with something a person could act on rather than a bare code.
    refused = client.post("/api/auth/anonymous", json={"device_id": str(uuid.uuid4())})
    if refused.status_code == 429:
        assert "try again" in refused.json()["detail"].lower()


def test_the_cap_fails_open_without_a_cache(client: TestClient, monkeypatch):
    """A cache outage must not lock everybody out."""
    monkeypatch.setattr(cache, "get_client", lambda: None)
    response = client.post("/api/auth/anonymous", json={"device_id": str(uuid.uuid4())})
    assert response.status_code == 200
