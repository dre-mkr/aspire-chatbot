# COVERAGE — what was tested, and what was not

Branch `bug-hunt/2026-08-05` against `e5c4466`. Companion to `FINDINGS.md`.

The short version: **roughly a third of the brief was executed.** Phases 0–3 are
substantially done, 4 and 10 are partial, and 5–9 were not started. The
untested part is the part a government client is most exposed by, and it is
untested because it needs model spend I stopped short of committing without
asking.

---

## Phase-by-phase

| Phase | Status | What ran | What did not |
|---|---|---|---|
| **0 — Recon** | ✅ Done | Repo map, 48 routes enumerated with prefixes, 10 agents, graph pipeline, background job, external deps, env-var diff (119 code vs 66 documented), persona/band/language vocabularies and their 3 enforcement layers, scaffolding-smell sweep. `INVENTORY.md` written before proceeding. | — |
| **1 — Cold start** | ✅ Done | Fresh clone to temp dir, README followed verbatim, boot attempted. Failure matrix: DB unreachable, Valkey down, empty KB, invalid LLM key, empty `SESSION_SECRET`. Migrations run on scratch DB; vector extension and index inventory verified post-migration. | Frontend boot and health-check pass. `vite build` / SSR server not exercised in the cold clone. |
| **2 — Static sweep** | 🟡 Partial | `ruff check --select F,E9` (7 errors, 2 of them live crash bugs). `tsc --noEmit` clean. Suppression census (10 `type: ignore`, 2 `noqa`). AST scan for blocking calls inside `async def` — clean. | **No mypy/pyright run** — neither is installed or configured, and adding a type checker to 128 untyped-checked files would produce noise, not findings, without a baseline. No N+1 / unbounded-SELECT analysis of the history and retrieval paths. Suppressions counted but not individually judged. |
| **3 — Contract drift** | 🟡 Partial | Persona / age-band / language vocabularies enumerated on the backend and cross-checked against `frontend/src/lib/aspire/personas.ts`. Streaming envelope inspected structurally. | **No systematic field-by-field diff** of every request/response shape. Optionality, nullability, date formats and numeric types not compared. Gamification and eligibility payloads not diffed. No test of what the UI does with an unhandled enum value. |
| **4 — API assault** | 🟡 Partial | Malformed bodies (empty, wrong type, null) on `/v2/chat/stream`; unauthenticated reads on `/api/conversations`; malformed id. Error bodies checked for `Traceback`, `site-packages`, `asyncpg`, `SELECT`, filesystem paths, `sk-`, connection strings — all clean. Honest-status-code check → found S2-005. | **Oversized inputs** (50k-char message, 10MB payload, 500-message history). **Unicode/injection corpus** (emoji, RTL, ZWJ, accented ES/FR, SQL-ish, `{{template}}`, newline floods). **Idempotency/replay** under concurrency. 43 of 48 routes were never called. |
| **5 — KB & retrieval** | ❌ Not started | Row count observed incidentally (706 in `documents`, 706 in the CSV), all at 3072 dims, single ingest batch. Dimension guard attacked and held. | **Everything that matters.** No duplicate/empty/orphan/null-embedding audit. No 30-question hit-rate scoring. No 10 unanswerable questions (does it invent a government fact?). No cross-lingual EN/ES/FR retrieval comparison. **No numeric-precision testing on interest rates, age eligibility, deposit minimums or account types** — the brief rates a drifted number S0. |
| **6 — Conversational** | ❌ Not started | — | Persona fidelity (10 turns × 4). Persona bleed on mid-session switch. Language switching and mixed-language messages. Memory at turn 20 / summarizer threshold. Account-status routing incl. unknown/null. Gamification (3 games × complete/abandon/refresh/out-of-order/empty/duplicate/post-end). **All safety testing** — prompt injection, PII solicitation, investment guarantees, medical/legal, in 3 languages. |
| **7 — Frontend E2E** | ❌ Not started | — | Journeys per persona, desktop + iPhone SE. Compositor→dock transition ×20 with interrupt / 4× CPU throttle / back-nav / hard-refresh. Streaming typewriter and settled-block parser across fast/slow/markdown-mid-token/code/lists/links/emoji/ends-mid-block. Abort-by-navigation, second message while streaming. Back/forward, deep links, refresh mid-conversation, two tabs, offline-5s. Error-state screenshots. Keyboard and focus management. |
| **8 — Auth & session** | ❌ Not started | Observed only that `POST /v2/session` mints a token for an unauthenticated caller (used as step 1 of the S1-005 repro). | Signature validation against forged / expired / mutated-device-id / cross-environment tokens. Two devices one identity. Cleared storage. **IDOR enumeration of conversation ids across sessions.** Anonymous→identified upgrade and its mid-upgrade failure case. |
| **9 — Concurrency & load** | ❌ Not started | — | 20 concurrent streams. DB pool / Valkey connection / memory growth over 5 minutes. Cache stampede (10 identical cold). Valkey drop mid-request. p50/p95 for retrieval, first token, full response. Kill/restart Postgres and Valkey under load. |
| **10 — Security & privacy** | 🟡 Partial | Repo-wide secret scan (`sk-`, `AKIA`, private keys, connection strings) — clean; `.env` correctly untracked. Error-body leak probing — clean. Unauthorized-write finding S1-005. Debug-route existence leak S1-004. | **Log inspection for conversation content, child PII and device ids in plaintext** — the brief rates this S0 and it was not done. CORS / rate-limit / request-size **enforcement** (config was read; enforcement not exercised). `npm audit` / `pip-audit`. **KB-borne prompt-injection canary row.** Built-frontend-bundle secret scan (no `dist/` present). |

---

## Why the gaps exist

**Phases 5, 6 and most of 10's behavioural half need real model calls.** Doing
them properly is ~80 prompts × 3 languages × 4 personas, plus a 30-question
retrieval set and a 10-question refusal set. I stopped rather than commit that
spend unasked, and rather than produce a token version of the two phases that
matter most on a children's financial product — a shallow safety pass is worse
than none, because it reads as clearance.

**Phase 7 needs a running frontend + backend pair** and would use puppeteer, not
Playwright (see below). Standing that up is straightforward; it was a time
choice, not a blocker.

**Phase 9 needs a load harness** and a backend under sustained traffic, which
means model spend again unless the agent is stubbed. Stubbing it is the right
call and is the first thing I would build on resuming.

---

## Deviations from the brief

1. **Playwright → puppeteer.** The repo has no Playwright and ~60 existing
   puppeteer harnesses in `frontend/.impeccable/`. Adding a second browser
   automation stack to a repo with a stated no-new-dependencies rule seemed the
   wrong trade for a QA pass. Flagging rather than doing it silently.

2. **Neon branch → local pgvector container.** No `NEON_API_KEY` and no `neonctl`
   in this environment, so a Neon branch was not available. A disposable
   `pgvector/pgvector:pg16` container was used instead, which the brief permits.
   See `evidence/DB-TARGET-CONFIRMATION.md`.

3. **One product-code blocker worked around, not patched.** `ssl: "require"` is
   hardcoded (S2-004) and blocks any non-TLS Postgres. Rather than modify the
   app, TLS was enabled inside the scratch container with a self-signed cert.
   Product code is untouched on this branch.

4. **The brief's "~338 verified rows" is stale** — the KB is 706 rows. Likewise
   "FastAPI + LangChain" (it is LangGraph now), `/api/chat` (it is
   `/v2/chat/stream`), and BGE-M3 embeddings (it is `text-embedding-3-large` at
   3072 dims, with a 384-dim fastembed fallback). Noted in `INVENTORY.md` §1.

---

## Environment left standing

The scratch environment is still up and ready to resume from:

```
container      aspire-bughunt-pg   (pgvector/pgvector:pg16, TLS enabled)
DATABASE_URL   postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt
               — migrated to head, 706 documents rows at 3072 dims
VALKEY_URL     redis://127.0.0.1:6380/9   (db 9, namespace bughunt-)
```

Teardown: `docker rm -f aspire-bughunt-pg`

---

## If you approve one thing

Close Phase 5's numeric-precision testing first. It is the only untested area
where a defect is **S0 by the brief's own rubric** — a drifted interest rate or
age threshold on a government financial programme for children — and it is
cheap: ~40 targeted questions against the real corpus, scored by hand against
`data/knowledge_base.csv`. Phase 6's safety pass is second for the same reason.
