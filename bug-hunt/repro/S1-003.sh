#!/usr/bin/env bash
# S1-003 — /ready is a 500 in every deployment. 4-line repro.
# SAFETY: DATABASE_URL points at the disposable scratch container.
set -u
cd "$(dirname "$0")/../../backend" || exit 1
DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
.venv/Scripts/python.exe - <<'PY'
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, raise_server_exceptions=False) as c:
    print("/ready ->", c.get("/ready").status_code)   # expect 200, get 500
    print("/health ->", c.get("/health").status_code) # 200
PY
