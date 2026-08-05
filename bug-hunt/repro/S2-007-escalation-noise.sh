#!/usr/bin/env bash
# S2-007 — how many staff tickets does ordinary conversation open?
#
# `qa/nodes.py:20` is deliberate and right: "Ungrounded means escalate, not
# guess." A government service that invents an answer about a child's savings
# account is worse than one that fetches a human.
#
# But `escalate/graph.py:22` says what an escalation IS: "A ticket is read by
# staff, exported to a case system and joined to a record." So the cost of an
# ungrounded turn is a row in `tickets` and a person's attention -- and the
# ungrounded set includes every conversational aside, because "can you repeat
# that?" retrieves nothing from a knowledge base about savings accounts.
#
# This measures the rate on turns that are not questions about ASPIRE at all,
# and counts the `tickets` rows they produce.
#
# Also re-runs the language check that the first pass got wrong: asking "can you
# reply in Spanish?" is itself ungrounded, so it escalated, and the escalation
# came back correctly localised -- which the detector then scored as a language
# failure. Real ASPIRE questions in each language are the right probe.
#
# NOTE: cache namespace is timestamped per run.
#
# SAFETY: scratch container. Costs ~16 chat completions.
#
#   bash bug-hunt/repro/S2-007-escalation-noise.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
ASPIRE_CACHE_NAMESPACE="bughunt-s2007-$(date +%s)-" \
.venv/Scripts/python.exe - <<'PY'
import asyncio, json, logging, os, re, sys, uuid
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level="CRITICAL")
import asyncpg
from fastapi.testclient import TestClient
from app.main import app

DSN = os.environ["DATABASE_URL"]

async def _tickets():
    conn = await asyncpg.connect(DSN)
    try:
        return await conn.fetchval("SELECT count(*) FROM tickets")
    finally:
        await conn.close()

def tickets():
    return asyncio.run(_tickets())

def sse(raw):
    prose, ev = [], None
    for line in raw.splitlines():
        if line.startswith("event: "): ev = line[7:].strip()
        elif line.startswith("data: ") and ev == "token":
            try: prose.append(json.loads(line[6:]).get("t", ""))
            except Exception: pass
    return "".join(prose).strip()

# A reference number in the reply is the observable signature of a ticket.
TICKETED = re.compile(r"\b(ASP-[0-9A-F]{6,}|referencia|référence|reference)\b", re.I)

# Things a person says to a chatbot that are not questions about ASPIRE.
ASIDES = [
    "hello",
    "thanks!",
    "ok",
    "can you say that again?",
    "sorry, can you explain that more simply?",
    "what did I just ask you?",
    "wait, I don't understand",
    "who are you?",
]

# Real ASPIRE questions, one per language. These SHOULD be grounded.
LANG = [
    ("en", "What is the ASPIRE Programme?"),
    ("es", "¿Qué es el Programa ASPIRE?"),
    ("fr", "Qu'est-ce que le Programme ASPIRE ?"),
]

FAILS = []
def check(label, ok, detail=""):
    if not ok: FAILS.append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")

before = tickets()
print(f"tickets in the table before: {before}\n")

with TestClient(app, raise_server_exceptions=False) as c:
    def tok(locale="en"):
        return c.post("/v2/session", json={"device_id": "s2007", "locale": locale}).json()["token"]

    print("== conversational asides ==")
    t = tok()
    escalated = []
    for msg in ASIDES:
        n0 = tickets()
        text = sse(c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {t}"},
                          json={"message": msg, "session_id": str(uuid.uuid4())}).text)
        # The DB row is the ground truth, NOT the reply text. A child's
        # escalation deliberately omits the reference number (escalate/graph.py:99),
        # so scoring the prose for "ASP-xxxxxx" reports every child ticket as a
        # non-ticket -- which is exactly how this script first scored 0/8 while
        # the table gained eight rows.
        opened = tickets() - n0
        if opened: escalated.append(msg)
        print(f"  {'TICKET' if opened else 'ok    '}  {msg[:42]!r}")
        print(f"            {text[:110]!r}")

    print("\n== the same question in three languages, properly grounded ==")
    answers = {}
    lang_before = tickets()
    for locale, q in LANG:
        text = sse(c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {tok(locale)}"},
                          json={"message": q, "session_id": str(uuid.uuid4())}).text)
        answers[locale] = text
        print(f"  {locale}: {text[:100]!r}")

lang_tickets = tickets() - lang_before
after = tickets()
print(f"\ntickets in the table after: {after}  (+{after - before})")

print()
check("an ordinary aside does not open a staff ticket",
      not escalated, f"{len(escalated)}/{len(ASIDES)} did: {escalated}")
check("real ASPIRE questions in en/es/fr open no tickets",
      lang_tickets == 0, f"{lang_tickets} ticket(s) from 3 grounded questions")
for locale, _ in LANG:
    check(f"the {locale} answer is non-empty",
          bool(answers.get(locale, "").strip()), "empty")

print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAIL'}")
sys.exit(1 if FAILS else 0)
PY
