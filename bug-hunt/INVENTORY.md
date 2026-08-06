# INVENTORY — Phase 0 recon

ASPIRE AI, branch `bug-hunt/2026-08-05`, cut from `feat/aspire-langgraph-platform`
at `e5c4466`.

Read fresh. Where this contradicts the brief, the brief is stale — noted inline.

---

## 1. Shape of the repo

```
backend/     FastAPI + LangGraph. 128 .py files under app/.
frontend/    React 19 + TanStack Start/Router/Query. SSR.
deploy/      nginx conf, systemd units, pm2 ecosystem, update.sh
reports/     audit history: findings.md (closed at P12), P13/P14/P15 reports
docs/        latency-baseline.md — one file
.github/     deploy.yml (verify → deploy), evals.yml
```

**No root `README.md`.** Setup docs are `backend/README.md` and
`frontend/README.md` only. Phase 1's "follow the README literally" therefore has
no single entry point — logged as a finding candidate.

### Brief vs reality

| Brief says | Actually |
|---|---|
| "~338 verified rows" in the KB | `backend/data/knowledge_base.csv` is **706 lines** |
| "backend (FastAPI + LangChain)" | LangChain *and* **LangGraph** — the graph is now the only chat path |
| Chat at `/api/chat` | **`POST /v2/chat/stream`**; the old `/chat` and `/chat/stream` are deleted, not deprecated |
| Playwright for E2E | Repo has **puppeteer** (`frontend/.impeccable/*.mjs`), no Playwright |

---

## 2. The graph — this is the product now

`app/graph/main_graph.py`. Every turn walks:

```
START → hydrate → guard ─┬→ safety_in ─┬→ cards ─┬→ classify ─→ <agent> ─┐
                         │             │         │                       │
                         └─────────────┴─────────┴──────→ safety_out ←────┘
                                                              ↓
                                                           persist → END
```

Every path reaches `safety_out`. Guard, safety_in and cards can each short-circuit
straight to it. That is the structural claim to attack in Phase 6: **is there any
route to a user-visible token that does not pass `safety_out`?** Streaming makes
that a real question, because tokens leave the process before the node finishes —
see `app/graph/stream_interceptor.py`.

### 10 agents (`AGENT_NAMES`)

`learn_agent`, `learning_preview`, `learning_sample`, `qa_agent`,
`qa_agent_limited`, `qa_agent_public`, `register_agent`, `register_agent_step1`,
`servicing_agent`, `escalate_agent`.

### Access matrix (`app/graph/access.py`)

Pure function over (persona × age_band × account_status × authenticated).
4 × 5 × 4 × 2 = 160 combinations, claimed exhaustively tested. Empty list = hard 403.

Its own docstring flags a **known open question**: `aurora` and `nova` are
unrestricted by age band because the spec's table says so, and the author notes
the permissive rows *should* be unreachable because a guardian token carries
`adult`. "Should be unreachable" is exactly the kind of claim worth attacking —
Phase 8, via a minted token.

---

## 3. Personas, bands, languages

| Axis | Values | Defined in |
|---|---|---|
| Persona | `stella`, `orion`, `aurora`, `nova` | `app/games/models.py:25` **and** `app/voice/registry.py:19` — deliberately duplicated |
| Age band | `5-8`, `9-12`, `13-15`, `16-18`, `adult` | `app/graph/state.py:58` |
| Language | `en`, `es`, `fr` | `games/models.py`, `voice/registry.py` |

**Enforcement is in three layers, not one:**

1. **Token/claims** — `app/graph/account.py:claims_for()` derives persona and band
   from the account, never the request. A client may only *narrow* persona
   (`_narrowing`), never widen.
2. **Access matrix** — `app/graph/access.py` decides which agents the classifier
   may even choose from.
3. **Output gate** — `safety_out` caps answer length *by band* (35 words at 5-8,
   70 at 9-12, 180 at 16-18 per `cache.py`'s note).

Layer 3 is the one with a documented hole in its neighbour: `cache_key()` had to
add `age_band` because *"a cache hit never reaches the gate"*. That comment is a
map to the bug class — anything else that bypasses `safety_out` has the same
problem. Phase 5/6.

Note `PLAYING_PERSONAS = {stella, orion}` — games are gated to child personas.

---

## 4. HTTP surface — 48 routes

| Prefix | Count | Notes |
|---|---|---|
| `/v2` (graph) | 4 | `chat/stream`, `widget/interaction`, `documents/presign`, `session` |
| `/admin` | 8 | applications list/detail, document URL, transition, widgets, auth |
| `/api/auth` | 11 | register, login, logout, refresh, forgot, reset, signin-link(+redeem), verify, anonymous, session |
| `/api/conversations` | 4 | list, detail, rename, claim |
| `/api/games` | 7 | list, state, start, submit, hint, skip, quit |
| `/api/eligibility` | 6 | state, start, answer, back, restart, quit |
| `/api/voice` | 5 | config, transcribe, speak, speak-stream, realtime-token |
| root | 4 | `/health`, `/ready`, `/debug/timings`, `/api/title` |

`/debug/timings` is gated on `TIMINGS_ENDPOINT_ENABLED` — check it is off by
default and that it leaks nothing (Phase 10).

### Leads already open from recon

- **`POST /v2/documents/presign`** takes `application_id` from the **request
  body** and passes it to `presign_upload()`, which does no ownership check
  (`app/storage/presign.py:119`). Meanwhile `POST /v2/session`'s own docstring
  argues at length that claims must never come from the request. Confirm in
  Phase 4/10.
- **`_record_document`** (`app/agents/register/graph.py:666`) takes
  `payload.get("storage_key")` from the client, falling back to a derived key.
  The DB row's `application_id` is server-side (good), but the storage key is
  not. Confirm in Phase 10.

---

## 5. Background jobs

One, `arq`: `app/jobs.py` → `WorkerSettings`, cron-only.
`retention_job` at 03:15 daily, `run_at_startup=False`. Enforces the 180-day
anonymous-deletion promise in `PRIVACY.md`.

---

## 6. External dependencies

| Service | Where | Failure mode to test |
|---|---|---|
| Postgres + pgvector (Neon) | corpus **and** checkpointer **and** app data | KB now lives in PG (P13-002) — `_require_corpus` makes an empty corpus fatal at boot |
| Valkey | response cache, embedding cache, rate limits, arq queue | shared instance (P7-002, still open) |
| OpenAI / Anthropic | `chat_model` is a `provider:model` string | `/ready` probes reachability |
| ElevenLabs | voice; off unless `VOICE_ENABLED` | stub for non-voice tests |
| Resend | transactional mail; console provider is the fallback | `MAIL_CONSOLE_LOGS_LINKS` (P9-003) |
| S3-compatible storage | `app/storage/presign.py` | 503s when unconfigured, by design |

---

## 7. Environment variables — 55 undocumented, 2 stale

Settings classes are `Settings` (`app/config.py`, 60 fields) and `VoiceSettings`
(`app/voice/config.py`). **Neither declares `env_prefix`**, so every field binds
to its own uppercased name.

- **119** settings referenced in code
- **66** entries in `.env.example`
- **55 in code, absent from `.env.example`** — including `RESEND_API_KEY`,
  `PUBLIC_WEB_URL`, `MAIL_CONSOLE_LOGS_LINKS`, `BREAKER_*`, `CHAT_*_WINDOW`,
  `QA_*` retrieval tuning, `SEMANTIC_CACHE_*`, `WIDGET*`, and 11 `VOICE_<persona>_<lang>` ids
- **2 in `.env.example` that bind to nothing**: `SESSION_TTL_DAYS`,
  `VOICE_REALTIME_ENABLED`

`VOICE_REALTIME_ENABLED` is **confirmed inert** — the field is `realtime_enabled`
with no prefix, so the live variable is `REALTIME_ENABLED`. `app/voice/router.py:396`
returns an error telling the operator to set the dead one.
Evidence: `evidence/S2-001-realtime-env-var.log`.

---

## 8. Migrations — 15

`0001_documents` … `0015_staff`. Note the shape of the history:
`0008_drop_documents` removed the pgvector table, then `0009_documents_live`
brought it back when the corpus moved off Chroma into Postgres. Phase 1 must
verify the **vector extension and HNSW indexes actually exist after
`alembic upgrade head`**, not merely that the migration ran.

Recent additions: `0010_tickets`, `0011_curriculum`, `0012_mastery`,
`0013_concept_widgets`, `0014_applications`, `0015_staff`.

---

## 9. Scaffolding smells

Genuinely low. This is a well-tended codebase.

- **1** `TODO` in all 128 files (`app/graph/state.py:212`, a typed-dict
  refactor note).
- **0** `FIXME` / `XXX` / `HACK`.
- **2** `except Exception: pass` — both in `app/cache.py` (405, 471), both in
  accounting paths where the comment says accounting must never affect the
  request. Legitimate on inspection; re-check in Phase 2 that they are not
  swallowing anything else.

The risk here is not abandoned scaffolding. It is that the code is **confident
and heavily commented**, which makes a wrong comment more dangerous than no
comment. Several findings below are expected to be "the comment says X, the code
does Y".

---

## 10. Test + harness assets already present

- `backend/tests/` — 517 tests, split `-m slow` / `not slow` (P0-010)
- `backend/evals/` — `golden.yaml` + `run.py`, retrieval and answer scoring
- `frontend/.impeccable/*.mjs` — ~60 puppeteer harnesses, review-only
- `frontend/src/lib/aspire/knowledge.regression.test.ts` — node:test

These are assets, not evidence. A hostile pass must assume they encode the
authors' assumptions and test *around* them.

---

## 11. Test environment

See `evidence/DB-TARGET-CONFIRMATION.md`. Summary: all writes go to a disposable
`pgvector/pgvector:pg16` container on `127.0.0.1:55433/aspire_bughunt`. The
Neon endpoint in `backend/.env` was read once to identify it and is otherwise
untouched.
