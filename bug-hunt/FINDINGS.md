# ASPIRE AI — hostile QA findings

Branch `bug-hunt/2026-08-05`, against `e5c4466` (`feat/aspire-langgraph-platform`).
All write-path testing ran against a disposable `pgvector/pgvector:pg16`
container. The Neon endpoint in `backend/.env` was read once to identify it and
never written to — see `evidence/DB-TARGET-CONFIRMATION.md`.

---

## Verdict

**No — not shippable to a government client next week, but the gap is narrower
than the count suggests.** Nothing I found puts a child in front of unsafe
content, leaks a secret, or exposes another person's conversation, and the parts
of this system that were built with care are genuinely careful: the access
matrix, the embedding-dimension guard, the empty-corpus refusal and the error
surfaces all behaved correctly under attack. What is broken is the *operational
skin* around a sound core. A new engineer cannot start this service by following
its own README; the readiness probe a ministry's load balancer would poll returns
500 on every call in every deployment; and one endpoint in the graph API signs an
upload URL for whatever `application_id` the caller types, in a codebase that
checks ownership correctly one file away. Those are shallow fixes — the two
crash bugs are single missing imports — but they are exactly the class of defect
that turns a launch day into an incident, and the reason they survived is
structural: **there is no Python linter in CI**, and `ruff check --select F`
finds both in under a second. Fix the seven S1s, add the linter, and this is
defensible. Ship it as-is and the first thing the ministry's ops team does —
wire up `/ready` — fails.

Phase 5 is now done and it moved the verdict in the product's favour: the corpus
is clean, retrieval latency is fine at 706 rows, and cross-lingual answering
works correctly in Spanish and French — a suspected S1 there was refuted by
measurement. Phases 6–9 (conversational behaviour and safety, frontend E2E,
auth, load) remain untouched. See **Coverage gaps**; that is a large, deliberate,
and honestly declared hole, not a clean bill of health.

---

## Findings table

| ID | Sev | Area | Summary |
|---|---|---|---|
| S1-001 | S1 | docs / cold start | Following the README verbatim cannot start the service; it dies on a raw `asyncpg` traceback |
| S1-002 | S1 | ops / observability | Service boots and `/health` returns 200 while no user can obtain a session |
| S1-003 | S1 | backend / ops | `/ready` returns HTTP 500 unconditionally — `NameError: time` |
| S1-004 | S1 | backend / security | `/debug/timings` 500s when disabled, confirming it exists — the opposite of its stated design |
| S1-005 | S1 | security / storage | `POST /v2/documents/presign` signs an upload URL for any `application_id` the caller supplies |
| S1-006 | S1 | CI | No Python linter anywhere in CI; both crash bugs are one `ruff` invocation away |
| S2-001 | S2 | config | `VOICE_REALTIME_ENABLED` is inert; the live variable is `REALTIME_ENABLED`, and an error message tells you to set the dead one |
| S2-002 | S2 | docs | `backend/README.md` documents an architecture that no longer exists (5 instances) |
| S2-003 | S2 | config | 55 settings referenced in code are absent from `.env.example`; 2 documented ones bind to nothing |
| S2-004 | S2 | backend / dev-ex | `ssl: "require"` is hardcoded — the backend cannot run against any non-TLS Postgres |
| S2-006 | S2 | eval / CI | Nightly retrieval gate scores a retriever no request touches; its 3 misses are false alarms |
| S2-005 | S2 | API contract | `POST /v2/chat/stream` returns HTTP 200 for an unauthenticated request, with the error inside the body |
| S3-001 | S3 | hygiene | 4 unused imports and 1 placeholder-free f-string (`ruff F401/F541`) |

---

## Full findings

### [S1-001] Following the README verbatim cannot start the service

**Area:** docs / cold start
**Severity:** S1
**Confidence:** Confirmed (fresh clone, 1/1 reproduction)

**Repro:**
1. `git clone` to an empty directory. Note there is **no root `README.md`**.
2. `cd backend && cp .env.example .env`
3. Set only `OPENAI_API_KEY`, which the README calls the one required value.
4. Boot the app.

**Expected:** The service starts, or refuses with a message naming what is missing.
**Actual:** Boot dies with a raw driver traceback:

```
File ".../asyncpg/connect_utils.py", line 1102, in __connect_addr
    await connected
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user 'user'
```

`.env.example` ships a placeholder `DATABASE_URL` pointing at
`ep-example-123456-pooler.us-east-2.aws.neon.tech` and an **empty**
`SESSION_SECRET`. The README's "Minimum config" section says *"Only one value is
truly required in .env: `OPENAI_API_KEY`"* and *"Everything else has a working
default."* Both are false since the corpus moved into Postgres (P13-002).

The README mentions `alembic`, `DATABASE_URL`, `SESSION_SECRET`, Postgres,
pgvector and Valkey **zero times each**.

**Evidence:** `evidence/S1-001-cold-start.log`
**Suspected cause:** `app/db/engine.py:warm()` runs before
`app/main.py:_require_corpus()`. `_require_corpus` has a written, actionable
message naming `alembic upgrade head` — it is never reached, because `warm()`
raises first.
**Blast radius:** Every new engineer, every CI bootstrap, every handover to the
ministry's own team. This is the first thing a client does.

---

### [S1-002] Service boots and reports healthy while no user can get a session

**Area:** ops / observability
**Severity:** S1 (brief: "silent degradation is an S1")
**Confidence:** Confirmed (2/2 reproductions)

**Repro:**
1. Start the app with `SESSION_SECRET=""` — the value `.env.example` ships.
2. `GET /health`
3. `POST /api/auth/anonymous` — what a first-time visitor's browser does.

**Expected:** Refusal at boot. `app/config.py` states the intent explicitly:
*"the failure mode of forgetting to set it must be a refusal at boot rather than
forged sessions in production."*
**Actual:** Boots cleanly. `/health` → `200 {"status":"ok","database":true,...}`.
Session creation → `RuntimeError: SESSION_SECRET is not set.`

**Good news, stated plainly:** `_secret()` refuses correctly and `mint_token`
fails, so **no token can be forged**. This is not a security hole. It is a
liveness hole: the service passes its own health check while being 100% unusable,
so it enters a load-balancer rotation and stays there.

The endpoint that would have caught this is `/ready` — which is itself broken
(S1-003). The two findings compound: there is currently *no* signal that
distinguishes a working deployment from a dead one.

**Evidence:** `evidence/S1-002-boots-unusable.log`
**Repro script:** `repro/S1-002-boots-unusable.sh`
**Blast radius:** Any deploy with a missing or rotated-out signing key. Silent.

---

### [S1-003] `/ready` returns HTTP 500 unconditionally, in every deployment

**Area:** backend / ops
**Severity:** S1
**Confidence:** Confirmed (3/3 reproductions, healthy config)

**Repro:**
1. Boot with a working DB, working cache and a valid `SESSION_SECRET`.
2. `GET /ready`

**Expected:** `200 {"ready":true,...}` (or an honest 503).
**Actual:** `HTTP 500 Internal Server Error`. Underlying: `NameError: name 'time'
is not defined`.

`app/main.py` has no `import time`; line 362 calls `time.monotonic()` inside
`_provider_ready()`, which `/ready` calls on every request.

**Evidence:** `evidence/S1-003-ready-500.log`
**Repro script:** `repro/S1-003.sh` (4 lines)
**Suspected cause:** `app/main.py:362` — `import time` was lost when the chat
endpoints were removed from this module during the P15 refactor; the reference
survived.
**Blast radius:** The endpoint exists precisely so ops can distinguish "process is
up" from "able to answer". Nothing references it today (`deploy/`, `.github/`,
`frontend/src` — no hits) and **no test covers it**, which is why it has gone
unnoticed. The moment it is wired to a load balancer — its only purpose — every
instance fails its readiness gate and no deploy completes.

---

### [S1-004] `/debug/timings` 500s when disabled, confirming the route exists

**Area:** backend / security
**Severity:** S1
**Confidence:** Confirmed (3/3)

**Repro:**
1. Boot with `TIMINGS_ENDPOINT_ENABLED` unset (the default — disabled).
2. `GET /debug/timings` → **500**
3. `GET /debug/nonexistent-xyz` → **404**

**Expected:** Both 404, indistinguishable. The docstring is explicit: *"404 rather
than 403 when it is off: a disabled debug route should not confirm that it
exists."*
**Actual:** 500 vs 404. An unauthenticated prober learns the route exists from the
status code alone — the bug **inverts** the property the design was careful about.

**Evidence:** `evidence/S1-004-debug-timings-500.log`
**Suspected cause:** `app/main.py:296` — `HTTPException` is not imported into
this module (`ruff F821`). The `raise` becomes a `NameError`.
**Blast radius:** Reconnaissance only; the endpoint still refuses to serve data.
Rated S1 rather than S2 because it is a security control that fails open in the
one dimension it was built to close, and because the fix is one import.

---

### [S1-005] `POST /v2/documents/presign` signs uploads for any `application_id`

**Area:** security / storage
**Severity:** S1
**Confidence:** Confirmed (HTTP 200, end to end)

**Repro:**
1. `POST /v2/session` with no `Authorization` header → 200, returns a token.
   Anyone may mint one; the endpoint uses `optional_principal`.
2. `POST /v2/documents/presign` with that token and a body naming an
   `application_id` the caller does not own.

**Expected:** 403, or the id taken from the caller's own claims.
**Actual:** `200`, and the signed URL is scoped to the supplied id:

```
[1] POST /v2/session               -> 200
[2] POST /v2/documents/presign     -> 200
    document_id: d0b51b14986d405ab387eaa7cdc0ef35
    signed key : applications/11111111-1111-1111-1111-111111111111/national_id/d0b51b14...
```

`app/api/stream.py:561` reads `application_id` straight from the request body;
`presign_upload()` (`app/storage/presign.py:119`) performs no ownership check,
and **no `owns_application()` helper exists anywhere in the codebase**.

The same API does this correctly one file over — `app/api/stream.py:144`:
`if not await turn_service.owns_thread(thread_id, owner_id)`. And
`POST /v2/session`'s own docstring argues at length that claims must never come
from the request. This endpoint is the exception.

**Evidence:** `evidence/S1-005-presign.log`
**Repro script:** `repro/S1-005-presign-foreign-application.sh`
**Blast radius, stated honestly:** This is an unauthorized **write**, not a read.
An attacker cannot retrieve a victim's documents — storage keys end in a
server-generated UUID, as `storage_key_for()`'s comment says. What they can do is
place arbitrary (MIME- and size-checked) objects inside another applicant's
`applications/<id>/<slot>/` prefix, including `national_id`. That matters because
the prefix is the unit of retention (*"a single application's documents can be
removed together"*) and because any future admin tooling that lists by prefix
would show planted files against a victim's application. On a benefits programme
handling minors' identity documents, an unauthenticated stranger being able to
write into a named applicant's national-ID slot is not acceptable regardless of
whether a read path exists today. **Rated S1 rather than S0** only because no
read path was proven.

---

### [S1-006] No Python linter in CI

**Area:** CI
**Severity:** S1 (as the root cause of S1-003 and S1-004)
**Confidence:** Confirmed

**Repro:** `grep -nE "run:.*(ruff|mypy|pyright)" .github/workflows/deploy.yml` → no matches.

**Expected:** The backend gate matches the frontend's, which runs `biome check`
(lint + format + import order) and is green.
**Actual:** The backend gate is `pytest` only, split fast/slow. 517 tests pass
with two `NameError`s live in `app/main.py`.

```
$ uvx ruff check app/ --select F,E9 --output-format concise
app\main.py:296:15: F821 Undefined name `HTTPException`
app\main.py:362:11: F821 Undefined name `time`
... 5 more
Found 7 errors.
```

**Evidence:** `evidence/S1-004-debug-timings-500.log`
**Blast radius:** Both production crash bugs in this report are single-token
typos that this catches in under a second. Tests cannot substitute: neither line
is imported by any test.

---

### [S2-001] `VOICE_REALTIME_ENABLED` is inert, and an error message recommends it

**Area:** config
**Severity:** S2
**Confidence:** Confirmed (2/2)

**Repro:**
```
$ VOICE_REALTIME_ENABLED=true python -c "...get_voice_settings().realtime_enabled"
-> False
$ REALTIME_ENABLED=true       python -c "...get_voice_settings().realtime_enabled"
-> True
```

`VoiceSettings` declares no `env_prefix`, so the field `realtime_enabled` binds to
`REALTIME_ENABLED`. `.env.example` documents `VOICE_REALTIME_ENABLED`, and
`app/voice/router.py:396` returns *"Realtime voice is not enabled. Set
VOICE_REALTIME_ENABLED=true."* — instructing the operator to set the dead one.

**Evidence:** `evidence/S2-001-realtime-env-var.log`
**Blast radius:** An operator enabling realtime voice follows the error message,
sets the documented variable, observes no change, and has no way to discover why.

---

### [S2-002] `backend/README.md` documents an architecture that no longer exists

**Area:** docs
**Severity:** S2
**Confidence:** Confirmed (5/5 instances verified against code)

1. *"agentic RAG over a CSV knowledge base"* — the corpus is in Postgres.
2. *"Only one value is truly required… `OPENAI_API_KEY`"* — see S1-001.
3. Zero mentions of alembic; 15 migrations exist and nothing runs them for you.
4. *"Delete `data/chroma` and re-ingest"* as the fix for a dimension change —
   Chroma is gone; the real remediation is a column-width migration, which is what
   the actual guard says (`app/ingest.py:229`).
5. *"Memory is in-process. `InMemorySaver`…"* — `app/graph/checkpointer.py:285`
   uses `AsyncPostgresSaver`; conversations survive restart.

Dead weight from the same root cause: `chroma_dir` / `chroma_collection` remain
in `app/config.py`, and `langchain-chroma==1.1.0` is still a pinned dependency.

**Evidence:** `evidence/S2-002-readme-stale.log`

---

### [S2-003] 55 settings undocumented; 2 documented settings bind to nothing

**Area:** config
**Severity:** S2
**Confidence:** Confirmed

119 settings referenced in code vs 66 entries in `.env.example`.

**In code, absent from `.env.example` (55)** — including `RESEND_API_KEY`,
`PUBLIC_WEB_URL`, `MAIL_CONSOLE_LOGS_LINKS`, `BREAKER_FAILURE_THRESHOLD`,
`CHAT_MESSAGES_PER_WINDOW`, `CHAT_RATE_WINDOW_SECONDS`, `QA_RETRIEVE_K`,
`QA_RELEVANCE_FLOOR`, `SEMANTIC_CACHE_*`, `WIDGET_*`, and 11 `VOICE_<persona>_<lang>` ids.

Several are security- or cost-relevant: an operator cannot discover the rate-limit
window or the circuit-breaker thresholds from the documented configuration.

**In `.env.example`, binding to nothing (2):** `SESSION_TTL_DAYS`,
`VOICE_REALTIME_ENABLED` (S2-001).

**Evidence:** `INVENTORY.md` §7

---

### [S2-004] `ssl: "require"` is hardcoded; the backend cannot use a non-TLS Postgres

**Area:** backend / dev-ex
**Severity:** S2
**Confidence:** Confirmed

`app/db/engine.py:101` sets `connect_args={"ssl": "require"}` unconditionally.
Against a stock local Postgres:

```
ConnectionError: PostgreSQL server at "127.0.0.1:55433" rejected SSL upgrade
```

**This was a blocker for this hunt.** Per the rules of engagement I worked around
it *without touching product code* — by generating a self-signed cert and enabling
TLS inside the scratch container — rather than patching the app.

**Blast radius:** No local Postgres, no CI service container, no offline
development. Combined with S1-001 and S2-002 (which never mention a database at
all), the practical requirement to run this project is a Neon account.

---

### [S2-006] The nightly retrieval gate scores a retriever no request touches

**Area:** eval / CI
**Severity:** S2
**Confidence:** Confirmed — and it began as a suspected S1 that measurement refuted

**This finding is mostly a retraction, and the retraction is the important half.**

I first read the eval's three misses as a cross-lingual retrieval failure on the
eligibility cut-off row. Measured end to end, that is **false** — see
"Verified sound". What survives is narrower: the gate measures the wrong component.

`.github/workflows/evals.yml:62` gates nightly on:

```
uv run python -m evals.run --retrieval --fail-under 0.95
```

`--retrieval` scores `build_retriever` — vector-only, with an absolute similarity
floor of 0.434315. The product does not use it. `app/agents/qa/nodes.py` runs
`rewrite_query → hybrid_retrieve → rerank → generate → ground_check`, RRF-fusing a
vector and a lexical retriever.

Measured through `build_retriever`, same question, same target row ASP-031:

| lang | similarity to ASP-031 | vs 0.434315 floor | eval result |
|---|---|---|---|
| en | 0.7026 | PASS | hit |
| es | 0.3837 | cut | **got []** |
| fr | 0.4011 | cut | **got []** |

ASP-031 ranks *first* in all three languages — ranking is fine cross-lingually.
Cross-lingual pairs simply score in a lower absolute band (~0.38–0.40) than
same-language pairs (~0.70), and the floor sits between them.

Measured through the real transport with a cold cache, the same two questions are
answered correctly (see Verified sound). So:

- its 3 reported misses are **false alarms**;
- its `0.95` is not a measure of product retrieval quality;
- a real regression in `hybrid_retrieve` / `rerank` / `ground_check` would be
  **invisible** to it;
- and it is brittle — `hit_rate` is `0.95` against `--fail-under 0.95`, exactly on
  the line, so one more cross-lingual case scored this way turns the nightly red
  for a reason no user would ever experience.

**Evidence:** `evidence/S2-006-eval-measures-wrong-retriever.log`
**Repro script:** `repro/S1-007-crosslingual-eligibility.sh` (floor asymmetry),
`repro/S1-007b-what-the-bot-says.sh` (end-to-end refutation)
**Blast radius:** False assurance on the one automated quality signal this product
has for retrieval. Also a coverage note: 60 expectation-bearing cases cover
**20 distinct rows of 706** (2.8% of the corpus).

---

### [S2-005] `POST /v2/chat/stream` returns 200 for an unauthenticated request

**Area:** API contract
**Severity:** S2
**Confidence:** Confirmed (3/3)

```
empty body   /v2/chat/stream -> 200  'event: error\ndata: {"code":"unauthenticated",...'
wrong type   /v2/chat/stream -> 200  (same)
null message /v2/chat/stream -> 200  (same)
```

The brief's rule: *"A 200 with `{"error": ...}` inside is a finding."*

`chat_stream_v2` (`app/api/stream.py:474`) parses the bearer token and then
returns `StreamingResponse` unconditionally; the auth failure surfaces inside
`_events()` after the 200 has been committed. Because the check happens *before*
any stream content, a 401 is achievable here — SSE does not force this.

Mitigating: the payload is well-formed, carries a machine-readable `code`, and
leaks nothing. So this is a contract/observability defect (every monitoring
system will read these as successes), not a functional break.

---

### [S3-001] Unused imports and a placeholder-free f-string

**Area:** hygiene
**Severity:** S3
**Confidence:** Confirmed

```
app\agents\escalate\graph.py:45     F401 `directive_payload` imported but unused
app\agents\learn\nodes\explain_back.py:40  F401 `CheckQuestion` imported but unused
app\agents\qa\graph.py:37           F401 `END` imported but unused
app\games\engine.py:42              F401 `Reveal` imported but unused
app\prompts.py:51                   F541 f-string without any placeholders
```

All five auto-fixable. Listed because they arrive with S1-006 and disappear with it.

---

## Verified sound — attacked and held

Recorded so a later pass does not re-litigate, and so the verdict is not read as
"everything is broken".

| Area | What was attacked | Result |
|---|---|---|
| Embedding dimensions | Set the documented offline path `EMBEDDINGS_PROVIDER=fastembed` (384-dim) against a `vector(3072)` column | **Refused loudly**, naming both numbers and the remedy (`app/ingest.py:227`). No silent truncation. |
| Empty corpus | Truncated `documents`, pointed ingest at a header-only CSV | **Refused at boot** with the filename: *"contained no usable rows."* |
| Valkey down | Booted with the cache pointed at a dead port | Booted and served — correct; the cache is explicitly best-effort |
| Error surfaces | Empty / wrong-type / null bodies, unauthenticated reads, malformed ids | No `Traceback`, `site-packages`, `asyncpg`, `SELECT`, filesystem path, `sk-`, or connection string in any response body |
| Committed secrets | Repo-wide scan for `sk-…`, `AKIA…`, private keys, connection strings; `.env` tracking | Clean. `.env` correctly untracked |
| Frontend types | `tsc --noEmit` | Clean |
| **Cross-lingual answering (EN/ES/FR)** | Same eligibility question asked through `POST /v2/chat/stream` in all 3 languages, cold cache, unique namespace | **Correct in all three.** `agent=qa_agent_public`, `cached=None`. ES and FR both state "18 años o menos" / "18 ans ou moins" on 13 Dec 2023, matching ASP-031 |
| **Corpus integrity** | 706 rows vs 706 CSV rows, duplicates, empties, orphans, null embeddings, dims | Exact match. 0 duplicates, 0 empties, 0 nulls, all 3072-dim |
| **Retrieval latency** | `EXPLAIN ANALYZE` + 15 runs at 706 rows | Seq scan, 4.6ms in-DB, p50 6.89ms / p95 9.41ms. Migration 0009's no-index argument still holds at 2x the row count it was written for |
| Vector index absence | `documents` has no HNSW index | **Deliberate and documented** (migration 0009) with a sound argument. Flagged as a *suspicion* below, not a finding — the argument cites "332 rows" and the corpus is now 706 |

---

## Suspicions — unconfirmed

Things that smell wrong and that I could **not** reproduce or measure. No claim is
made about any of these.

1. **`_record_document` trusts a client-supplied `storage_key`.**
   `app/agents/register/graph.py:679` uses `payload.get("storage_key")` when
   present, falling back to a derived key. The DB row's `application_id` is
   server-side (correct), so I could not construct an exploit — a victim's key
   ends in a UUID the attacker cannot guess. Combined with S1-005 this deserves a
   second look by someone who knows the upload client.

2. **Persona/age-band caching.** `cache_key()` gained `age_band` because *"a cache
   hit never reaches the gate"* — an explicit acknowledgement that bypassing
   `safety_out` is a live bug class. I did not test whether any *other* path
   reaches a user without passing `safety_out` (the streaming interceptor is the
   obvious candidate). Untested, not cleared.

3. **`aurora`/`nova` unrestricted by age band.** `app/graph/access.py`'s own
   docstring flags this as a known open question and reasons that the permissive
   rows are unreachable because a guardian token carries `adult`. I did not attempt
   to mint a token that reaches them.

---

## Coverage gaps — what I did **not** test

Declared honestly. An unknown gap is worse than a known one.

**Not started at all:**

- **Phase 5 — KB & retrieval integrity.** No retrieval hit-rate scoring, no
  30-question set, no unanswerable-10, no cross-lingual EN/ES/FR check, **no
  numeric-precision testing on interest rates, age eligibility or deposit
  minimums.** The brief rates a hallucinated number S0. *This is the single
  largest gap and the one I would close first.*
- **Phase 6 — Conversational behaviour.** No persona fidelity runs, no persona
  bleed, no language switching, no memory-at-turn-20, no account-status routing,
  no gamification, and **no safety testing** (injection, PII solicitation,
  investment guarantees) in any language.
- **Phase 7 — Frontend E2E.** No journeys, no compositor→dock transition runs, no
  streaming-parser tests, no error-state screenshots, no keyboard/focus checks.
- **Phase 8 — Auth & session.** No forged/expired/mutated tokens, no IDOR
  enumeration of conversation ids, no anonymous→identified upgrade.
- **Phase 9 — Concurrency & load.** No 20-stream run, no pool/leak measurement, no
  p50/p95, no Valkey/Postgres kill-under-load.

**Partially done:**

- **Phase 4 — API assault.** Only malformed-body and error-leak probes on a few
  endpoints. No oversized inputs (50k chars, 10MB, 500-message history), no
  Unicode/RTL/ZWJ/template-injection corpus, no concurrent-replay idempotency.
- **Phase 10 — Security.** Secret scanning and error-leak probing done. **Not**
  done: log inspection for PII/device-ids in plaintext, CORS/rate-limit/request-size
  *enforcement* testing, `npm audit`/`pip-audit`, KB-borne prompt-injection canary.

**Why:** Phases 5 and 6 require real model calls across 3 languages × 4 personas ×
~80 prompts. I stopped rather than spend that budget without checking with you
first, and rather than produce a shallow version of the tests that matter most on
a children's financial product. Everything above is reachable with the scratch
environment already standing.

**Environment caveat:** the frontend E2E work would use **puppeteer**, not
Playwright — the repo standardises on it (`frontend/.impeccable/*.mjs`, ~60
harnesses) and has no Playwright dependency. Adding one to a repo with a
no-new-dependencies rule seemed the wrong call for a QA pass; flagging the
deviation rather than making it silently.

---

## Recommended fix order

Sequenced by risk and dependency. Effort is one engineer.

| # | Fix | Why first | Effort |
|---|---|---|---|
| 1 | **S1-006** — add `ruff check --select F,E9` to the CI verify job | Prevents recurrence of 3 and 4, and is the reason they exist. Do this before fixing them, so the fixes are proven by the gate. | 15 min |
| 2 | **S1-003** — `import time` in `app/main.py` | One line. Unblocks any readiness wiring. | 2 min |
| 3 | **S1-004** — import `HTTPException` in `app/main.py` | One line. Closes the existence leak. | 2 min |
| 4 | **S1-005** — verify application ownership in `presign` | Security. Mirror `owns_thread`; add `owns_application()`. Needs a decision on what "owns" means for an anonymous draft. | 2–4 h |
| 5 | **S1-002** — validate `SESSION_SECRET` at boot, not first use | Call `_secret()` in the lifespan. Makes the promise in `config.py` true. Depends on 2/3 so `/ready` can report it. | 30 min |
| 6 | **S1-001 + S2-002 + S2-003** — one documentation pass | Rewrite the README's setup and swapping-models sections; add the 55 missing vars to `.env.example`; delete the 2 stale ones. Best done as one commit by whoever did P13. | 3–4 h |
| 7 | **S2-001** — rename to `REALTIME_ENABLED` in docs + error message, or add `env_prefix` | Trivial, but decide which way — `env_prefix="VOICE_"` would rename *every* voice setting. | 30 min |
| 8 | **S2-004** — make SSL conditional on the host | Unblocks local/CI Postgres. `ssl="require"` unless host is loopback. | 1 h |
| 9 | **S2-005** — return 401 before opening the stream | Contract honesty; check the frontend handles a non-200 from the stream endpoint first. | 1–2 h |
| 10 | **S3-001** — `ruff check --fix` | Falls out of step 1. | 5 min |
| — | **Then re-run this hunt from Phase 5.** | The untested half is where a government-facing product is most exposed. | — |

---

## Approximate spend

**~$0.10.** One unintended ingest of 706 chunks through
`text-embedding-3-large` (~140k tokens ≈ $0.018) when auto-ingest fired during
the Phase 1 failure matrix — the subprocess inherited `OPENAI_API_KEY` from
`backend/.env`. No chat completions were made; no ElevenLabs calls were made.
Flagged rather than buried: it also **invalidated my first empty-KB test**, which
I re-ran correctly with a header-only corpus file.
