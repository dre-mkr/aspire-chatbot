#!/usr/bin/env bash
# Phase 8 — auth & session, attacked.
#
# Forged / mutated / expired / cross-environment tokens, and IDOR: can one
# anonymous session read another's conversation by id?
#
# SAFETY: scratch container only. No model calls.
#
#   bash bug-hunt/repro/phase8-auth-session.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
ASPIRE_CACHE_NAMESPACE="bughunt-p8-" \
.venv/Scripts/python.exe - <<'PY'
import base64, json, logging, sys, time, uuid
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level="CRITICAL")
import jwt
from fastapi.testclient import TestClient
from app.main import app

FAILS = []
def check(label, ok, detail=""):
    if not ok: FAILS.append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")

SECRET = "bughunt-scratch-secret-not-production-32bytes"

def parts(tok):
    head, payload, sig = tok.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    return json.loads(base64.urlsafe_b64decode(pad(payload)))

with TestClient(app, raise_server_exceptions=False) as c:
    print("\n== graph session tokens (/v2) ==")
    tok = c.post("/v2/session", json={"device_id": "p8-a", "locale": "en"}).json()["token"]
    claims = parts(tok)
    print(f"  claims: persona={claims.get('per')} band={claims.get('band')} sid={str(claims.get('sid'))[:8]}...")

    # 1. signed with a trivially guessable key
    forged = jwt.encode(claims, "secret", algorithm="HS256")
    r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {forged}"}, json={"message": "hi"})
    check("a token signed with a guessed key is refused", r.status_code == 401, f"HTTP {r.status_code}")

    # 2. signed with the WRONG key
    wrong = jwt.encode(claims, "a-different-secret-of-sufficient-length-32", algorithm="HS256")
    r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {wrong}"}, json={"message": "hi"})
    check("a token signed with another key is refused", r.status_code == 401, f"HTTP {r.status_code}")

    # 3. tampered payload, original signature
    head, payload, sig = tok.split(".")
    bad = dict(claims); bad["band"] = "adult"; bad["per"] = "aurora"
    pad = lambda b: b.rstrip(b"=")
    mutated = ".".join([head, pad(base64.urlsafe_b64encode(json.dumps(bad).encode())).decode(), sig])
    r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {mutated}"}, json={"message": "hi"})
    check("a mutated payload with the original signature is refused", r.status_code == 401, f"HTTP {r.status_code}")

    # 4. alg=none
    none_tok = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode() + "." + \
               base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode() + "."
    r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {none_tok}"}, json={"message": "hi"})
    check("alg=none is refused", r.status_code == 401, f"HTTP {r.status_code}")

    # 5. expired
    expired = dict(claims); expired["exp"] = int(time.time()) - 3600
    r = c.post("/v2/chat/stream",
               headers={"Authorization": f"Bearer {jwt.encode(expired, SECRET, algorithm='HS256')}"},
               json={"message": "hi"})
    check("an expired token is refused", r.status_code == 401, f"HTTP {r.status_code}")

    # 6. escalation attempt: forge a wider band with the REAL key is impossible
    #    without the key, but check the server ignores a body that asks.
    r = c.post("/v2/session", json={"device_id": "p8-b", "locale": "en",
                                    "persona": "aurora", "age_band": "adult",
                                    "account_status": "guardian"})
    esc = parts(r.json()["token"])
    check("a session body cannot widen persona/band",
          esc.get("band") != "adult" or esc.get("per") != "aurora",
          f"got persona={esc.get('per')} band={esc.get('band')}")

    print("\n== anonymous account sessions (/api/auth) ==")
    a = c.post("/api/auth/anonymous", json={"device_id": "p8-dev-A"})
    b = c.post("/api/auth/anonymous", json={"device_id": "p8-dev-A"})
    check("the same device id yields two DIFFERENT identities",
          a.json()["user_id"] != b.json()["user_id"],
          "device id is not accepted as authentication")

    ta, tb = a.json()["token"], b.json()["token"]

    print("\n== IDOR: can B read A's conversations? ==")
    lst = c.get("/api/conversations", headers={"Authorization": f"Bearer {ta}"})
    check("A can list its own conversations", lst.status_code == 200, f"HTTP {lst.status_code}")

    # Enumerate: sequential + guessed ids, and A's real thread if any.
    probes = [str(uuid.UUID(int=n)) for n in range(1, 6)] + [
        "00000000-0000-0000-0000-000000000000",
        str(uuid.uuid4()),
    ]
    leaked = []
    for pid in probes:
        r = c.get(f"/api/conversations/{pid}", headers={"Authorization": f"Bearer {tb}"})
        if r.status_code == 200:
            leaked.append((pid, r.status_code))
    check("id enumeration returns nothing readable", not leaked, str(leaked[:3]))

    # And a real one owned by A, read with B's token.
    graph_a = c.post("/v2/session", json={"device_id": "p8-dev-A", "locale": "en"}).json()
    thread = graph_a["session_id"] if "session_id" in graph_a else parts(graph_a["token"])["sid"]
    r = c.get(f"/api/conversations/{thread}", headers={"Authorization": f"Bearer {tb}"})
    check("B cannot read a thread id belonging to A", r.status_code in (403, 404),
          f"HTTP {r.status_code}")

    print("\n== token reuse across environments ==")
    other_env = jwt.encode(claims, "a-totally-different-deployment-secret-32b", algorithm="HS256")
    r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {other_env}"}, json={"message": "hi"})
    check("a token from another deployment is refused", r.status_code == 401, f"HTTP {r.status_code}")

print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAIL: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
PY
