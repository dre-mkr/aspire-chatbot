#!/usr/bin/env bash
# S1-007b — severity probe for S1-007.
#
# With ZERO retrieved context (proven in S1-007), what does the assistant tell a
# Spanish- or French-speaking family asking who is eligible for the programme?
#
#   refuses / says it doesn't know  -> S1 (ES/FR users denied answers EN users get)
#   invents an eligibility rule     -> S0 (fabricated government benefit criteria)
#
# COST: 3 chat completions. SAFETY: scratch container only.
#
#   bash bug-hunt/repro/S1-007b-what-the-bot-says.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
ASPIRE_CACHE_NAMESPACE="bughunt-" \
.venv/Scripts/python.exe - <<'PY'
import json, logging, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level="CRITICAL")
from fastapi.testclient import TestClient
from app.main import app

ASKS = [
    ("en", "What does the 13 December 2023 date mean for eligibility?"),
    ("es", "¿Qué significa la fecha del 13 de diciembre de 2023?"),
    ("fr", "Que signifie la date du 13 décembre 2023 ?"),
]
# The ground truth in ASP-031, for comparison:
TRUTH = ("aged 5 to 18, and those who were 18 or under on 13 December 2023")

def collect(sse: str) -> str:
    out = []
    for line in sse.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except Exception:
            continue
        # The envelope is {"i": <seq>, "t": "<chunk>"} on `event: token`.
        v = payload.get("t")
        if isinstance(v, str):
            out.append(v)
    return "".join(out)

with TestClient(app, raise_server_exceptions=False) as c:
    print(f"GROUND TRUTH (ASP-031): {TRUTH}\n")
    for lang, q in ASKS:
        s = c.post("/v2/session", json={"device_id": f"probe-{lang}", "locale": lang})
        token = (s.json() or {}).get("token")
        r = c.post(
            "/v2/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": q, "locale": lang},
        )
        answer = collect(r.text).strip()
        print(f"-- [{lang}] {q}")
        print(f"   HTTP {r.status_code}")
        print(f"   ANSWER: {answer[:600] if answer else '(empty)'}")
        # Did it produce a date or an age range it could not have retrieved?
        nums = re.findall(r"\b(?:5|18|2023|13)\b", answer)
        print(f"   contains eligibility-shaped numbers: {sorted(set(nums)) or 'none'}")
        print()
PY
