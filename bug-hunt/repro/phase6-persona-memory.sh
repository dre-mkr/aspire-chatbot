#!/usr/bin/env bash
# Phase 6b — persona fidelity, persona bleed, language switching, memory.
#
# Four personas are not four prompt strings, they are four audiences: a
# six-year-old, a young teenager, a school-leaver, and a parent. The claim worth
# testing is not "does it sound different" but "does a six-year-old get an
# answer a six-year-old can read", and that is measurable: words per sentence,
# rate of long words, and whether financial jargon appears at all.
#
# Bands are derived from the account record (`account.claims_for`), never from
# the request -- so the fixtures here create real users and set a real date of
# birth, rather than asking for a band and being ignored.
#
# NOTE: the cache namespace is timestamped per run. A fixed one replays cached
# turns and will happily report a stale result as a current one.
#
# SAFETY: scratch container. Costs ~35 chat completions.
#
#   bash bug-hunt/repro/phase6-persona-memory.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
ASPIRE_CACHE_NAMESPACE="bughunt-p6pm-$(date +%s)-" \
.venv/Scripts/python.exe - <<'PY'
import asyncio, json, logging, pathlib, re, sys, uuid
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level="CRITICAL")
from fastapi.testclient import TestClient
from app.main import app

EV = pathlib.Path(__file__).resolve().parents[2] / "bug-hunt" / "evidence"
EV.mkdir(parents=True, exist_ok=True)
FAILS = []
def check(label, ok, detail=""):
    if not ok: FAILS.append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")

def sse(raw):
    prose, ev = [], None
    for line in raw.splitlines():
        if line.startswith("event: "): ev = line[7:].strip()
        elif line.startswith("data: ") and ev == "token":
            try: prose.append(json.loads(line[6:]).get("t", ""))
            except Exception: pass
    return "".join(prose).strip()

# ── readability, crudely but consistently ────────────────────────────────────
JARGON = re.compile(
    r"\b(compound interest|diversification|portfolio|equity|liquidity|"
    r"amortis|principal balance|annualis|yield curve|asset allocation|"
    r"capital gains|tax-deferred|maturity date)\w*", re.I)

def readability(text):
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    if not words or not sentences:
        return {"wps": 0.0, "long_word_rate": 0.0, "jargon": []}
    def syllables(w):
        return max(1, len(re.findall(r"[aeiouy]+", w.lower())))
    long_words = [w for w in words if syllables(w) >= 4]
    return {
        "wps": round(len(words) / len(sentences), 1),
        "long_word_rate": round(len(long_words) / len(words), 3),
        "jargon": sorted({m.group(0).lower() for m in JARGON.finditer(text)}),
    }

# ── fixtures: real users with real dates of birth ────────────────────────────
#
# A DIRECT asyncpg connection, not `app.db.session`. The app's engine binds its
# pool to the loop the TestClient runs in, and driving it from a second loop
# here raises "attached to a different loop" rather than doing anything useful.
import asyncpg, datetime, os

DSN = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")

async def _set_dob(user_id, dob, is_minor):
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            "UPDATE users SET date_of_birth = $1, is_minor = $2 WHERE id = $3",
            datetime.date.fromisoformat(dob), is_minor, uuid.UUID(str(user_id)))
    finally:
        await conn.close()

def set_dob(user_id, dob, is_minor):
    asyncio.run(_set_dob(user_id, dob, is_minor))

QUESTION = "How does ASPIRE help me save money?"
results = {}

with TestClient(app, raise_server_exceptions=False) as c:
    def account(dob, is_minor, tag):
        r = c.post("/api/auth/anonymous", json={"device_id": f"p6-{tag}"}).json()
        set_dob(r["user_id"], dob, is_minor)
        return r["token"]

    def graph_token(account_token=None, locale="en", session_id=None, persona=None):
        h = {"Authorization": f"Bearer {account_token}"} if account_token else {}
        body = {"device_id": "p6", "locale": locale}
        if session_id: body["session_id"] = session_id
        if persona: body["persona"] = persona
        return c.post("/v2/session", headers=h, json=body).json()

    def turn(tok, msg, session_id):
        r = c.post("/v2/chat/stream", headers={"Authorization": f"Bearer {tok}"},
                   json={"message": msg, "session_id": session_id})
        return sse(r.text)

    # ── 1. persona fidelity ──────────────────────────────────────────────────
    print("== persona fidelity: the same question to four audiences ==")
    BANDS = [
        ("2019-03-14", True,  "5-8",   "child6"),
        ("2012-03-14", True,  "13-15", "teen14"),
        ("2009-03-14", True,  "16-18", "teen17"),
        ("1988-03-14", False, "adult", "parent"),
    ]
    for dob, minor, band, tag in BANDS:
        at = account(dob, minor, tag)
        s = graph_token(at)
        claims_band = json.loads(
            __import__("base64").urlsafe_b64decode(
                s["token"].split(".")[1] + "==").decode()).get("band")
        tid = str(uuid.uuid4())
        text = turn(s["token"], QUESTION, tid)
        m = readability(text)
        results[band] = {"claimed_band": claims_band, "persona": s.get("persona"),
                         "text": text, **m}
        print(f"  {band:6} (band in token: {claims_band or '?'})  "
              f"wps={m['wps']:5}  long={m['long_word_rate']:.3f}  jargon={m['jargon']}")
        print(f"          {text[:130]!r}")

    print("\n== is the youngest band actually getting simpler language? ==")
    young, adult = results.get("5-8"), results.get("adult")
    if young and adult and young["text"] and adult["text"]:
        check("a 5-8 answer is no denser than the adult answer",
              young["long_word_rate"] <= adult["long_word_rate"] + 0.02,
              f"5-8 long-word rate {young['long_word_rate']} vs adult {adult['long_word_rate']}")
        check("a 5-8 answer uses shorter sentences than the adult answer",
              young["wps"] <= adult["wps"] + 3,
              f"5-8 {young['wps']} wps vs adult {adult['wps']} wps")
    check("no financial jargon reaches the 5-8 band",
          not (young or {}).get("jargon"), str((young or {}).get("jargon")))
    check("no financial jargon reaches the 13-15 band",
          not results.get("13-15", {}).get("jargon"),
          str(results.get("13-15", {}).get("jargon")))

    # ── 2. persona bleed across concurrent sessions ─────────────────────────
    print("\n== persona bleed: two bands interleaved in one process ==")
    at_child = account("2019-06-01", True, "bleed-child")
    at_adult = account("1985-06-01", False, "bleed-adult")
    sc, sa = graph_token(at_child), graph_token(at_adult)
    tc, ta = str(uuid.uuid4()), str(uuid.uuid4())
    bleed = []
    for i in range(3):
        a = turn(sc["token"], "What is ASPIRE?", tc)
        b = turn(sa["token"], "What is ASPIRE?", ta)
        bleed.append((readability(a), readability(b)))
    child_j = [x for r, _ in bleed for x in r["jargon"]]
    check("interleaved turns never put jargon in the child's answers",
          not child_j, str(child_j))
    check("the two bands do not converge on identical text",
          any(r["wps"] != s["wps"] for r, s in bleed),
          "every interleaved pair had identical sentence length")

    # ── 3. language switching mid-conversation ──────────────────────────────
    print("\n== language switching mid-conversation ==")
    ats = account("1990-01-01", False, "lang")
    s = graph_token(ats, locale="en")
    tid = str(uuid.uuid4())
    en = turn(s["token"], "What is ASPIRE?", tid)
    s_es = graph_token(ats, locale="es", session_id=tid)
    es = turn(s_es["token"], "¿Puedes responderme en español por favor?", tid)
    s_fr = graph_token(ats, locale="fr", session_id=tid)
    fr = turn(s_fr["token"], "Peux-tu me répondre en français s'il te plaît ?", tid)
    def looks(lang, t):
        marks = {"es": r"\b(el|la|los|las|para|que|con|ahorro|dinero)\b",
                 "fr": r"\b(le|la|les|pour|que|avec|épargne|argent)\b"}[lang]
        return len(re.findall(marks, t, re.I)) >= 3
    print(f"  en -> {en[:80]!r}")
    print(f"  es -> {es[:80]!r}")
    print(f"  fr -> {fr[:80]!r}")
    check("switching to es produces Spanish", looks("es", es), es[:60])
    check("switching to fr produces French", looks("fr", fr), fr[:60])

    # ── 4. memory at turn 20 ────────────────────────────────────────────────
    print("\n== memory: is turn 1 still available at turn 20? ==")
    atm = account("1990-01-01", False, "mem")
    sm = graph_token(atm)
    tid = str(uuid.uuid4())
    SECRET = "Marigold"
    turn(sm["token"], f"Remember this word, it matters to me: {SECRET}. "
                      "I will ask you for it later.", tid)
    for i in range(2, 20):
        turn(sm["token"], f"Tell me one fact about saving money. (number {i})", tid)
    recall = turn(sm["token"], "What was the word I asked you to remember?", tid)
    print(f"  turn 20 -> {recall[:150]!r}")
    check("the word from turn 1 survives to turn 20", SECRET.lower() in recall.lower(),
          "rolling summary drops it -- SUMMARY_AFTER_MESSAGES=12")

out = EV / "phase6-persona-memory.json"
out.write_text(json.dumps(
    {"personas": results, "memory_recall": recall, "language": {"en": en, "es": es, "fr": fr}},
    indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nevidence -> {out}")
print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAIL: ' + '; '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
PY
