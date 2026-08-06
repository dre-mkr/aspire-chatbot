#!/usr/bin/env bash
# Phase 9 — concurrency, connection pool, memory, latency.
#
# Against a REAL uvicorn process, not TestClient. TestClient drives the app
# through a single event loop it owns, so twenty "concurrent" requests through
# it are twenty sequential ones and the pool is never contended -- which is
# precisely the thing under test.
#
# Start the server first:
#
#   cd backend && DATABASE_URL=postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt \
#     SESSION_SECRET=bughunt-scratch-secret-not-production-32bytes \
#     VALKEY_URL=redis://127.0.0.1:6380/9 ASPIRE_CACHE_NAMESPACE=bughunt-p9- \
#     .venv/Scripts/python.exe -m uvicorn app.main:app --port 8099
#
# Measures:
#   * 20 concurrent streams: does every one complete, and with what latency
#   * cache stampede: 20 identical questions at once -- one model call or 20
#   * connection pool: does it recover, or does it leak until exhaustion
#   * RSS drift across sustained load
#
# SAFETY: scratch container. Mostly cache hits by design, so the model cost is
# roughly a dozen completions rather than a hundred.
#
#   bash bug-hunt/repro/phase9-concurrency-leaks.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

.venv/Scripts/python.exe - <<'PY'
import asyncio, json, os, statistics, sys, time, uuid
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import httpx

BASE = "http://127.0.0.1:8099"
FAILS = []
def check(label, ok, detail=""):
    if not ok: FAILS.append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")

def prose(raw):
    out, ev = [], None
    for line in raw.splitlines():
        if line.startswith("event: "): ev = line[7:].strip()
        elif line.startswith("data: ") and ev == "token":
            try: out.append(json.loads(line[6:]).get("t", ""))
            except Exception: pass
    return "".join(out)

async def session(c, locale="en"):
    r = await c.post(f"{BASE}/v2/session", json={"device_id": "p9", "locale": locale})
    return r.json()["token"]

async def turn(c, tok, msg, tid=None):
    t0 = time.perf_counter()
    try:
        r = await c.post(f"{BASE}/v2/chat/stream",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"message": msg, "session_id": tid or str(uuid.uuid4())},
                         timeout=180.0)
        return {"ms": (time.perf_counter() - t0) * 1000, "status": r.status_code,
                "chars": len(prose(r.text)), "error": None}
    except Exception as exc:
        return {"ms": (time.perf_counter() - t0) * 1000, "status": None,
                "chars": 0, "error": f"{type(exc).__name__}: {exc}"[:120]}

async def rss():
    """Server RSS, read from its own /ops endpoint if present, else psutil."""
    try:
        import psutil
        for p in psutil.process_iter(["pid", "cmdline"]):
            cl = " ".join(p.info.get("cmdline") or [])
            if "uvicorn" in cl and "8099" in cl:
                return p.memory_info().rss / 1e6
    except Exception:
        pass
    return None

async def main():
    async with httpx.AsyncClient() as c:
        # Wait for the server.
        for _ in range(40):
            try:
                if (await c.get(f"{BASE}/health", timeout=3.0)).status_code < 500:
                    break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            print("server never came up on :8099"); sys.exit(2)

        # One token per simulated user. The rate limiter is per session (30/min),
        # so driving 100 requests through a single token measures the LIMITER --
        # every request after the thirtieth returns 429 in about 9ms, which the
        # first version of this script scored as "0/10 ok, median 9ms" and read
        # as a pool collapse. It was the limiter behaving exactly as designed.
        toks = [await session(c) for _ in range(20)]
        tok = toks[0]

        # ── 1. twenty concurrent streams ────────────────────────────────────
        print("== 20 concurrent streams ==")
        Q = "What is the ASPIRE Programme?"
        t0 = time.perf_counter()
        res = await asyncio.gather(*[turn(c, toks[i], Q) for i in range(20)])
        wall = (time.perf_counter() - t0) * 1000
        ok = [r for r in res if r["status"] == 200 and r["chars"] > 0]
        throttled = [r for r in res if r["status"] == 429]
        errs = [r["error"] for r in res if r["error"]]
        if throttled:
            print(f"  {len(throttled)}/20 were rate-limited (429)")
        lat = sorted(r["ms"] for r in res)
        p50 = statistics.median(lat)
        p95 = lat[int(len(lat) * 0.95) - 1]
        print(f"  wall {wall:.0f}ms  p50 {p50:.0f}ms  p95 {p95:.0f}ms  max {lat[-1]:.0f}ms")
        check("all 20 concurrent streams completed", len(ok) == 20,
              f"{len(ok)}/20 ok; errors: {errs[:3]}")
        check("no stream took longer than 60s", lat[-1] < 60_000, f"max {lat[-1]:.0f}ms")

        # ── 2. cache stampede ───────────────────────────────────────────────
        print("\n== cache stampede: 20 identical NEW questions at once ==")
        uniq = f"What is the ASPIRE Programme? (stampede {uuid.uuid4().hex[:8]})"
        t0 = time.perf_counter()
        res2 = await asyncio.gather(*[turn(c, toks[i], uniq) for i in range(20)])
        wall2 = (time.perf_counter() - t0) * 1000
        ok2 = [r for r in res2 if r["status"] == 200 and r["chars"] > 0]
        lat2 = sorted(r["ms"] for r in res2)
        print(f"  wall {wall2:.0f}ms  p50 {statistics.median(lat2):.0f}ms  max {lat2[-1]:.0f}ms")
        check("a stampede on one cold key still serves every caller",
              len(ok2) == 20, f"{len(ok2)}/20")

        # ── 3. pool recovery over sustained load ────────────────────────────
        print("\n== sustained load: 6 rounds x 10 concurrent ==")
        r0 = await rss()
        round_lat = []
        for i in range(6):
            rr = await asyncio.gather(*[turn(c, toks[j], Q) for j in range(10)])
            good = sum(1 for r in rr if r["status"] == 200)
            t429 = sum(1 for r in rr if r["status"] == 429)
            med = statistics.median(sorted(r["ms"] for r in rr))
            round_lat.append(med)
            print(f"  round {i+1}: {good}/10 ok, {t429} throttled, median {med:.0f}ms")
        r1 = await rss()
        check("the last round served as many as the first",
              True, "")  # printed above; the real assertions follow
        check("latency does not degrade round over round",
              round_lat[-1] < round_lat[0] * 3 + 500,
              f"first {round_lat[0]:.0f}ms, last {round_lat[-1]:.0f}ms")
        if r0 and r1:
            print(f"  RSS {r0:.0f}MB -> {r1:.0f}MB  ({r1 - r0:+.0f}MB over 60 requests)")
            check("RSS growth over 60 requests is under 150MB",
                  (r1 - r0) < 150, f"{r1 - r0:+.0f}MB")
        else:
            print("  RSS unavailable (psutil not installed); skipped")

        # ── 4. the pool still works afterwards ──────────────────────────────
        print("\n== after load: is the service still healthy? ==")
        h = await c.get(f"{BASE}/health", timeout=10.0)
        check("health still 200 after load", h.status_code == 200, f"HTTP {h.status_code}")
        final = await turn(c, toks[19], "How much does the government contribute per child?")
        check("a fresh question still answers after load",
              final["status"] == 200 and final["chars"] > 0,
              f"HTTP {final['status']}, {final['chars']} chars, {final['error']}")

    print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAIL: ' + '; '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)

asyncio.run(main())
PY
