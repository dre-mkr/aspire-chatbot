# P7 — Backend core: FastAPI, data layer, cache

Diagnosis only. Nothing changed. I connected to the **live Postgres and Valkey**
(read-only: `EXPLAIN`, `information_schema`, `SCAN`, `CONFIG GET`) using the
credentials in `backend/.env`. No writes, no schema changes.

> **Which environment is this?** The database holds 720 conversations, 2,995
> users and 126 eligibility outcomes, with rows dating to 2025-02-04. That is not
> a fresh local scratch database. **Please confirm whether `backend/.env` points
> at production or a shared staging environment** — it changes the severity of
> §5 considerably, though not the code-level findings.

---

## 1. The scope correction, restated

The pack's Postgres section assumes retrieval runs on pgvector with HNSW. **It
does not** (P0). Measured on the live database:

```
documents table:  0 rows
  ix_documents_embedding_en   hnsw (((embedding)::halfvec(3072)) halfvec_cosine_ops)
  ix_documents_persona_tags   gin (persona_tags)
  ix_documents_account_status_tags  gin (account_status_tags)
  ix_documents_language       btree (language)
```

A complete, correctly-built pgvector setup — including the knowledgeable
`halfvec` cast that works around pgvector's 2,000-dimension indexing limit for
3,072-dim `text-embedding-3-large` — sitting on **an empty table that nothing
queries**. Retrieval goes to Chroma on local disk.

So: there is no sequential scan over embeddings to find, no distance-operator
mismatch to check, and no `ef_search` recall/latency curve to plot, **because no
vector query runs against Postgres at all**. Reporting a tuned curve here would
be fiction. The equivalent real work — chunking, top-k, hybrid search,
cross-lingual retrieval quality — is P8's, against Chroma.

What this *is* is dead infrastructure that still costs something: `check_embedding_dimensions()`
runs at every boot to validate a column nothing writes (P7-007).

---

## 2. FastAPI

**Sync/async correctness.** Cross-referencing P1: the one confirmed event-loop
blocker is `voice/router.py:190 async def speak` (P1-002). Retrieval does **not**
block — verified in `langchain_core/retrievers.py:158,323`, it delegates to a
threadpool. No other route does blocking I/O on the loop.

**Dependency injection — correct.** Every expensive object is process-wide via
`@lru_cache(maxsize=1)`: `get_engine`, `get_sessionmaker`, `get_client` (Valkey),
`get_vector_store`, `get_agent`, `_follow_up_model`, `_title_model`,
`_summary_model`. **Nothing is constructed per request.** No measurement needed —
there is no per-request construction to measure.

**Pydantic — v2 throughout.** `model_validate`, `model_dump`,
`Field(default_factory=...)`, `SettingsConfigDict`. No v1 idioms. `response_model`
is set on `/health`, `/chat` and `/api/title`, so internal fields cannot leak
through the serializer. Validation is field-level with `max_length` bounds
(`message` 8000, `answer` 20000) — nothing O(n) over a large payload on the hot
path.

**Middleware.** Exactly one: `CORSMiddleware`. Order is not a question with a
single entry, and its hot-path cost is a header check. Nothing to fix except the
wildcard origin already filed as P0-008.

**Lifespan.** Startup is well ordered: ingest-if-empty → agent build (so model
errors surface at boot, not mid-request) → voice registry validation → DB warm →
schema check → Valkey ping. Shutdown calls `await dispose_database()`.

Two gaps:
- **No explicit drain of in-flight streams.** uvicorn's graceful shutdown will
  wait on open responses, so this is mostly covered by the server rather than the
  app — but nothing is deliberate about it.
- **A restart discards every conversation's memory**, because the checkpointer is
  an in-process `InMemorySaver` (P0-003). That is not a lifespan bug so much as
  the consequence of P0-003, but it belongs in the same conversation.

**Health vs readiness — not distinct (P7-009).** There is one `/health`
(`main.py:159`) reporting `status`, `database`, `cache` and `cache_stats`. There
is no separate readiness probe, and **nothing checks the model provider** — the
one dependency whose failure makes the product useless. nginx deliberately does
not expose `/health`, so it is loopback-only, which is fine for liveness but
means no external system can distinguish "up" from "able to answer".

---

## 3. Postgres — the strongest part of the codebase

Everything the pack asks about connection handling is **correct**, and verified
against the live database rather than inferred:

| Check | Finding |
|---|---|
| Pooled vs direct endpoint | `-pooler` present ✅, with a startup warning if absent (`engine.py:77-86`) |
| **asyncpg-through-pgbouncer prepared statements** | **`statement_cache_size: 0` (`engine.py:101`)** ✅ — the exact pitfall the pack names, handled, with a comment saying why |
| Neon scale-to-zero | `pool_recycle=280` + `pool_pre_ping=True` ✅ |
| libpq-only params | `sslmode`/`channel_binding`/`options` stripped, `ssl: "require"` preserved ✅ |
| Pool size | 5 + 5 overflow = 10 connections, single worker. Sessions are short and **never span a model call**, so 10 is ample. |
| Live schema vs migration chain | `alembic_version` = `0007_accounts` = chain head ✅ |
| Migration linearity | 0001→0002→0003→0004→0005→0006→0007, single head, no branches ✅ |
| Reversibility | 0006 is genuinely reversible **with data preservation** — it reconstructs `owner_key` from `users.device_id` on downgrade ✅ |

**No transaction is ever held open across an LLM call.** I checked every
`session()` use in the request path: `_open_conversation` (opens and closes),
`_prepare_messages` (loads context, closes), `_persist_turn` (runs *after* the
model call). The pack flags this as "a killer at concurrency"; it is not present.

**No N+1 anywhere.** Every repository read issues a constant number of queries:
`load_transcript` 2, `load_context` 3, `turns_awaiting_summary` 3. No query
inside a loop.

### EXPLAIN (ANALYZE, BUFFERS), live

**`list_conversations`** — the rail's query, the hottest read:

```
Limit  (cost=0.28..8.29) (actual time=1.196..1.198 rows=1)
  ->  Index Scan using ix_conversations_owner_updated on conversations
        Index Cond: (owner_id = '...'::uuid)
Execution Time: 1.226 ms
```

Index Scan, **no Sort node** — the index is `(owner_id, updated_at DESC)`, so the
ordering is satisfied by the index. This is exactly right.

I nearly filed a finding here: migration 0005 indexes `owner_key`, while the
model queries `owner_id`. Checking 0006 showed it adds `owner_id`, backfills it
from `owner_key`, drops the old index and column, and **rebuilds the index on
`owner_id`**. The concern was unfounded.

**`load_transcript`** — unbounded (P7-005):

```
Sort  (Sort Key: seq, Method: quicksort Memory: 28kB)
  ->  Bitmap Heap Scan on messages
        ->  Bitmap Index Scan on ix_messages_conversation_seq
Execution Time: 1.367 ms
```

Fast today (4 rows), but `select(Message).where(conversation_id).order_by(seq)`
has **no LIMIT and no pagination**. It backs `GET /api/conversations/{id}`, which
the client calls to restore a conversation — and P5 measured that the client then
renders every message with no virtualization. A long conversation is therefore
an unbounded query feeding an unbounded render.

**Indexes on hot-path columns are complete.** Every `WHERE`/`ORDER BY` column in
the request path is indexed: `conversations(owner_id, updated_at DESC)`,
`messages(conversation_id, seq)` unique, `users(lower(email)) WHERE email IS NOT
NULL`, `users(device_id)`, `auth_tokens(token_hash)` unique,
`auth_tokens(user_id, purpose)`.

**`append_turn` has a small race (P7-008).** It computes `MAX(seq)+1` then
inserts. Two concurrent appends to one thread can both read the same max; the
unique index catches it, but the resulting exception is swallowed by
`_persist_turn`'s try/except and **the turn is silently lost**. Low probability —
the client blocks send-during-turn — but the failure mode is silent data loss.

---

## 4. Data growth and the retention promise — **the S1 of this pass**

`backend/PRIVACY.md` publishes a commitment: anonymous conversations are deleted
after `ANONYMOUS_RETENTION_DAYS` (180). `app/retention.py` implements it
correctly, and `app/jobs.py:99-100` registers it:

```python
cron_jobs = [cron(retention_job, hour=3, minute=15, run_at_startup=False)]
```

**Nothing in the deploy ever starts an arq worker.** `deploy/` contains
`aspire-api.service` and `aspire-web.service` and no third unit;
`ecosystem.config.cjs` defines `aspire-api` and `aspire-web` and no third app.
`deploy/README.md:367` refers to "the arq worker (`arq app.jobs.WorkerSettings`)"
as though it exists — but no artefact creates it.

Measured consequence on the live database:

```
ANONYMOUS_RETENTION_DAYS = 180
anonymous, unclaimed, last seen > 180 days ago:   20
oldest such row last seen:                        2025-12-06
conversations still held for those identities:    20
```

**The published data-retention commitment is not being kept**, by roughly eight
months, on a product whose users are children. The code is right; nobody runs it.

Related shape worth recording for P9: of 2,995 users, **2,713 are anonymous and
2,473 of those own no conversation at all**. That is the intended consequence of
the IDOR fix (`POST /api/auth/anonymous` always creates a new row rather than
looking one up) — but it means a row is created and retained for 180 days for
every *visit*, including visits where nobody asked anything. At national scale
that is a large store of records about people who never used the product.

---

## 5. Valkey — shared with someone else's application

`SCAN` over the live instance, 274 keys total:

| Namespace | Keys | TTL |
|---|---|---|
| `bull-test:*` | 238 | none |
| `bull:*` (`settlement`, `transfer`) | 34 | none |
| `aspire:*` | **2** | **none** |

**`bull:*` is BullMQ — a Node.js queue. This project uses arq (Python).** The
instance is shared with a different application, whose queues are named
`settlement` and `transfer`. ASPIRE owns two keys on it, and they are the hit and
miss counters.

```
maxmemory         0          (unlimited)
maxmemory-policy  noeviction
used_memory       1.79M
dbsize            274
```

Three problems compound:

1. **Co-tenancy with an unrelated system.** A `FLUSHDB` from either side wipes the
   other. ASPIRE namespaces its keys well (`aspire:answer:v1:`), so silent
   collisions are unlikely — but arq's own keys are not similarly prefixed.
   A settlement/transfer queue sharing a datastore with a children's chatbot is
   also a segregation question for a government deployment, independent of the
   technical risk.
2. **`maxmemory = 0` with `noeviction`.** Neither a ceiling nor a policy was
   chosen. If the instance fills the host, writes begin failing — ASPIRE degrades
   silently (its cache catches everything), but the co-tenant's job queue would
   not.
3. **Zero cached answers present.** No `aspire:answer:v1:*` key exists. Either
   the cache has never retained an answer here, or all have expired past the 6h
   TTL.

### Cache correctness — mostly right

**Right:** the key includes language, persona and account status
(`cache.py:51-81`) with an explicit comment on why serving an English answer into
a Spanish session is the worst failure this cache can have. Keys are SHA-256
digests, so no user text reaches logs or `KEYS` output. Every write sets a TTL.
Reads and writes never raise — a cache outage degrades to a miss. Only first
turns are cacheable, which is what makes an exact-match cache safe here.

**And the hit rate is genuinely measured** (`_HITS`/`_MISSES`, reported on
`/health`). The pack says being unable to measure it is itself a finding; they
can.

**Three gaps:**

- **No stampede protection (P7-003).** A miss lets every concurrent caller run
  the full agent. The landing page's four starter chips are the
  highest-collision strings in the product — a classroom tapping "What is the
  ASPIRE Programme?" on a cold cache is N simultaneous agent runs, each with its
  own retrieval and two model calls.
- **No knowledge-base version in the key (P7-004).** The pack asks to *prove*
  stale answers cannot survive a KB edit. They can: keys are
  `aspire:answer:v1:{digest(question, lang, persona, status)}` with nothing
  identifying the corpus, so after re-ingesting an edited `knowledge_base.csv`,
  answers from the old corpus keep serving for up to `RESPONSE_CACHE_TTL_SECONDS`
  (21,600s = 6 hours). For a government FAQ where a correction may be the reason
  for the edit, that is the wrong default.
- **The counters have no TTL and never reset (P7-006).** Measured: they are the
  only two `aspire:*` keys, both persistent. The reported hit rate is
  lifetime-cumulative, so it cannot show whether the cache is working *now*.

Serialization is `json.dumps` of a small dict (reply + up to 6 sources capped at
600 chars each + follow-ups) — payloads are a few KB, cost negligible.

---

## 6. Summary

**9 findings: 1 × S1, 4 × S2, 4 × S3.**

**Worst — P7-001 (S1):** the arq worker is never deployed, so the retention cron
has never run, and the 180-day deletion promise published in `PRIVACY.md` is
being missed by about eight months. Measured, not inferred: 20 expired anonymous
identities and their 20 conversations are still held. The implementation is
correct; the deployment omits it entirely.

**Second — P7-002 (S2):** the Valkey instance is shared with an unrelated
BullMQ application handling "settlement" and "transfer" queues, with no memory
ceiling and `noeviction`.

Postgres is the best-engineered part of this system. The asyncpg/pgbouncer
prepared-statement trap is handled, the pooled endpoint is enforced with a
warning, the live schema matches the migration chain exactly, migrations are
linear and genuinely reversible with data preservation, the rail's query is a
clean index scan with no sort, there are no N+1s, and **no transaction is ever
held across a model call**. I went looking for the classic concurrency killers
and did not find them.

**What I could not do:** the pack's `ef_search` recall/latency curve has no
subject — there is no live vector index to tune. Retrieval quality is P8's
against Chroma.
