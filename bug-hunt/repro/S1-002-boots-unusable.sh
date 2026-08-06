#!/usr/bin/env bash
# S1-002 — the service boots and reports READY while being completely unusable.
#
# Two misconfigurations that a deployment can plausibly ship with:
#   (a) SESSION_SECRET unset   — exactly what .env.example ships
#   (b) LLM API key invalid    — a rotated/typo'd key
#
# For each: boot, then ask /health and /ready what they think, then try the
# thing a real user does first.
#
# SAFETY: DATABASE_URL is set explicitly to the scratch container.
#
#   bash bug-hunt/repro/S1-002-boots-unusable.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1
PY=.venv/Scripts/python.exe
SCRATCH_DB="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt"

run_case() {
  local label="$1"; shift
  echo "══════════════════════════════════════════════════════════"
  echo "CASE: $label"
  echo "──────────────────────────────────────────────────────────"
  env "$@" timeout 240 "$PY" - <<'PY' 2>&1 | grep -E "^(HEALTH|READY|SESSION|VERDICT)"
import logging
logging.basicConfig(level="ERROR")
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    h = client.get("/health")
    print(f"HEALTH  -> {h.status_code}  {h.text[:160]}")
    r = client.get("/ready")
    print(f"READY   -> {r.status_code}  {r.text[:200]}")
    # What a first-time visitor's browser does before it can ask anything.
    s = client.post("/api/auth/anonymous", json={"device_id": "probe-device-0001"})
    print(f"SESSION -> {s.status_code}  {s.text[:160]}")
    usable = s.status_code == 200
    ready_ok = r.status_code == 200
    if ready_ok and not usable:
        print("VERDICT: SILENT DEGRADATION -- /ready says 200 but no user can get a session")
    elif not ready_ok and not usable:
        print("VERDICT: honest -- /ready reports the problem")
    else:
        print("VERDICT: usable")
PY
  echo
}

run_case "SESSION_SECRET unset (as .env.example ships it)" \
  DATABASE_URL="$SCRATCH_DB" SESSION_SECRET="" VALKEY_URL="redis://127.0.0.1:6380/9"

run_case "LLM API key invalid" \
  DATABASE_URL="$SCRATCH_DB" \
  SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
  VALKEY_URL="redis://127.0.0.1:6380/9" \
  OPENAI_API_KEY="sk-invalid-deliberately-for-this-probe"
