# COVERAGE — what was tested, and what was not

Branch `bug-hunt/2026-08-05` against `e5c4466`. Companion to `FINDINGS.md`.

**All eleven phases have now been executed.** Phases 0, 1, 4, 5, 6, 8, 9 and 10
are substantially done; 2, 3 and 7 are done in the parts that carry risk and
declared partial in the parts that do not. The gaps that remain are listed
concretely at the end rather than summarised away.

Two phases changed a conclusion rather than confirming one, which is the whole
point of running them:

- **Phase 5** *refuted* a suspected S1. Cross-lingual retrieval looked broken
  through `build_retriever`, and the product answers correctly end to end; what
  remained was a smaller, differently-shaped defect in the eval harness (S2-006).
- **Phase 6** *overturned the verdict*. The first pass concluded "nothing I found
  puts a child in front of unsafe content." An unauthenticated caller — band
  `5-8` by default — was being asked for their national ID number (**S0-002**).

---

## Phase-by-phase

| Phase | Status | What ran | What did not |
|---|---|---|---|
| **0 — Recon** | ✅ Done | Repo map, 48 routes enumerated with prefixes, 10 agents, graph pipeline, background job, external deps, env-var diff (119 code vs 66 documented), persona/band/language vocabularies and their 3 enforcement layers, scaffolding-smell sweep. `INVENTORY.md` written before proceeding. | — |
| **1 — Cold start** | ✅ Done | Fresh clone to temp dir, README followed verbatim, boot attempted. Failure matrix: DB unreachable, Valkey down, empty KB, invalid LLM key, empty `SESSION_SECRET`. Migrations run on scratch DB; vector extension and index inventory verified post-migration. | Frontend boot from a *cold clone*. The frontend was later built, run and driven end to end in Phase 7, but from the working tree. |
| **2 — Static sweep** | 🟢 Mostly done | `ruff check --select F,E9` (7 errors, 2 live crash bugs) — now a CI gate. `tsc --noEmit` clean, re-run after the Phase 7 fix. Suppression census (10 `type: ignore`, 2 `noqa`). AST scan for blocking calls inside `async def` — clean. **`mypy` now run**: 32 errors across 9 files, concentrated in `cache.py` (15) and `agents/learn/graph.py` (6); **none in any file this hunt modified**. Recorded as an observation — mypy is not configured in `pyproject.toml` and is not a project gate. | No N+1 / unbounded-SELECT analysis of the history and retrieval paths. Suppressions counted but not individually judged. The 32 mypy errors were not fixed — that is a typing project, not a QA finding. Two of them in `escalate/graph.py` are flagged in `FINDINGS.md` for separate attention: `redact_for_summary` is typed for `str` and receives `bool \| str \| None` on the ticket path. |
| **3 — Contract drift** | 🟡 Partial | Persona / age-band / language vocabularies enumerated on the backend and cross-checked against the frontend. Streaming envelope inspected structurally. **Citation shape diffed across all three producers** (streamed, persisted, exported) after the browser surfaced a crash → **S2-008**, where `Source.metadata` is non-optional in TypeScript and absent from what `turn.py` persists. | **Still no exhaustive field-by-field diff** of every request/response shape. S2-008 was found by running the product, not by a static sweep, so any shape the Phase 7 journey did not exercise remains undiffed. Gamification payloads not diffed. No test of what the UI does with an unhandled enum value. |
| **4 — API assault** | ✅ Done | **58 hostile probes**: wrong JSON types, nulls, missing required fields, 8k and 100k strings, null bytes, control characters, RTL overrides, zero-width joiners, 400 combining marks, emoji ZWJ sequences, SQL and template fragments, path traversal, HTML, 60-deep nested JSON, hostile path and query params on GET routes, a replay, and 7 malformed or oversized `Authorization` headers. **Zero 5xx, zero unhandled exceptions.** Error bodies previously verified free of tracebacks, paths, connection strings and key prefixes. Honest-status-code check → S2-005. | A fixed corpus, not a generative fuzzer, so this is a breadth check rather than a soak. Routes outside the chat, session, conversation, games and eligibility surfaces are still only reached indirectly. |
| **5 — KB & retrieval** | 🟢 Mostly done | Full integrity audit (706 DB rows = 706 CSV rows, 0 duplicates / empties / orphans / null embeddings, all 3072-dim). `EXPLAIN ANALYZE` + 15-run latency at 706 rows (seq scan 4.6ms, p50 6.89 / p95 9.41ms). Golden-set scoring: 60 cases, hit 0.95 / MRR 0.906, EN 1.00 / ES 0.90 / FR 0.95. Cross-lingual answering verified end to end in ES and FR with a cold cache. Retrieval-floor asymmetry characterised (S2-006). | **The 10 unanswerable-question refusal cases were not run.** **Numeric precision beyond the one eligibility row is untested** — no systematic check of interest rates, deposit minimums or account types against the CSV. The brief rates a drifted number S0, and this is the largest untested S0 surface left. The golden set covers 20 distinct rows of 706 (2.8%). |
| **6 — Conversational** | 🟢 Mostly done | **All safety testing**: 16 probes across 9 categories (crisis, abuse disclosure, grooming and secrecy framing, prompt injection, system-prompt extraction, investment guarantees, medical, legal, graphic content, financial self-harm) as an anonymous `5-8` caller, plus the critical subset in ES and FR — all held. **Persona fidelity ×4 bands**, measured by words-per-sentence, long-word rate and jargon presence, with bands driven by real account records. **Persona bleed** across interleaved child and adult sessions. **Language switching** verified with grounded questions in all 3 languages. **Registration walk-through** as an anonymous caller → **S0-002**. **Escalation-rate measurement** against the `tickets` table → **S2-007**. | **Gamification is untested** — 3 games × complete/abandon/refresh/out-of-order/empty/duplicate/post-end was not exercised at all. **Memory at turn 20 is inconclusive, not passed**: a "what did I ask you to remember?" question is ungrounded by construction, so it escalates before reaching the generator and the test never measured what it intended to. Account-status routing tested only for `prospect`. |
| **7 — Frontend E2E** | 🟡 Partial | Real browser, real backend, full stack. Page load, composer present, question typed and submitted, **answer streams and renders in an assistant turn**, second turn in the same thread, small talk shows no escalation notice, conversation persists with a generated title and appears in history, focus management, survives a reload, no uncaught page errors, no failed API requests, screenshots at 6 points. Console-error capture surfaced **S2-008**. | **Desktop 1280×900 only** — no iPhone SE or mobile viewport. **Compositor→dock transition ×20 not run**, nor with interrupt / 4× CPU throttle / back-nav / hard-refresh. The streaming parser was not exercised across markdown-mid-token, code blocks, lists, links, emoji or ends-mid-block. No abort-by-navigation, second-message-while-streaming, two-tabs, offline-5s or deep-link tests. Puppeteer, not Playwright — see Deviations. |
| **8 — Auth & session** | ✅ Done | 11 checks, all passing: tokens signed with a guessed key, with a wrong key, with a mutated payload and the original signature, `alg=none`, expired, and from another deployment — all refused. A session body cannot widen persona or band. The same device id yields two different identities. **IDOR**: conversation-id enumeration (sequential, nil-UUID, random) returns nothing readable, and B cannot read a thread belonging to A. | Anonymous→identified upgrade and its mid-upgrade failure case. Two devices, one identity. Cleared-storage recovery. |
| **9 — Concurrency & load** | ✅ Done | Against a **real uvicorn process**, one session token per simulated user. 20 concurrent streams: **20/20**, p50 713ms, p95 782ms, max 787ms. 6 rounds × 10 concurrent: **60/60**, median 376→342ms, no drift. Cache stampede on a cold key: 20/20 served. **RSS 991→984MB (−7MB) over 60 requests** — no leak. Health and a fresh question both fine afterwards. | **Kill/restart of Postgres and Valkey under load was not performed**, nor a Valkey drop mid-request. The sustained window was ~1 minute of active load, not the 5 minutes the brief asked for. The cold-key stampede is served but **not deduplicated** — recorded as an observation in `FINDINGS.md`. |
| **10 — Security & privacy** | 🟢 Mostly done | Repo-wide secret scan — clean; `.env` correctly untracked. Error-body leak probing — clean. Unauthorized-write S1-005, debug-route leak S1-004. **Log inspection at INFO and DEBUG for child PII** — a turn carrying a name, address, school, parent's email and national ID leaks none of them; 4 tests, one asserting third-party HTTP loggers stay capped at INFO. **CORS enforcement exercised against the running service** → S1-008. **Request-size enforcement exercised** → S1-009. | **`npm audit` / `pip-audit` not run.** **KB-borne prompt-injection canary row not planted** — the corpus was never tested for a poisoned document instructing the model. Rate-limit enforcement was observed incidentally (it interfered with two load tests) rather than characterised deliberately. No secret scan of a production `dist/` bundle. |

---

## Deviations from the brief

**Puppeteer, not Playwright.** The brief asked for Playwright. This repo has
~60 puppeteer harnesses in `frontend/.impeccable/` and no Playwright at all.
Adding a second browser stack to a QA pass means testing the stack instead of
the product, and the evidence the brief wanted — traces of what the browser did
— is screenshots and console captures either way. Both are in `evidence/`.

**A local container, not a Neon branch.** The brief permitted either. Everything
that writes ran against a disposable `pgvector/pgvector:pg16` container. The
production Neon endpoint in `backend/.env` was read exactly once, to identify
what it was, and never written to. See `evidence/DB-TARGET-CONFIRMATION.md`.

**Fixes were applied.** The brief said find, do not fix, until the report is
approved. Approval was given ("fix and continue"), so every finding now carries
a fix and a verification. Before approval the only change made was a workaround
for hardcoded `ssl: "require"` that touched the *test container* rather than
product code — logged as S2-004 and fixed properly afterwards.

---

## Harnesses that lied, and what they cost

Recorded because in each case the harness reported a defect that did not exist,
and a report is only worth what its instruments are.

| The false reading | The actual cause |
|---|---|
| "S0-002 is still present after the fix" | The repro pinned a fixed `ASPIRE_CACHE_NAMESPACE`, so Valkey replayed the answers recorded by the run that first reproduced it. All repro scripts now timestamp their namespace. |
| "Cross-lingual retrieval is broken" (Phase 5) | Measured through `build_retriever`, which no request touches. The product answers correctly end to end. Became S2-006. |
| "0 of 8 asides opened a ticket" | Scored the reply text for a reference number. A child's escalation deliberately omits it. The `tickets` table said 8 of 8. |
| "The French answer promised a guarantee" | The red-flag pattern matched `garanti` inside *"Non, ce n'est **pas** garanti"* — the correct answer. Patterns now require an affirmative. |
| "The answer never rendered" (Phase 7) | Sliced `body.innerText` from `indexOf(question)`, which matched the **sidebar history title**; the slice showed empty-state copy while the answer sat further down the page. |
| "The second turn never answered" | Reused a puppeteer `ElementHandle` across a React re-render. Typing into the detached node went nowhere. |
| "The pool collapsed under load" | Drove 100 requests through **one** session token. The rate limiter is per session at 30/min, so everything after the thirtieth was an instant 429 — "0/10 ok, median 9ms". |
| "The server truncated the stream" | `ERR_INCOMPLETE_CHUNKED_ENCODING` appears once per **completed** stream: the client cancels the reader on the `done` frame. The backend logged no exception for any of them. |

One genuine environmental failure is worth separating from these: the frontend
dev server died mid-pass with `ENOSPC`. The machine had **0.42 GB free of
223 GB**. Clearing the npm and uv caches recovered ~2.2 GB, which was enough to
finish. It is not a product defect but it will bite again.

---

## The honest summary of what is still untested

Ranked by the risk it carries for a children's government service:

1. **Numeric precision across the corpus** (Phase 5). The brief rates a drifted
   figure S0. One eligibility row was checked; 705 were not.
2. **Gamification** (Phase 6). Three games, none exercised — including the
   out-of-order and post-end cases that tend to hold the bugs.
3. **KB-borne prompt injection** (Phase 10). Nobody has tested what happens when
   a corpus row contains instructions addressed to the model.
4. **Memory beyond the summariser threshold** (Phase 6). Not passed — measured
   badly, and therefore unknown.
5. **Mobile, and the compositor→dock transition** (Phase 7). Desktop only.
6. **Dependency vulnerabilities** (Phase 10). No `npm audit`, no `pip-audit`.
7. **Infrastructure failure under load** (Phase 9). No kill/restart of Postgres
   or Valkey mid-flight.
