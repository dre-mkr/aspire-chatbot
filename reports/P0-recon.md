# P0 — Recon and baseline

Read-only pass. No source file was modified. Everything below was read from the
code; nothing is inferred from a filename or a README.

---

## 0. Corrections to the assumed architecture

The prompt pack's assumptions do not match the repository. These matter because
several later passes are written against the wrong system.

| Assumed | Actual | Evidence |
|---|---|---|
| `apps/web` + `apps/api` | `frontend/` + `backend/` | repo root |
| Retrieval on **Postgres + pgvector (Neon), HNSW** | Retrieval on **Chroma**, on local disk at `backend/data/chroma/` | `backend/app/rag.py:13,69-85`. `pgvector` is a declared dependency but **no code imports it for retrieval**. Postgres holds conversations/users/outcomes only. |
| **BGE-M3** embeddings | **OpenAI `text-embedding-3-large`** (3072-dim) | `backend/.env` → `EMBEDDINGS_PROVIDER=openai`, `EMBEDDINGS_MODEL=text-embedding-3-large`. A local `fastembed` path exists (`rag.py:22-50`) but is not the configured one. |
| Streaming chat surface | **Not streaming.** Whole-response `/chat` + client-side typewriter | `use-conversation.ts:597`; `stream.ts`/`settled.ts` have zero importers. See P0-001. |
| Virtualized message list | **No virtualization.** `@tanstack/react-virtual` was removed in `06074cb` as unused | `Transcript.tsx`; commit message: "nothing ever imported" |

**Consequence for the plan.** P7's pgvector/HNSW section (EXPLAIN ANALYZE,
`hnsw.ef_search` recall curve, opclass/operator match) is **not applicable as
written** — there is no vector index in Postgres to tune. The equivalent work is
a Chroma retrieval-quality audit, which belongs in P8. P5's virtualization
section audits something that does not exist; the honest version is "measure,
then decide whether it is needed".

---

## 1. Architecture map

```
frontend/  TanStack Start 1.168 · Router 1.170 · Query 5.101 · React 19.2 · Vite 8.2 · Tailwind 4.3
  src/routes/        __root · _shell (pathless layout) · _shell/index · _shell/chat.$chatId
                     signin · signup · verify · reset
  src/components/    chat/ (AspireChat, Transcript, Composer, Rail, Voice, WordScramble,
                     TrueFalse, EligibilityCheck, ChatTitleBar, Crossfade, VoiceSettings)
                     auth/ (AuthSurface, AccountControl, Avatar, Field)
  src/lib/aspire/    api · stream(dead) · settled(dead) · use-conversation · queries · session
                     auth · conversations · history · knowledge · games · eligibility · voice · title
  server.mjs         production node server (srvx)

backend/   FastAPI 0.141 · LangChain 1.3 · LangGraph 1.2 · Python 3.13 · uv
  app/main.py        /health · /chat · /chat/stream (unused by the app) · /api/title
  app/agent.py       create_agent + retriever tool + InMemorySaver checkpointer
  app/rag.py         Chroma vector store + embeddings switch point
  app/db/            SQLAlchemy async + asyncpg → Neon Postgres (conversations, users, outcomes)
  app/games/         word_scramble, true_false — own router, own server-side session
  app/eligibility/   rules engine — own router, deliberately never routed through the prompt
  app/voice/         ElevenLabs STT/TTS, own rate limiter, on-disk cache
  app/cache.py       Valkey response cache (first-turn answers only)
  app/jobs.py        arq queue — conversation summarisation, off the request path
  alembic/versions/  7 migrations, 20260801_0001 → 20260803_0007

deploy/    nginx (single origin, app :3000 + API :8000) · systemd × 2 · pm2 ecosystem · update.sh
```

**Deployment shape.** `deploy/nginx-aspire.conf` puts the app and the API behind
one origin (`aspire.eccugenai.app`), so the browser never preflights.
`deploy/aspire-api.service` runs uvicorn with `--workers 1`, and the unit file
documents this as **required, not tunable**: conversation memory is an in-process
`InMemorySaver` and the voice rate limiter is a process-local dict, so a second
worker would split both. That is the system's hard scaling ceiling (P0-003).

---

## 2. Dependency inventory (installed, from lockfiles and `node_modules`)

Latest-version comparison and CVE scan are **P2 work** and are deliberately not
guessed here.

| Package | Installed | Specifier |
|---|---|---|
| `@tanstack/react-start` | 1.168.34 | `latest` ⚠ |
| `@tanstack/react-router` | 1.170.18 | `latest` ⚠ |
| `@tanstack/react-query` | 5.101.4 | `latest` ⚠ |
| `@tanstack/ai-client` | 0.22.1 | `^0.22.1` (dead code — see P0-001) |
| `@tanstack/react-store` | 0.11.0 | `^0.11.0` |
| `react` / `react-dom` | 19.2.8 | `^19.2.0` |
| `vite` | 8.2.0 | `^8.2.0` |
| `typescript` | 6.0.3 | `^6.0.2` |
| `tailwindcss` | 4.3.3 | `^4.1.18` |
| `@biomejs/biome` | 2.4.5 | pinned |
| `babel-plugin-react-compiler` | 1.0.0 | `^1.0.0` — React Compiler is **on** (`vite.config.ts`) |
| Node | 26.2.0 | — |
| Python | 3.13.14 | `.python-version` says 3.12+ |

Backend versions are fully pinned with `==` in `pyproject.toml` (good). Notable:
`langchain==1.3.14`, `langgraph==1.2.10`, `fastapi==0.141.1`,
`sqlalchemy==2.0.51`, `asyncpg==0.31.0`, `redis==5.3.1`, `arq==0.28.0`,
`elevenlabs==2.60.0`, `chromadb` via `langchain-chroma==1.1.0`.

Chat model: `openai:gpt-5.6-luna` (`backend/.env`).

⚠ Eight frontend packages use the literal specifier `"latest"` — P0-006.

---

## 3. Critical path traces

### (b) User sends a message — **fully traced**

```
Composer.tsx  onSubmit
  → use-conversation.ts:745  send()
      guard: isThinkingRef || cursor.current  (blocks send-during-turn)
      mints thread id client-side (newThreadId, l.145) on first message
      upsertConversation → rail row appears optimistically, same commit
      onThreadStart → URL becomes /chat/:id
      setMessages(+user bubble); setIsThinking(true)
  → use-conversation.ts:590  ask()
  → api.ts  askAspire()          POST /chat   (NOT /chat/stream)
                                 90s internal timeout, no external abort signal
  → backend main.py:558  chat()
      chat_principal → Principal | None (anonymous allowed)
      _cached_reply()  → Valkey, first turn only (main.py:341)
      _open_conversation()  → NO-OP (P0-004)
      _prepare_messages()   → memory_window off ⇒ [HumanMessage] only
      get_agent().ainvoke() → LangGraph agent
            ├ retriever tool → Chroma → OpenAI embeddings → k=4
            └ optional: start_game / start_eligibility_check tools
      _extract_reply / _started_game / _started_eligibility
      suggest_follow_ups()  → second model call (skipped on card turns)
      _persist_turn()       → Postgres (ensure_conversation + 2× append_turn)
      enqueue_summary()     → arq, only if memory_window_enabled (it is not)
      response_cache.put_answer() → first turn only
  → back in ask(): turnToken check, then parseAnswer(result.reply)
  → beginStream()  → setInterval(tick, 40ms), 4 words/tick   ← simulated reveal
  → Transcript.tsx renders; no virtualization
```

The reveal is a **presentation effect over an already-complete answer**, by
explicit design (`use-conversation.ts:538-552`). The comment explains the
tradeoff honestly — an even cadence bought at the cost of time-to-first-word —
but the cost is not currently measured, and it is what makes the pack's ≤1.2s
first-token budget unreachable.

### (a) Cold load → SSR → hydration — **partially traced**

Entry `src/start.ts` → `src/router.tsx` → `__root.tsx` → `_shell.tsx` (pathless
layout) → `_shell/index.tsx` or `_shell/chat.$chatId.tsx`. `src/middleware.ts`
exists. Route tree is generated (`routeTree.gen.ts`, currently **modified in the
working tree** — worth confirming it matches `tsr generate` output).
Not yet read: loaders, SSR mode per route, dehydrate/rehydrate wiring. **Carries
into P3.**

### (c) Persona / language switch — **not traced.** Carries into P1/P4.
Both are sent per-request (`main.py:592-596`) and both are part of the response
cache key (`cache.get_answer(..., language=, persona=, account_status=)`), which
is the right shape. Whether they are part of the **TanStack Query** keys is
unverified and is exactly the cache-poisoning class P4 targets.

### (d) Gamification launch and score persist — **not traced.** Carries into P1.
Structure is known: the model calls `start_game`, the client then loads
authoritative state from `/games/*` rather than trusting the prose, and
`tests/games/test_no_answer_leak.py` exists — a good sign the answer-leak risk
was considered.

---

## 4. Baseline numbers

| Check | Command | Result |
|---|---|---|
| Frontend typecheck | `npx tsc --noEmit` | **exit 0, clean** |
| Frontend lint | `npx biome lint` | **3 errors** (1 fixable deps, 2 a11y) |
| Frontend format | `npx biome format` | **38 files differ** |
| Frontend tests | — | **none exist** (no test runner in `package.json`; `puppeteer` is present for the `.impeccable` design-review suite only) |
| Frontend build | `npx vite build` | **exit 0, 444ms** (client+SSR, 103 modules) |
| Backend tests | `pytest -q` | **487 passed, 520.25s** |
| Backend lint/typecheck | — | no ruff/mypy configured |

### Bundle (client, gzip — measured, not estimated)

| Asset | raw | gzip |
|---|---|---|
| `index-D_m1NPoL.js` | 257 KB | **80 KB** |
| `_shell-CAGyYKn_.js` | 115 KB | **34 KB** |
| `query-NESHdaTQ.js` | 62 KB | **19 KB** |
| `session-r0bm5HTK.js` | 33 KB | **11 KB** |
| `styles-DRB-mjzC.css` | 76 KB | **14 KB** |
| auth routes (signin/signup/verify/reset/Field/AuthSurface) | ~19 KB | ~6 KB |

**First load for the chat route: 147,556 bytes gzip JS (144 KB) + 14 KB CSS.**
Against the pack's ≤350 KB first-load and ≤200 KB/route budgets, this **passes
comfortably**. Route-level code splitting is working — the auth routes are
separate chunks.

### Not measured (requires a running app + real device)

LCP, INP, CLS, TTFB, time-to-first-token, frame time during reveal, long tasks,
scroll fps at message count. All of these are P5 work and need the stack up.

---

## 5. What I could not inspect, and what I need

1. **Baseline screenshots** (`reports/baseline-screens/`) — directory created but
   **empty**. Capturing them needs the frontend and backend running together with
   a reachable Neon DB, Valkey and OpenAI key. The repo already has puppeteer and
   an `.impeccable/` harness that appears purpose-built for this; I did not run it
   because P0 forbids changes and the harness writes output. **This is a real gap:
   without it the UI-change policy has no pixel contract to enforce.** Tell me
   whether to run the existing `.impeccable` tooling or drive puppeteer directly.
2. **Production `.env`** — I only have the local one. Three values change severity
   materially: `CORS_ALLOW_ORIGINS` (P0-008), `ANONYMOUS_SESSIONS_PER_IP_PER_HOUR`
   (local is 500, with a comment saying that is a local-only value), and
   `MEMORY_WINDOW_ENABLED` (absent locally ⇒ the unbounded path, P0-003).
3. **A reachable database and vector store** — no `EXPLAIN`, no index checks, no
   retrieval-quality measurement, no migration rebuild-from-scratch verification
   without them.
4. **Latest versions / CVEs** — needs registry access; deliberately deferred to P2
   rather than answered from memory.
5. **`routeTree.gen.ts` is modified in the working tree** along with
   `use-conversation.ts` and `vite.config.ts`. I audited the working-tree state.
   Confirm that is what you want audited, or commit/stash first.

---

## 6. Summary

Ten findings recorded: **3 × S1, 5 × S2, 2 × S3.** Six things verified sound and
recorded so later passes do not re-litigate them.

The headline is not a bug in the usual sense. **The application does not stream,
and two well-built subsystems for streaming are dead code** — the SSE transport,
the AG-UI endpoint, and the settled-block parser whose module docstring is the
most careful piece of reasoning in the repository. What ships instead is a
blocking request followed by a simulated typewriter. That is a defensible product
decision, argued in the code, but it is currently an *unmeasured* one, and it is
the direct cause of the chat surface feeling slower than it should.

The second theme is unbounded growth: an in-memory checkpointer with no eviction
on the default path, pinned to a single worker, replaying every prior turn's
retrieved documents into every prompt — and no way to cancel a turn, so abandoned
generations are paid for in full.

The codebase is unusually well-commented, and the comments are load-bearing: they
explain *why*, and several of them document invariants the tests then enforce.
That is a genuine asset. It also created the one trap worth naming — `_open_con-
versation` has a nine-line docstring describing behaviour its body does not
implement, and only reading the body catches it.
