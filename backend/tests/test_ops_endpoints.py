"""The two operational endpoints, which nothing covered until they both broke."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import requires_database


pytestmark = requires_database


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_ready_answers_rather_than_raising(client):
    """A readiness probe that 500s is a deploy that never goes live."""
    response = client.get("/ready")

    assert response.status_code in (200, 503), (
        f"/ready returned {response.status_code}; it must answer, not raise"
    )
    body = response.json()
    assert set(body) >= {"ready", "database", "cache", "provider"}
    assert isinstance(body["ready"], bool)
    # 200 and 503 must agree with the flag rather than contradict it.
    assert body["ready"] is (response.status_code == 200)


def test_health_is_cheap_and_always_answers(client):
    """Liveness is a different question from readiness, and must never depend on it."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize("path", ["/api/health", "/api/ready"])
def test_the_probes_are_reachable_through_the_api_prefix(client, path):
    """
    The bare paths are unreachable in production.

    nginx proxies only `/api/` and `/v2/` to this service, so `/health` and
    `/ready` fall through to the SPA and answer 404 with HTML -- the deployment
    had no health check anything outside the box could call. These aliases are
    what a monitor, a deploy gate and the keep-warm ping actually hit, so they
    have to keep answering.
    """
    response = client.get(path)
    assert response.status_code in (200, 503)
    assert response.headers["content-type"].startswith("application/json")


def test_the_aliases_answer_exactly_as_the_originals_do(client):
    """Two doors, one room. A drifting alias is worse than no alias."""
    assert client.get("/api/health").json() == client.get("/health").json()

    prefixed = client.get("/api/ready")
    bare = client.get("/ready")
    assert prefixed.status_code == bare.status_code
    assert prefixed.json() == bare.json()


def test_disabled_debug_route_is_indistinguishable_from_an_absent_one(client):
    """The 404-not-403 choice is a security property, and it has to hold."""
    if os.environ.get("TIMINGS_ENDPOINT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        # A box that enables the endpoint cannot test the disabled path, so skip rather than fail.
        pytest.skip("TIMINGS_ENDPOINT_ENABLED is set; the disabled path is not testable here")

    disabled = client.get("/debug/timings")
    absent = client.get("/debug/a-route-that-does-not-exist")

    assert disabled.status_code == 404
    assert disabled.status_code == absent.status_code, (
        "a disabled debug route is distinguishable from an absent one, which is "
        "the reconnaissance leak the 404 was chosen to prevent"
    )


def test_debug_timings_serves_when_switched_on(client, monkeypatch):
    """The other half: the gate must not be so tight that the route never works."""
    monkeypatch.setenv("TIMINGS_ENDPOINT_ENABLED", "true")
    response = client.get("/debug/timings")

    assert response.status_code == 200
    # Shape only.
    assert isinstance(response.json(), dict)


# ── boot-time refusal on a bad signing key ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret, expect",
    [
        ("", "is not set"),
        ("tooshort", "bytes; it must be at least"),
    ],
    ids=["absent", "too-short"],
)
async def test_a_bad_signing_key_refuses_at_boot(monkeypatch, secret, expect):
    """`config.py` promises "a refusal at boot", and it has to be true."""
    from app.config import get_settings
    from app.main import app, lifespan

    monkeypatch.setenv("SESSION_SECRET", secret)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match=expect):
            async with lifespan(app):
                pass
    finally:
        get_settings.cache_clear()
