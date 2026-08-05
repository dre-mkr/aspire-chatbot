"""The two operational endpoints, which nothing covered until they both broke.

`/ready` and `/debug/timings` each raised `NameError` on every call -- `time` and
`HTTPException` were both missing from `app/main.py` -- and the 517-test suite
passed throughout, because no test imported either line. A `ruff --select F` gate
now catches that class at CI time; these tests catch the behaviour, which is the
half a linter cannot check.

Deliberately not marked `slow`: they are the cheapest possible assertions and
belong in the gate that runs first.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_ready_answers_rather_than_raising(client):
    """A readiness probe that 500s is a deploy that never goes live.

    The status is not asserted to be 200: a machine with no database
    legitimately reports 503, and this test must pass in both worlds. What it
    refuses to accept is a 5xx that is not a considered answer -- so the body has
    to be the JSON contract, whatever the verdict inside it.
    """
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


def test_disabled_debug_route_is_indistinguishable_from_an_absent_one(client):
    """The 404-not-403 choice is a security property, and it has to hold.

    `debug_timings` documents it: "a disabled debug route should not confirm that
    it exists". A `NameError` made it 500 instead, which a prober can tell apart
    from the 404 that any unknown path returns -- so the bug leaked exactly the
    fact the design was written to hide.
    """
    assert os.environ.get("TIMINGS_ENDPOINT_ENABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }, "this test asserts the DISABLED behaviour; unset TIMINGS_ENDPOINT_ENABLED"

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
    # Shape only. The ring is per-process and per-restart, so its contents are
    # not something a test may assume anything about.
    assert isinstance(response.json(), dict)
