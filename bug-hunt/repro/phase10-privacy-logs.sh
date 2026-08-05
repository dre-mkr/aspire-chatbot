#!/usr/bin/env bash
# Phase 10 — does the service write children's data to the log?
#
# The brief rates PII exposure S0 on a minors' programme. This drives a turn
# containing a name, an address, a school and an email through the graph with
# logging at DEBUG (louder than production) and greps everything written.
#
# SAFETY: scratch container. Costs 1 chat completion.
#
#   bash bug-hunt/repro/phase10-privacy-logs.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
ASPIRE_CACHE_NAMESPACE="bughunt-p10-" \
LOG_LEVEL=DEBUG \
.venv/Scripts/python.exe - <<'PY'
import io, logging, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

captured = io.StringIO()
handler = logging.StreamHandler(captured)
handler.setLevel(logging.DEBUG)
root = logging.getLogger()
root.setLevel(logging.DEBUG)
root.addHandler(handler)

from fastapi.testclient import TestClient
from app.main import app

# Distinctive strings so a match cannot be a coincidence.
NEEDLES = {
    "child name":     "Zephaniah Quillfeather",
    "address":        "17 Marigold Crescent, Basseterre",
    "school":         "Saint Ambrose Preparatory",
    "email":          "zephaniah.q@example-parent.test",
    "national id":    "SKN-99-887766",
    "device id":      "p10-device-CANARY-4471",
}
# Deliberately a question that produces PROSE. "Am I eligible?" opens the
# eligibility CARD, which emits a directive and no prose -- a valid turn, but it
# exercises less of the pipeline than a full Q&A generation does.
MESSAGE = (
    f"Hi, my name is {NEEDLES['child name']}, I live at {NEEDLES['address']}, "
    f"I go to {NEEDLES['school']}. My mum's email is {NEEDLES['email']} and my "
    f"ID is {NEEDLES['national id']}. What is the ASPIRE Programme?"
)

with TestClient(app, raise_server_exceptions=False) as c:
    tok = c.post("/v2/session", json={"device_id": NEEDLES["device id"], "locale": "en"}).json()["token"]
    r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {tok}"},
               json={"message": MESSAGE})
    print(f"turn -> HTTP {r.status_code}, {len(r.text)} bytes of SSE")

root.removeHandler(handler)
logs = captured.getvalue()
print(f"captured {len(logs)} bytes of log across {len(logs.splitlines())} lines\n")

leaks = []
for label, needle in NEEDLES.items():
    if needle in logs:
        line = next((l for l in logs.splitlines() if needle in l), "")
        leaks.append((label, needle, line[:160]))

for label, needle in NEEDLES.items():
    hit = any(label == l for l, _, _ in leaks)
    print(f"  {'LEAK' if hit else 'ok  '}  {label:12} {needle[:40]!r}")

# The whole question, verbatim, is the worst case.
if MESSAGE[:60] in logs:
    leaks.append(("full question", MESSAGE[:60], ""))
    print("  LEAK  full question text appears in the log")
else:
    print("  ok    full question text does not appear in the log")

print()
if leaks:
    print(f"{len(leaks)} PII LEAK(S) IN LOGS:")
    for label, needle, line in leaks:
        print(f"  [{label}] {line or needle}")
else:
    print("NO PII IN LOGS")
sys.exit(1 if leaks else 0)
PY
