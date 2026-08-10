"""Uploading into somebody else's application."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage.presign import owns_application


class _Claims:
    """The two fields `owns_application` reads off a session token."""

    def __init__(self, session_id: str, user_id: str | None = None) -> None:
        self.session_id = session_id
        self.user_id = user_id


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def storage(monkeypatch):
    """Make signing succeed without a bucket, so 200 vs 404 is about ownership."""
    for name, value in (
        ("S3_ENDPOINT", "https://s3.example.invalid"),
        ("S3_BUCKET", "stub"),
        ("S3_REGION", "us-east-2"),
        ("S3_ACCESS_KEY_ID", "AKIASTUBSTUBSTUBSTUB"),
        ("S3_SECRET_ACCESS_KEY", "stub-not-a-real-credential"),
    ):
        monkeypatch.setenv(name, value)
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── the unit rule ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_caller_owns_their_own_session_scoped_application():
    """The endpoint's long-standing default, and it must keep working."""
    sid = str(uuid.uuid4())
    assert await owns_application(sid, _Claims(session_id=sid)) is True


@pytest.mark.asyncio
async def test_a_stranger_id_is_refused():
    """The bug, as a unit: a well-formed id belonging to nobody the caller is."""
    assert await owns_application(str(uuid.uuid4()), _Claims(session_id=str(uuid.uuid4()))) is False


@pytest.mark.asyncio
async def test_a_malformed_id_is_refused_rather_than_erroring():
    """`CAST(:id AS uuid)` raises on junk; that must read as 'no' and not as 500."""
    assert await owns_application("../../etc/passwd", _Claims(session_id=str(uuid.uuid4()))) is False
    assert await owns_application("", _Claims(session_id=str(uuid.uuid4()))) is False


# ── the endpoint ─────────────────────────────────────────────────────────────


def _session(client, device: str) -> str:
    response = client.post("/v2/session", json={"device_id": device, "locale": "en"})
    assert response.status_code == 200
    return response.json()["token"]


def test_presign_refuses_a_foreign_application_id(client, storage):
    """The original exploit, end to end."""
    token = _session(client, "attacker-device")
    victim = "11111111-1111-1111-1111-111111111111"

    response = client.post(
        "/v2/documents/presign",
        headers={"Authorization": f"Bearer {token}"},
        json={"application_id": victim, "slot": "national_id", "mime": "image/jpeg", "size": 1024},
    )

    assert response.status_code == 404, (
        f"expected 404, got {response.status_code}: {response.text[:200]}"
    )
    assert victim not in response.text, "the refusal echoed the id back"


def test_presign_still_works_for_the_callers_own_application(client, storage):
    """The fix must not close the door on the legitimate path."""
    token = _session(client, "honest-device")

    response = client.post(
        "/v2/documents/presign",
        headers={"Authorization": f"Bearer {token}"},
        json={"slot": "national_id", "mime": "image/jpeg", "size": 1024},
    )

    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["url"].startswith("https://")
    assert "document_id" in body and "expires_at" in body


def test_presign_still_requires_a_session(client, storage):
    """Unchanged behaviour, asserted so the fix cannot regress it."""
    response = client.post(
        "/v2/documents/presign",
        json={"slot": "national_id", "mime": "image/jpeg", "size": 1024},
    )
    assert response.status_code == 401
