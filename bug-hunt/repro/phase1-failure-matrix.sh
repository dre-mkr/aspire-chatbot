#!/usr/bin/env bash
# Phase 1 failure matrix — does each broken dependency fail LOUDLY, or does the
# service boot into a state where the UI silently returns nothing?
#
# Silent degradation is an S1 per the brief.
#
# SAFETY: every case sets DATABASE_URL explicitly at the scratch container.
# Nothing here can reach the Neon endpoint in backend/.env.
#
#   bash bug-hunt/repro/phase1-failure-matrix.sh
set -u

cd "$(dirname "$0")/../../backend" || exit 1
PY=.venv/Scripts/python.exe
SCRATCH_DB="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt"
SECRET="bughunt-scratch-secret-not-production-32bytes"

probe() {
  # $1 = label, rest = env assignments
  local label="$1"; shift
  echo "════════════════════════════════════════════════════════════════"
  echo "CASE: $label"
  echo "────────────────────────────────────────────────────────────────"
  env "$@" timeout 180 "$PY" - <<'PY' 2>&1 | tail -14
import asyncio, logging
logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
from app.main import app, lifespan
async def main():
    try:
        async with lifespan(app):
            print(">>> VERDICT: BOOTED  (now check whether it can actually answer)")
    except Exception as e:
        print(f">>> VERDICT: REFUSED  {type(e).__name__}")
        print(f">>> MESSAGE: {str(e)[:400]}")
asyncio.run(main())
PY
  echo
}

# (b) database unreachable — port nobody is listening on
probe "DB unreachable" \
  DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55999/aspire_bughunt" \
  SESSION_SECRET="$SECRET" VALKEY_URL="redis://127.0.0.1:6380/9"

# (a) Valkey down — DB fine, cache pointed at a dead port
probe "Valkey down" \
  DATABASE_URL="$SCRATCH_DB" SESSION_SECRET="$SECRET" \
  VALKEY_URL="redis://127.0.0.1:6399/9"

# (d) empty knowledge base — migrated DB, zero documents rows
probe "Empty knowledge base" \
  DATABASE_URL="$SCRATCH_DB" SESSION_SECRET="$SECRET" \
  VALKEY_URL="redis://127.0.0.1:6380/9"

# (c) invalid LLM key
probe "Invalid LLM API key" \
  DATABASE_URL="$SCRATCH_DB" SESSION_SECRET="$SECRET" \
  VALKEY_URL="redis://127.0.0.1:6380/9" \
  OPENAI_API_KEY="sk-invalid-deliberately-for-this-probe"

# (e) no SESSION_SECRET at all — the value .env.example ships
probe "Empty SESSION_SECRET (as .env.example ships it)" \
  DATABASE_URL="$SCRATCH_DB" SESSION_SECRET="" \
  VALKEY_URL="redis://127.0.0.1:6380/9"
