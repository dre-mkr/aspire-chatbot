#!/usr/bin/env bash
# S0-002 — how much PII will the service collect from an unauthenticated child?
#
# `access.py:123` states the guarantee:
#
#     _ANONYMOUS: `register_agent_step1` collects only what can be collected
#     before an account exists, and nothing that would be PII about a minor.
#
# `register/graph.py:702` states the mechanism:
#
#     `register_agent_step1` is the anonymous variant: the same graph, and the
#     access matrix is what stops it reaching the slots that need an account.
#
# The mechanism does not exist. `allowed_agents()` is a pure function returning
# agent NAMES; it has no slot-level vocabulary and is never consulted again
# after routing. `build_production_register()` takes no arguments, so it cannot
# know which of the two names it was registered under, and both names are
# registered to it in the same loop.
#
# This drives the flow as an anonymous caller -- which is band `5-8`, persona
# `stella`, status `prospect`, the conservative default every first-time
# visitor gets -- and records every slot it is asked for.
#
# The cache namespace below is timestamped PER RUN. A fixed namespace replays
# cached turns, and that is not a hypothetical: this script reported the bug as
# still present after it had been fixed, because Valkey was serving the answers
# recorded by the run that first reproduced it.
#
# SAFETY: scratch container. Values supplied below are fictional. Costs ~10
# chat completions.
#
#   bash bug-hunt/repro/S0-002-anonymous-child-registration.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
ASPIRE_CACHE_NAMESPACE="bughunt-s0002-$(date +%s)-" \
.venv/Scripts/python.exe - <<'PY'
import json, logging, re, sys, uuid
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level="CRITICAL")
from fastapi.testclient import TestClient
from app.main import app
from app.graph.access import allowed_agents

print("== what the matrix hands an anonymous caller ==")
agents = allowed_agents("stella", "5-8", "prospect", user_id=None)
print(f"  allowed_agents(stella, 5-8, prospect, user_id=None) = {agents}")

print("\n== are the two registration names actually different graphs? ==")
from app.agents.register import graph as rg
import inspect
sig = inspect.signature(rg.build_production_register)
print(f"  build_production_register{sig}  <- takes no agent name, so it cannot vary by one")

def sse(raw):
    prose, directives, ev = [], [], None
    for line in raw.splitlines():
        if line.startswith("event: "):
            ev = line[7:].strip()
        elif line.startswith("data: "):
            try: d = json.loads(line[6:])
            except Exception: continue
            if ev == "token" and isinstance(d, dict) and "t" in d:
                prose.append(d["t"])
            elif ev == "directive":
                directives.append(d)
    return "".join(prose), directives

# Plausible answers a child would give. All fictional.
SCRIPT = [
    "I want to join ASPIRE",
    "Amara Rosewood",
    "14 March 2016",
    "amara.rosewood@example-child.test",
    "SKN-11-223344",
    "22 Frangipani Lane, Basseterre",
    "Saint Ambrose Preparatory",
    "yes",
]

# What we are watching for it to ask.
SENSITIVE = {
    "full name":     r"(full name|your name)",
    "date of birth": r"(date of birth|when were you born|birthday|d\.?o\.?b)",
    "national id":   r"(national id|id number|identification number)",
    "address":       r"(address|where do you live|where you live)",
    "email":         r"(e-?mail)",
    "phone":         r"(phone|mobile|telephone)",
    "school":        r"(school)",
    "id document":   r"(upload|photo of your id|birth certificate|document)",
}

asked = {}
thread = str(uuid.uuid4())

with TestClient(app, raise_server_exceptions=False) as c:
    tok = c.post("/v2/session", json={"device_id": "s0002", "locale": "en",
                                      "session_id": thread}).json()["token"]
    print(f"\n== walking the flow anonymously (thread {thread[:8]}...) ==")
    for i, msg in enumerate(SCRIPT, 1):
        r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {tok}"},
                   json={"message": msg, "session_id": thread})
        text, directives = sse(r.text)
        # A slot directive names the field being collected.
        slots = [d.get("slot") or d.get("label") for d in directives
                 if d.get("slot") or d.get("label")]
        blob = f"{text} {' '.join(str(s) for s in slots)}"
        for label, pat in SENSITIVE.items():
            if re.search(pat, blob, re.I) and label not in asked:
                asked[label] = f"turn {i}"
        print(f"  turn {i}: child says {msg[:34]!r}")
        print(f"          bot -> {text.strip()[:130]!r}")
        if slots:
            print(f"          slots: {slots}")

print("\n== sensitive fields solicited from an unauthenticated 5-8 band caller ==")
for label in SENSITIVE:
    where = asked.get(label)
    print(f"  {'ASKED' if where else 'no   '}  {label:14} {where or ''}")

n = len(asked)
print()
if n:
    print(f"S0-002 REPRODUCED: {n} sensitive field(s) solicited from an anonymous child:")
    print(f"  {', '.join(sorted(asked))}")
    print("  access.py:123 guarantees 'nothing that would be PII about a minor'.")
else:
    print("no sensitive fields solicited")
sys.exit(1 if n else 0)
PY
