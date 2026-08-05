# TTFT latency baseline (P13-001)

Measurement only. Nothing in this phase optimises anything: no stage was moved,
removed, reordered, cached or parallelised, and no prompt, persona voice, factual
content or safety behaviour was touched. Every number below is a `perf_counter`
read on either side of work that was already happening.

- **Instrumentation:** `backend/app/timing.py`
- **Probe:** `backend/scripts/latency_probe.py`
- **Live percentiles:** `GET /debug/timings` (gated on `TIMINGS_ENDPOINT_ENABLED`)
- **Date:** 2026-08-04
- **Commit:** this one

## How to reproduce

```bash
TIMINGS_ENDPOINT_ENABLED=1 CHAT_MESSAGES_PER_WINDOW=200 uvicorn app.main:app --port 8001
```

```bash
python -m scripts.latency_probe --base-url http://127.0.0.1:8001 --label cold
```

Cold means *the server process has served nothing yet*, so restart it before the
cold run and do not restart it before the warm one. The probe cross-checks its
own label against the `cold_start` flag the server reports and warns if they
disagree.

`CHAT_MESSAGES_PER_WINDOW` is raised because one probe run spends the entire
default window (30 messages / 600 s) and a warm run straight after a cold one is
otherwise 30 × HTTP 429. The limiter is a FastAPI dependency that runs to
completion before the turn begins, so raising it cannot move any figure here.

### Configuration these numbers describe

| | |
|---|---|
| chat model | `openai:gpt-5.6-luna`, `use_responses_api=true` |
| embeddings | `openai:text-embedding-3-large` (3072 dims) — **a network call** |
| vector store | Chroma, local SQLite, 338 rows, `k=4`, score threshold 0.2 |
| history | `MEMORY_WINDOW_ENABLED=true`, window 6 turns, Postgres on Neon (pooled) |
| response cache | Valkey, enabled — but **never consulted on this path**; see below |
| workers | 1 |
| client | same host as the server; network time to Neon and OpenAI is real, browser latency is not included |

## Population

30 questions per run, fired sequentially, drawn from `backend/evals/golden.yaml`
(`grounded` and `exact` kinds), balanced to 10 per language × all four personas
in every language. Every turn opens a new conversation, because that is the turn
a first-time reader actually waits through.

**24 of the 30 have a TTFT.** The other six — `en-02`, `en-03`, `es-02`, `es-03`,
`fr-02`, `fr-03` ("Who is eligible…", "How do I apply…") — open the eligibility
card. That turn is silenced by design (`SILENT_TOOLS` in `app/streaming.py`), so
it has a `t_total` and no first token at all. They are excluded from every TTFT
figure and included in `t_total`.

`refuse` and `ambiguous` cases are excluded deliberately: a turn that never calls
the retriever is never released early by `TurnBuffer`, so its TTFT collapses into
its whole generation time. That is a different latency *shape*, not a different
duration, and averaging it in would produce a p95 describing no real population.
It deserves its own measurement — see *Not yet measured*.

---

## Baseline

### cold run

30 turns · cold-start turns: 1 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_open_conversation` | 868.9 | 993.8 | 1423.8 | 16.6% | 10.4% | Neon: upsert the conversation row before the model runs |
| `t_history` | 699.7 | 976.6 | 1079.5 | 13.4% | 10.2% | Neon: window read + running summary |
| `t_prompt_build` | 0.2 | 0.4 | 923.0 | 0.0% | 0.0% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call_1` | 1132.4 | 4125.1 | 5845.5 | 21.6% | 43.2% | derived: request → tool call, less the measured work above |
| `t_embed` | 553.5 | 1023.9 | 1150.3 | 10.6% | 10.7% | OpenAI text-embedding-3-large: network round trip |
| `t_retrieve` | 9.8 | 12.5 | 13.3 | 0.2% | 0.1% | Chroma: local HNSW query over 338 rows |
| `d_model_call_2` | 1617.1 | 3082.0 | 7394.1 | 30.9% | 32.3% | derived: tool call → model's first delta, less retrieval |
| `d_buffer_hold` | 0.3 | 0.5 | 1.1 | 0.0% | 0.0% | derived: TurnBuffer holding text until a tool had run |
| *unaccounted at p50* | 359.0 | | | 6.9% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 2780.5 | 5875.8 | 7412.8 | — | — | cumulative from request received |
| `t_agent_first_delta` | 5240.7 | 9552.5 | 10350.7 | — | — | cumulative from request received |
| `t_ttft` | **5240.8** | **9552.8** | 10351.0 | — | — | cumulative: request received → first token to client |
| `t_total` | 8831.0 | 15572.6 | 24755.0 | — | — | cumulative: request received → last token to client |
| **Auxiliary** | | | | | | |
| `t_retrieve_total` | 565.9 | 1033.7 | 1159.5 | — | — | `t_embed` + `t_retrieve`; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; `/voice/speak` is a separate request |

Client-observed TTFT (cross-check, n=24): p50 5243.6 ms · p95 9557.6 ms

### warm run

30 turns · cold-start turns: 0 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_identity` | 0.0 | 0.0 | 0.1 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_open_conversation` | 851.0 | 973.7 | 1114.0 | 17.6% | 12.9% | Neon: upsert the conversation row before the model runs |
| `t_history` | 708.8 | 952.8 | 990.7 | 14.7% | 12.6% | Neon: window read + running summary |
| `t_prompt_build` | 0.2 | 0.4 | 0.7 | 0.0% | 0.0% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call_1` | 959.0 | 2505.6 | 3185.5 | 19.9% | 33.1% | derived: request → tool call, less the measured work above |
| `t_embed` | 506.6 | 1015.1 | 1125.8 | 10.5% | 13.4% | OpenAI text-embedding-3-large: network round trip |
| `t_retrieve` | 8.9 | 11.7 | 18.9 | 0.2% | 0.2% | Chroma: local HNSW query over 338 rows |
| `d_model_call_2` | 1563.0 | 3716.9 | 111432.6 | 32.4% | **49.1%** | derived: tool call → model's first delta, less retrieval |
| `d_buffer_hold` | 0.3 | 0.5 | 0.6 | 0.0% | 0.0% | derived: TurnBuffer holding text until a tool had run |
| *unaccounted at p50* | 227.4 | | | 4.7% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 2512.3 | 4143.0 | 4766.8 | — | — | cumulative from request received |
| `t_agent_first_delta` | 4824.8 | 7562.7 | 115107.7 | — | — | cumulative from request received |
| `t_ttft` | **4825.2** | **7563.0** | 115108.0 | — | — | cumulative: request received → first token to client |
| `t_total` | 7860.9 | 12964.6 | 209668.0 | — | — | cumulative: request received → last token to client |
| **Auxiliary** | | | | | | |
| `t_retrieve_total` | 516.4 | 1022.4 | 1133.4 | — | — | `t_embed` + `t_retrieve`; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; `/voice/speak` is a separate request |

Client-observed TTFT (cross-check, n=24): p50 4828.3 ms · p95 7566.5 ms

## How to read these tables

Three things will mislead a later phase if they are not said plainly.

**The share columns do not sum to 100% at p95, and must not be read additively
there.** Each cell is that stage's own p95 divided by TTFT's p95, and the request
that was slow for one stage is not the request that was slow for another. The
warm p95 shares sum to 121.3%. The additive reading is only valid at p50, where the
measured durations plus the 4.7% residual account for TTFT exactly.

**`p99` is one observation.** With n=24, p99 is the single slowest request by
construction. The warm p99 column is dominated by one turn — `es-12`, a Spanish
`orion` question that stalled at the provider for 115 s to first token and 210 s
in total. It is a real event worth knowing about and it is not a statistic. Use
p50 and p95.

**Milestones are cumulative, durations are not.** `t_agent_first_tool` is measured
from "request received" and therefore *contains* `t_history` and
`t_open_conversation`. Only the duration rows belong in a budget; mixing the two
into one percentage column is the mistake this layout exists to prevent.

## Which single stage owns the largest share of p95 TTFT

**`d_model_call_2` — the second model call, the one that actually writes the
answer once retrieval has returned — at 49.1% of warm p95 TTFT (3,717 ms of
7,563 ms).** On the cold run it is 32.3% and `d_model_call_1` leads at 43.2%,
which is connection-pool and TLS warm-up landing on the first model call rather
than a different steady-state ordering. The more useful framing is that the two
model calls *together* own 82.3% of warm p95 TTFT and 75.4% of cold: TTFT here is
almost entirely time spent waiting on the chat model, twice, and everything else
competes for the remaining fifth. This is structural rather than incidental —
`app/streaming.py` releases no text until a tool has run, so in an agentic RAG
turn the reader necessarily waits for a full tool-selection round trip before the
answering call has even started. The next-largest single stage is a distant
`d_model_call_1` at 33.1%, then the two Neon round trips at 25.5% combined
(`t_open_conversation` 12.9% + `t_history` 12.6%), then the OpenAI embedding call
at 13.4%. Retrieval itself — the vector search the brief expected to dominate —
is **0.2%**, about 9 ms, and is not worth a single line of optimisation.

## Where the brief and the codebase disagree

Five assumptions in the workstream brief do not hold against this code. None of
them changes the instrumentation's correctness, but each changes where a later
phase should look, so they are recorded rather than quietly worked around.

1. **Retrieval is not pgvector on Neon.** It is Chroma, on local disk
   (`app/rag.py`, `data/chroma/chroma.sqlite3`, 12 MB). There is no vector-search
   network round trip to measure. The pgvector `documents` table was dropped in
   `alembic/versions/20260804_0008_drop_documents.py`, whose own note records that
   the table had always held 0 rows and that its existence "is what made the
   original audit brief assume this service used pgvector in the first place".
   Postgres is used heavily on this path — but for conversations, history and
   accounts, not for retrieval.
2. **Embeddings are not BGE-M3.** They are OpenAI `text-embedding-3-large`, which
   inverts the brief's cost model: the embedding step is a *network* call at
   507 ms p50 / 1,015 ms p95, while the vector search it feeds is local and free.
   BGE-M3 would be the `fastembed` provider, which is available and not selected.
   No HNSW index is in play; the HNSW index named in the brief was on the dropped
   table.
3. **There is no language detection.** `language` arrives on the request from the
   client's own setting (`ChatRequest.language`, default `"en"`). `t_lang` has
   nothing to time and is reported absent, not zero.
4. **There is no persona resolution or routing, and no account-status lookup.**
   Both `persona` and `account_status` arrive on the request and are forwarded to
   the agent config unread; the schema says so of `account_status` in as many
   words. `t_persona` and `t_account` are reported absent. The nearest real thing
   on this path is the ownership lookup, instrumented as `t_identity` — which
   costs 0.0 ms here because the probe is anonymous and `owner_id_for(None)`
   returns without touching the database. An authenticated population would show
   a real number there.
5. **`t_prompt_build` is not a per-request cost.** The system prompt is assembled
   inside `build_agent`, which is `lru_cache`d, so it is paid once per process.
   What remains per-request is `memory.build_prompt` plus its tiktoken pass:
   0.2 ms p50. The 923 ms cold p99 is tiktoken fetching and caching its encoding
   on the first turn.

Two stages were added because without them roughly a second of Neon latency sat
inside an opaque "first model call" figure where nobody would look for it:
`t_identity` and `t_open_conversation`. Two more were added because the brief's
stage list, taken literally, measures everything except the thing that dominates:
`t_agent_first_tool` and `t_agent_first_delta`, from which `d_model_call_1` and
`d_model_call_2` are derived.

## Observations, for later phases to act on or reject

Recorded here as measurements, not as decisions. Nothing below has been changed.

- **The response cache is not on this path at all.** `cache_hit` is `false` for
  all 60 turns, and not because the cache is cold: `_cached_reply` is only called
  from `POST /chat`, while the client uses `POST /chat/stream`. This is the
  already-open finding **P12-001**, and the baseline confirms it costs a full
  two-model-call turn on every repeat of the highest-collision strings in the
  product.
- **`t_open_conversation` (851 ms p50) is two sequential writes to Neon that the
  reader waits through before the model is even called.** It is ahead of the agent
  by deliberate design — `_open_conversation`'s docstring explains why a question
  must be recorded before it is answered — so this is a real constraint, not an
  oversight. Whether it must be *awaited* before the model call is a separate
  question from whether it must happen.
- **`t_history` is 709 ms p50 to read nothing.** Every probe turn opens a new
  conversation, so `load_context` returns an empty window every time. That figure
  is round-trip and connection cost, not query cost.
- **`d_buffer_hold` is 0.3 ms.** The suppression rule in `app/streaming.py` — the
  thing that file warns costs real latency — costs essentially nothing. Tokens are
  released within a third of a millisecond of existing. That question is settled
  and needs no further work.
- **TTS is fully buffered.** `VoiceClient.synthesise` joins the whole MP3 before
  returning (`app/voice/client.py`), so `t_tts_first_byte` records when the first
  chunk arrives from ElevenLabs while the caller still waits for the last.
  Instrumented and reported as absent above only because `/voice/speak` is a
  separate request that this probe does not fire.

## Not yet measured

- **Refusal and ambiguous turns.** ~~Expected to have a materially worse TTFT.~~
  **Measured in P13-004; the hypothesis was wrong.** A refusal is much *faster*
  overall — `t_ttft` 3.3–3.5 s against 8.0 s for a grounded turn — because it makes
  one model call and skips retrieval entirely. The half that was right is the
  mechanism, and it now has a number: a turn calling no tool is held by
  `TurnBuffer` until its message ends, and `d_buffer_hold` measured **383–398 ms**
  on those turns against 0.1 ms on a grounded one. That hold is the tail of a
  ~20-token refusal, so it scales with answer length — which is why removing the
  retriever tool call cannot be done without redesigning the release rule.
- **Multi-turn conversations.** Every turn here is an opening turn, so `t_history`
  is measured against an empty window and the summary path never runs.
- **The voice path end to end**, including `t_tts_first_byte` against a real
  `/voice/speak` request.
- **Concurrency.** Sequential by design, under `--workers 1`; queueing behaviour
  is not characterised.
- **`/chat` (non-streaming).** Instrumented and emits a line with no `t_ttft` —
  there is no first token when the whole reply arrives at once — but not probed.

---

# P13-002 — Chroma out, Neon pgvector in

Not a latency optimisation. This moves the corpus off a local Chroma store onto
Postgres so there is one source of truth, no local disk state, and a path that
works across workers. **`t_retrieve` gets worse, on purpose** — retrieval becomes a
network round trip — and that is what makes the in-memory matrix phase have
something real to remove.

- **Migration:** `alembic/versions/20260804_0009_documents_live.py`
- **Retriever:** `app/rag.py::PgVectorRetriever`
- **Equivalence gate:** `tests/test_retriever_equivalence.py`
- **Date:** 2026-08-04

## Deliverable: before/after `t_retrieve`

| | before (Chroma, local) | after (pgvector, Neon) | delta |
|---|---:|---:|---:|
| cold p50 | 4.0 ms | 523.6 ms | **+519.6 ms** |
| cold p95 | 6.7 ms | 1130.4 ms | **+1123.7 ms** |
| warm p50 | 8.9 ms | 547.5 ms | **+538.6 ms** |
| warm p95 | 11.7 ms | 565.9 ms | **+554.2 ms** |

Retrieval went from 0.2% of warm p95 TTFT to 9.0%. The warm figure is tight
(min 540.7, max 583.6) which makes it a reliable number: it is a round trip to
Neon plus an exact 332-row cosine scan, and the scan is the small part.

## What did NOT happen: a TTFT improvement

Warm `t_ttft` reads 4825.2 → 4640.4 p50 and 7563.0 → 6290.5 p95, i.e. *better*
after adding 540 ms of retrieval. That is noise, not a result, and it would be
dishonest to bank it. Over the same two runs the model calls moved far more than
retrieval did:

| stage | P13-001 warm p95 | P13-002 warm p95 | swing |
|---|---:|---:|---:|
| `d_model_call_1` | 2505.6 ms | 1883.1 ms | −622.5 ms |
| `d_model_call_2` | 3716.9 ms | 2680.1 ms | −1036.8 ms |

A combined ~1.66 s of provider variance swamps a 0.54 s regression. **At n=24,
cross-run TTFT comparisons are not a usable signal; per-stage durations are.**
Anything claiming a TTFT win from here needs either many more samples or a stage
figure to point at.

## Behaviour: unchanged, and here is how that was established

Rule 2 says no change to wording, persona voice, factual content or safety
behaviour. Retrieval feeds all four, so this got the most attention in the phase.

**Retrieval quality is identical.** `python -m evals.run --retrieval` over all 60
golden cases, scored on both backends minutes apart:

| | hit_rate | MRR | en | es | fr |
|---|---:|---:|---:|---:|---:|
| Chroma | 0.95 | 0.9056 | 1.00 | 0.90 | 0.95 |
| pgvector | 0.95 | 0.9056 | 1.00 | 0.90 | 0.95 |

Per-kind is identical too (grounded 1.00, exact 0.833), and the same three cases
miss on both (`es-x2`, `es-x4`, `fr-x4`).

**The relevance floor was carried across exactly, not re-tuned.** This needed
care, because `config.py` described a transform that was not running.
`RETRIEVER_SCORE_THRESHOLD=0.2` was written against Chroma's
`similarity_score_threshold`, and the collection had been created with Chroma's
*default* metric — `l2`, not cosine, because `build_vector_store` never passed a
`collection_configuration`. Chroma's `l2` space returns **squared** L2, so the
relevance function in play was `1 − L2²/√2`. Verified against the live store
rather than assumed: for "What is ASPIRE Day?" Chroma reported 0.49243456 and
`2 − 2·cos_sim` over the same vectors gives 0.49244264.

The embeddings are unit vectors, so `L2² = 2·cos_dist` and the keep condition is:

```
1 − (2·cos_dist)/√2  ≥  threshold      →      cos_dist  ≤  (1 − threshold)/√2
```

At 0.2 that is **cos_dist ≤ 0.565685, i.e. cosine similarity ≥ 0.434315**, which
is what `rag.chroma_floor_as_cosine_distance` computes and what the pgvector query
applies. Confirmed live: out-of-scope questions ("What is the capital of France?",
the chemistry one) return **zero** chunks with the floor and four without it.

## Top-5 equivalence: what the investigation actually found

The phase brief said a divergence "means an embedding or normalization bug, not an
acceptable approximation difference". Two of the thirty probe questions diverged,
and it was neither. The third possibility is worth recording because it changes
what can be asserted at all.

1. **Both searches are exact.** pgvector's `ORDER BY embedding <=> q` reproduces a
   numpy cosine ranking element for element on all 30 questions. Chroma's HNSW
   returned the exact ranking too — at 332 rows with `ef_search=100` it examines
   the whole graph, so there was never an approximation to inherit. (This is also
   why 0009 builds **no** vector index: at this size an ANN index buys nothing and
   would cost exactness twice, once for HNSW and once for the `halfvec` float16
   cast that 3072 dimensions forces.)
2. **OpenAI's embedding API is not bit-deterministic.** Two identical
   `embed_query` calls differ by up to **9.2e-05** per component. Document vectors
   from the Chroma ingest and the Neon ingest differ by up to **1.45e-03** — a
   cosine perturbation of ~1.5e-04.
3. **The two divergent questions have candidates closer together than that.** For
   "Combien y a-t-il sur le compte d'épargne ASPIRE ?", ASP-254 and ASP-172 sit
   **1.5e-04** apart. Their order is a coin flip below the embedding model's own
   reproducibility floor. Both are equally relevant context in a top-4 prompt.

So exact top-k equality across a re-ingest is **not obtainable** while embeddings
come from a hosted non-deterministic provider. The test therefore asserts what is
true and would still catch a real bug: the ranking is exact given the vectors,
rank 1 is stable on all 30, and any set difference is confined to chunks within
2e-3 cosine distance of the top-k boundary — an order of magnitude above the
measured noise and two orders below the span separating a relevant chunk from the
floor. A chunk lost to a bad cast or a normalisation error would sit far outside
that band.

**This makes local embeddings more attractive than the latency case alone
suggested.** A deterministic local model would make ingestion reproducible *and*
remove `t_embed` (425 ms p50 / 629 ms p95) from the request path.

## Cold and warm tables

### cold (pgvector) run

30 turns · cold-start turns: 1 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_open_conversation` | 812.2 | 848.3 | 1184.5 | 16.9% | 11.6% | Neon: upsert the conversation row before the model runs |
| `t_history` | 659.9 | 891.6 | 931.0 | 13.7% | 12.1% | Neon: window read + running summary |
| `t_prompt_build` | 0.1 | 0.6 | 273.3 | 0.0% | 0.0% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call_1` | 929.3 | 3476.6 | 6050.9 | 19.3% | 47.4% | derived: request -> tool call, less the measured work above |
| `t_embed` | 503.2 | 858.7 | 1843.0 | 10.4% | 11.7% | OpenAI text-embedding-3-large: network round trip |
| `t_retrieve` | 523.6 | 1130.4 | 1162.6 | 10.9% | 15.4% | Neon: exact cosine scan over 332 rows (network round trip) |
| `d_model_call_2` | 1306.4 | 4095.7 | 11811.4 | 27.1% | 55.8% | derived: tool call -> model's first delta, less retrieval |
| `d_buffer_hold` | 0.1 | 0.1 | 0.2 | 0.0% | 0.0% | derived: TurnBuffer holding text until a tool had run |
| *unaccounted at p50* | 81.2 | | | 1.7% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 2434.4 | 4946.1 | 7522.4 | — | — | cumulative from request received |
| `t_agent_first_delta` | 4815.9 | 7341.0 | 15734.6 | — | — | cumulative from request received |
| `t_ttft` | 4816.0 | 7341.1 | 15734.7 | — | — | cumulative: request received -> first token to client |
| `t_total` | 8431.0 | 20554.5 | 21154.4 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | |
| `t_retrieve_total` | 1026.8 | 1989.1 | 2362.7 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 4817.8 ms · p95 7344.5 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

### warm (pgvector) run

30 turns · cold-start turns: 0 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_open_conversation` | 848.8 | 873.2 | 878.2 | 18.3% | 13.9% | Neon: upsert the conversation row before the model runs |
| `t_history` | 694.8 | 711.0 | 711.6 | 15.0% | 11.3% | Neon: window read + running summary |
| `t_prompt_build` | 0.1 | 0.4 | 0.6 | 0.0% | 0.0% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call_1` | 855.4 | 1883.1 | 2729.1 | 18.4% | 29.9% | derived: request -> tool call, less the measured work above |
| `t_embed` | 425.1 | 628.9 | 677.7 | 9.2% | 10.0% | OpenAI text-embedding-3-large: network round trip |
| `t_retrieve` | 547.5 | 565.9 | 583.6 | 11.8% | 9.0% | Neon: exact cosine scan over 332 rows (network round trip) |
| `d_model_call_2` | 1028.2 | 2680.1 | 3099.4 | 22.2% | 42.6% | derived: tool call -> model's first delta, less retrieval |
| `d_buffer_hold` | 0.1 | 0.9 | 2.5 | 0.0% | 0.0% | derived: TurnBuffer holding text until a tool had run |
| *unaccounted at p50* | 240.5 | | | 5.2% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 2392.1 | 3418.7 | 4264.4 | — | — | cumulative from request received |
| `t_agent_first_delta` | 4639.6 | 6290.4 | 6387.3 | — | — | cumulative from request received |
| `t_ttft` | 4640.4 | 6290.5 | 6387.4 | — | — | cumulative: request received -> first token to client |
| `t_total` | 7366.9 | 12017.1 | 14872.5 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | |
| `t_retrieve_total` | 974.1 | 1175.2 | 1225.0 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 4643.5 ms · p95 6292.3 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

---

# P13-003 — the opening turn stops reading history it does not have

`request.thread_id is None` means the thread id was minted by this same request,
so no conversation and no message can predate it and the window read is empty by
construction. It was costing ~680 ms of Neon round trip ahead of the model, paid
by every first-time reader — which is the turn that decides whether somebody
stays.

- **Change:** `app/main.py::_prepare_messages`
- **Tests:** `tests/test_memory.py` (three, at the end)
- **Date:** 2026-08-04
- **Config:** re-baselined at `RETRIEVER_K=3`, `FOLLOW_UPS_ALWAYS=true` (see note)

## Deliverable: before/after

| | before | after | delta |
|---|---:|---:|---:|
| **`t_history` warm p50** | 676.7 ms | 0.0 ms | **−676.7 ms** |
| **`t_history` warm p95** | 792.3 ms | 0.0 ms | **−792.3 ms** |
| `t_history` cold p50 | 684.5 ms | 0.0 ms | −684.5 ms |
| `t_history` cold p95 | 800.7 ms | 0.0 ms | −800.7 ms |
| `t_ttft` warm p50 | 5187.4 ms | 4160.7 ms | −1026.7 ms |
| `t_ttft` cold p50 | 5016.1 ms | 4022.5 ms | −993.7 ms |

**The reliable number is the stage: 677 ms removed at warm p50, exactly and
repeatably, because the read no longer happens.** TTFT p50 fell by ~1.0 s in both
runs — more than the stage accounts for. Some of the excess is the smaller opening
prompt (below) and the rest is the model-call variance this document keeps
warning about. Do not quote 1.0 s as the win; quote 677 ms and note the direction
agreed twice.

`t_ttft` p95 moved 7484 → 10744 (cold) and 10761 → 8050 (warm) — opposite
directions on the same change, which is what noise looks like. Ignore it.

## A prompt bug fell out of this, and only half of it is fixed

The stage was described in P13-001 as reading nothing on a first turn. That was
wrong, and finding out why turned this from a pure saving into a behaviour change
worth stating plainly.

`_open_conversation` runs *before* `_prepare_messages` and writes this turn's
question to Postgres. The window read therefore returned that question, and
`build_prompt` then appended it again — so **the model was being sent the user's
question twice.** Reproduced directly, on a fresh thread:

```
load_context recent = [('user', 'What is ASPIRE Day?')]
prompt sent to the model:
   HumanMessage: 'What is ASPIRE Day?'
   HumanMessage: 'What is ASPIRE Day?'
```

Skipping the read removes the duplicate on opening turns. Measured effect on the
wire: `input_token_count` on an opening turn roughly halved, from 20–38 tokens to
14–19.

**This does not fix turns 2 and later.** There the window read is real and still
contains the just-written question, so those turns still duplicate it. The proper
fix is to order `_open_conversation` *after* `_prepare_messages` — still before
the model call, so the guarantee that a question is recorded before it is answered
survives intact. That is a prompt change on every turn and belongs in its own
phase rather than smuggled into a latency one. **Open, unfixed, recommended next.**

## Note on the config this was measured under

`RETRIEVER_K` was 4 for P13-001 and P13-002 and is 3 here (set in `.env`), and
`FOLLOW_UPS_ALWAYS` was **true at the time these two runs were taken** and has
since been reverted to false. Both changed outside this workstream, mid-session.

The before and after above were taken minutes apart under identical settings, so
this comparison holds — but these numbers are **not** comparable to the P13-001 and
P13-002 tables, which were taken at k=4 with chips on opening turns only.
`retrieved_chunk_count` in the structured log is the way to tell which regime any
given measurement came from; it is 4 in the earlier tables and 3 here.

While `FOLLOW_UPS_ALWAYS` was true it broke
`tests/test_streaming.py::test_a_continuing_turn_does_not_pay_for_chips`, which
exists to assert that a continuing turn does not spend a model call on chips —
confirmed by running that test under both values. It passes again now the flag is
back to false. Worth knowing that the assertion is there, because the flag's own
config comment calls it "roughly a 2x multiplier on per-turn model calls", which
is a thing to turn on deliberately rather than by accident.
### after (k=3, opening turn skips the history read) run

30 turns · cold-start turns: 1 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_open_conversation` | 854.4 | 971.9 | 1268.0 | 21.2% | 9.0% | Neon: upsert the conversation row before the model runs |
| `t_history` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: window read + running summary |
| `t_prompt_build` | 0.1 | 0.4 | 513.6 | 0.0% | 0.0% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call_1` | 911.6 | 2995.4 | 5701.5 | 22.7% | 27.9% | derived: request -> tool call, less the measured work above |
| `t_embed` | 438.8 | 1943.3 | 6568.9 | 10.9% | 18.1% | OpenAI text-embedding-3-large: network round trip |
| `t_retrieve` | 557.2 | 1196.9 | 1228.6 | 13.9% | 11.1% | Neon: exact cosine scan over 332 rows (network round trip) |
| `d_model_call_2` | 1309.1 | 2418.1 | 2503.0 | 32.5% | 22.5% | derived: tool call -> model's first delta, less retrieval |
| `d_buffer_hold` | 0.2 | 0.4 | 0.5 | 0.0% | 0.0% | derived: TurnBuffer holding text until a tool had run |
| *unaccounted at p50* | -48.9 | | | -1.2% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 1763.8 | 4777.0 | 6546.2 | — | — | cumulative from request received |
| `t_agent_first_delta` | 4022.3 | 10743.4 | 10885.2 | — | — | cumulative from request received |
| `t_ttft` | 4022.5 | 10743.5 | 10885.3 | — | — | cumulative: request received -> first token to client |
| `t_total` | 7371.2 | 13500.2 | 14330.9 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | |
| `t_retrieve_total` | 999.8 | 3172.0 | 7263.1 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 4024.1 ms · p95 10744.8 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

### after (k=3, opening turn skips the history read) run

30 turns · cold-start turns: 0 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_open_conversation` | 852.3 | 949.1 | 998.2 | 20.5% | 11.8% | Neon: upsert the conversation row before the model runs |
| `t_history` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: window read + running summary |
| `t_prompt_build` | 0.1 | 0.2 | 1.1 | 0.0% | 0.0% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call_1` | 876.6 | 2623.6 | 4108.8 | 21.1% | 32.6% | derived: request -> tool call, less the measured work above |
| `t_embed` | 495.5 | 838.2 | 3203.6 | 11.9% | 10.4% | OpenAI text-embedding-3-large: network round trip |
| `t_retrieve` | 550.6 | 646.1 | 1178.2 | 13.2% | 8.0% | Neon: exact cosine scan over 332 rows (network round trip) |
| `d_model_call_2` | 1149.2 | 5035.8 | 7119.6 | 27.6% | 62.6% | derived: tool call -> model's first delta, less retrieval |
| `d_buffer_hold` | 0.1 | 0.3 | 0.4 | 0.0% | 0.0% | derived: TurnBuffer holding text until a tool had run |
| *unaccounted at p50* | 236.2 | | | 5.7% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 1733.7 | 3467.8 | 4959.3 | — | — | cumulative from request received |
| `t_agent_first_delta` | 4160.5 | 8049.5 | 12571.9 | — | — | cumulative from request received |
| `t_ttft` | 4160.7 | 8049.6 | 12572.1 | — | — | cumulative: request received -> first token to client |
| `t_total` | 7001.9 | 12242.6 | 16879.2 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | |
| `t_retrieve_total` | 1048.2 | 1984.5 | 3745.8 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 4164.4 ms · p95 8051.3 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

---

# P13-004 — the question was being sent to the model twice

Not a latency phase. A correctness fix, recorded here because P13-003 found it and
only half-fixed it, and because it changes the prompt on every continuing turn.

- **Change:** `app/main.py` — `_prepare_messages` now runs before `_open_conversation`, on both endpoints
- **Tests:** `tests/test_streaming.py` (two, at the end)
- **Date:** 2026-08-04

## The bug

`_open_conversation` wrote this turn's question to Postgres, and *then*
`_prepare_messages` read the window back — which now contained that question — and
`build_prompt` appended it again. Demonstrated on a real continuing turn, by
capturing the messages the agent was actually handed:

```
AssertionError: the question was sent 2 times:
  ['What is ASPIRE?', 'A savings programme.',
   'And what about withdrawals?', 'And what about withdrawals?']
```

P13-003 removed it for opening turns as a side effect of skipping the empty
window read. This removes it everywhere, by swapping the two calls. Both remain
ahead of the model call, so `_open_conversation`'s actual guarantee — a question
is recorded before it is answered, so a failed turn still leaves a conversation
that can be reopened — is untouched.

## Before/after

The unit here is tokens, not milliseconds. A continuing turn with three prior
exchanges in the window:

| | input tokens | messages |
|---|---:|---:|
| before (question duplicated) | 162 | 8 |
| after (question once) | 147 | 7 |
| **saved** | **15 (9.3%)** | 1 |

Opening turns were already covered by P13-003, where `input_token_count` fell from
20–38 to 14–19.

**No TTFT measurement for this phase, deliberately.** `latency_probe.py` fires
opening turns only — every probe request omits `thread_id`, because that is the
turn a first-time reader waits through — so it cannot exercise the path this
changes. Running it would produce 60 turns of model-call noise around a null
result on a code path the probe does not reach. The honest claim is the token
figure above plus the demonstrated removal of the duplicate; there is no
millisecond claim to make.

## Why this was worth its own phase

It changes what the model is shown on every turn past the first, which is exactly
the kind of change a latency workstream is not allowed to make quietly. Bundling
it into P13-003 would have buried a prompt change inside a commit whose headline
was a 677 ms saving.

Two tests pin it: one behavioural, asserting the question appears exactly once in
what the agent receives on a continuing turn with real history; one structural,
asserting the call order in `chat_stream`, so the ordering stays pinned even where
the integration test skips for want of a database. Both were verified to FAIL on
the old ordering — a test that passes either way would have been worthless here.

---

# P13-005 — one model call instead of two

The agent used to spend a model round trip deciding to search, wait for the
search, then spend a second call writing the answer — and `app/streaming.py`
releases no text until a tool has run, so the reader waited out both. The corpus
is now searched on the request path, concurrently with the database work, and
arrives in the prompt before the model is called at all.

- **Agent:** `app/agent.py` (retriever removed from the tool list)
- **Retrieval:** `app/main.py::start_retrieval`, `_await_retrieval`
- **Release rule:** `app/streaming.py::TurnBuffer`
- **Date:** 2026-08-04

## Deliverable: before/after TTFT

Both runs at `RETRIEVER_K=3`, `FOLLOW_UPS_ALWAYS=false`.

| | before (two calls) | after (one call) | delta |
|---|---:|---:|---:|
| **`t_ttft` warm p50** | 4160.7 ms | **1819.3 ms** | **−2341.4 ms (−56.3%)** |
| **`t_ttft` warm p95** | 8049.6 ms | **2941.3 ms** | **−5108.3 ms (−63.5%)** |
| `t_ttft` cold p50 | 4022.5 ms | 1841.2 ms | −2181.2 ms (−54.2%) |
| `t_ttft` cold p95 | 10743.5 ms | 4267.1 ms | −6476.5 ms (−60.3%) |

`t_total` also fell (7001.9 → 4594.7 ms warm p50) but **that comparison is not
trustworthy and should not be quoted.** `FOLLOW_UPS_ALWAYS` was changed outside this
workstream between the two runs, and follow-up chips are generated after
`text_end` — so they sit inside `t_total` and not inside `t_ttft`. The TTFT figures
above are unaffected by the flag; the total is confounded by it.

**This one is signal, not noise, and that is worth stating because the previous
phases' p95 figures were not.** Three reasons: the p50 improvement (~2.3 s)
exceeds the ~1.66 s of model-call variance measured across the P13-001/002 runs;
cold and warm agree to within 160 ms on p50 and both show a ~60% p95 drop; and the
spread narrowed rather than moved, with warm p95/p50 falling from 1.93 to 1.62.
Removing an entire round trip removes its variance too.

Warm p95 after this change (2941 ms) is lower than warm **p50** before it.

## Where it went

| warm stage | before p50/p95 | after p50/p95 | |
|---|---:|---:|---|
| `d_model_call_1` (decide to search) | 876.6 / 2623.6 | **gone** | one call now |
| `t_open_conversation` | 852.3 / 949.1 | 826.5 / 980.2 | **concurrent, off the path** |
| `t_embed` | 495.5 / 838.2 | 401.9 / 583.7 | **concurrent, off the path** |
| `t_retrieve` | 550.6 / 646.1 | 531.9 / 1118.4 | **concurrent, off the path** |
| `t_concurrent_wait` (what the reader waits) | — | 935.9 / 1653.8 | replaces the three above |
| `d_model_call` (the answer) | — | 827.9 / 1341.4 | |

Two model calls became one, and the conversation write disappeared into the search
it now runs alongside. `t_concurrent_wait` at 936 ms p50 contains an 827 ms write
and a ~934 ms search: the write is absorbed essentially completely.

The budget closes to **3.0% unaccounted at warm p50** (54.6 ms), the tightest of
any phase — which is what you would expect once the two largest items are a single
measured wait and a single measured model call.

### Two accounting corrections this phase forced

`t_embed` and `t_retrieve` moved out of the TTFT budget into the auxiliary block.
They still record what retrieval cost; they are no longer time the reader waits, so
leaving them in would double-count them against the stages they overlap.

`t_open_conversation` and `t_retrieve_wait` moved out for the same reason and one
sharper one. Measured on the first cut: `t_open_conversation` 855 ms plus a separate
retrieval wait of 1030 ms, against **1534 ms actually elapsed**. Summing concurrent
stages is not a budget, it is an over-count — and it clamped the derived model
figure to zero. The single `t_concurrent_wait` that contains both is the budget
line now.

## Behaviour: better, and it took two attempts to get there

This changed the system prompt, so `evals.run --answers` was run on the code before
the change, after it, and after fixing what the first attempt broke. All 75 cases,
LLM-judged.

| | retrieval hit | answerable correct | refuse correct | refuse refused | ambiguous correct |
|---|---:|---:|---:|---:|---:|
| before (two calls) | 0.8833 | 0.85 | **10/10** | 7/10 | **3/5** |
| after, first attempt | 0.95 | 0.90 | 9/10 | 9/10 | **0/5** |
| **after, fixed** | **0.95** | **0.9167** | **10/10** | **9/10** | **5/5** |

**The first attempt regressed two things and the eval caught both.**

*All five ambiguous cases stopped asking for clarification and started refusing.* A
vague question ("How much money is it?") matches nothing above the relevance floor,
so the model was handed "no record to answer from" plus a new instruction not to
answer from general knowledge — and duly refused. Asking a question back is not
answering from memory, and `KNOWLEDGE_CONTEXT_EMPTY` now says so.

*`ref-09` — Spanish, "should I withdraw all my money, tell me yes or no" — went from
refused to answered.* GROUNDING said "answer from those entries and nothing else",
which reads as *always answer when entries exist* and quietly outranked the LIMITS
rule that a "should I?" question gets the explanation and never a verdict. GROUNDING
now defers to LIMITS explicitly.

Retrieval quality went **up** (0.8833 → 0.95) and the reason is structural: the
agent used to decide whether to search and sometimes didn't, or searched with
reworded queries. It now always searches, with the reader's own words.

`grounded_rate` moved 0.85 → 0.8333, which is one case in sixty on a single
LLM-judged run. Recorded rather than explained away, and not treated as a finding.

## The safety property that changed, stated plainly

`TurnBuffer` used to release nothing until a tool had run. That was free while every
answer began with a retrieval call. With one model call an ordinary answer calls no
tool at all, so the old rule would have held every answer to end-of-message —
measured at **383–398 ms** on a ~20-token refusal, scaling with answer length. The
rule is now per-message: a message that emits a tool-call chunk has its text
discarded; a message that emits text is an answer and streams.

**This rests on a provider behaviour rather than on a mechanical impossibility, and
that is a real weakening.** Measured across five card- and answer-triggering
questions, a tool-calling message emitted no prose — tool calls and text always
arrived in separate messages:

| question | message sequence |
|---|---|
| "How do I apply for ASPIRE?" | `TOOL:start_eligibility_check` |
| "Am I eligible to join ASPIRE?" | `TOOL:start_eligibility_check` |
| "Can we play a word game about saving money?" | `TOOL:start_game` |
| "Quiz me with a true or false question" | `TOOL:list_games` then `TOOL:start_game` |
| "What is ASPIRE Day?" | `TOOL:search_…` then *text* |

If that ever stops holding, prose could reach the screen before a card tool reveals
the turn was a card. `TurnBuffer.note_tool_call` cannot un-send those bytes, so it
logs an error and sets `leaked_before_tool_call` — a visible defect rather than a
silent one. The games suite and the no-answer-leak tests pass.

Also corrected here: the first cut put retrieved corpus rows in a **SystemMessage**.
`tests/test_kb_injection.py` exists to assert they never carry system authority —
the corpus is a staff-editable CSV, so a spreadsheet edit would become a prompt edit
— and it kept passing only because it never exercised the new path. The block is a
`HumanMessage`, and there is now a test covering the route every turn uses.

## What was given up

The agent can no longer search twice when the first results are thin, which the old
retriever tool description explicitly invited it to do. The corpus is 332 fixed rows
and retrieval hits on the first attempt 95% of the time — but "rarely load-bearing"
is not "never", and this is the trade.

Retrieval also now runs on every turn, including refusals and card turns that
previously skipped it. It is concurrent, so it costs no latency; it does cost an
embedding call.

## Cold and warm tables

### cold (P13-005, one model call) run

30 turns · cold-start turns: 1 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_retrieve_kickoff` | 0.0 | 0.4 | 719.3 | 0.0% | 0.0% | local: asyncio.create_task for the concurrent search |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_history` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: window read + running summary |
| `t_concurrent_wait` | 896.5 | 2417.0 | 2868.6 | 48.7% | 56.6% | what the reader waits for the search AND the write, overlapped |
| `t_prompt_build` | 1.1 | 12.6 | 606.1 | 0.1% | 0.3% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call` | 826.3 | 1662.3 | 2771.7 | 44.9% | 39.0% | derived: the one answering call, less every pre-model stage |
| `d_buffer_hold` | 0.1 | 0.3 | 0.5 | 0.0% | 0.0% | derived: TurnBuffer holding text before releasing it |
| *unaccounted at p50* | 117.1 | | | 6.4% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 1853.3 | 3153.7 | 3153.7 | — | — | cumulative from request received |
| `t_agent_first_delta` | 1841.0 | 4266.9 | 4723.6 | — | — | cumulative from request received |
| `t_ttft` | 1841.2 | 4267.1 | 4723.8 | — | — | cumulative: request received -> first token to client |
| `t_total` | 4818.5 | 7696.2 | 7959.1 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | |
| `t_open_conversation` | 829.7 | 1175.2 | 1567.1 | — | — | concurrent: Neon upsert + question write (off the critical path) |
| `t_retrieve_wait` | 895.1 | 2416.9 | 2868.6 | — | — | of that block, the search alone (overlaps the write) |
| `t_embed` | 366.5 | 1760.5 | 2339.4 | — | — | concurrent: OpenAI embedding round trip (off the critical path) |
| `t_retrieve` | 531.8 | 1122.3 | 1368.2 | — | — | concurrent: Neon cosine scan over 332 rows (off the critical path) |
| `t_retrieve_total` | 904.9 | 2417.9 | 2873.4 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 1845.5 ms · p95 4269.6 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

### warm (P13-005, one model call) run

30 turns · cold-start turns: 0 · cache hits: 0 · turns with a visible token: 24

| stage | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---|
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | |
| `t_lang` | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_retrieve_kickoff` | 0.0 | 0.0 | 0.2 | 0.0% | 0.0% | local: asyncio.create_task for the concurrent search |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_history` | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: window read + running summary |
| `t_concurrent_wait` | 935.9 | 1653.8 | 1655.7 | 51.4% | 56.2% | what the reader waits for the search AND the write, overlapped |
| `t_prompt_build` | 0.6 | 23.9 | 44.0 | 0.0% | 0.8% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call` | 827.9 | 1341.4 | 2714.6 | 45.5% | 45.6% | derived: the one answering call, less every pre-model stage |
| `d_buffer_hold` | 0.1 | 1.0 | 2.2 | 0.0% | 0.0% | derived: TurnBuffer holding text before releasing it |
| *unaccounted at p50* | 54.6 | | | 3.0% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | |
| `t_agent_first_tool` | 1797.7 | 2077.1 | 2077.1 | — | — | cumulative from request received |
| `t_agent_first_delta` | 1819.1 | 2941.1 | 3597.2 | — | — | cumulative from request received |
| `t_ttft` | 1819.3 | 2941.3 | 3597.4 | — | — | cumulative: request received -> first token to client |
| `t_total` | 4594.7 | 6935.4 | 9065.5 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | |
| `t_open_conversation` | 826.5 | 980.2 | 1655.5 | — | — | concurrent: Neon upsert + question write (off the critical path) |
| `t_retrieve_wait` | 921.5 | 1598.0 | 1653.7 | — | — | of that block, the search alone (overlaps the write) |
| `t_embed` | 401.9 | 583.7 | 689.2 | — | — | concurrent: OpenAI embedding round trip (off the critical path) |
| `t_retrieve` | 531.9 | 1118.4 | 1136.5 | — | — | concurrent: Neon cosine scan over 332 rows (off the critical path) |
| `t_retrieve_total` | 933.9 | 1598.7 | 1655.2 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 1821.5 ms · p95 2943.7 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

---

# P13-006 — the response cache, on the transport the client uses

P12-001, closed. The cache was written for `POST /chat`; the client speaks
`POST /chat/stream`. So the only reader was a transport nobody used, and — found
while wiring this — the only *writer* was too, which is why `cache_hit` was false
for all 60 turns in P13-001.

- **Lookup and replay:** `app/main.py::_replay_cached`, `_cache_the_answer`
- **Key fix:** `app/cache.py::cache_key`
- **Tests:** `tests/test_streaming.py` (five), `tests/test_cache_keys.py`
- **Date:** 2026-08-04

## Deliverable: before/after

Measured as a clean pair on one process: clear the 30 probe questions, run once
(every turn a miss), run again (every cacheable turn a hit).

| | `t_ttft` p50 | `t_ttft` p95 |
|---|---:|---:|
| before this phase (P13-005, no cache on the stream) | 1819.3 ms | 2941.3 ms |
| after — **first** ask (cache miss) | 1658.0 ms | 2401.4 ms |
| after — **repeat** ask (cache hit) | **6.2 ms** | **9.1 ms** |

A repeat question went from **1819 ms to 6.2 ms — 293× faster**, and the four
landing starter chips are the highest-collision strings in the product.

**The miss pays almost nothing**, which is the other half of the claim and the
part that needed checking: `t_cache_lookup` is **3.3 ms p50 / 9.0 ms p95**, 0.2%
of TTFT. The lookup is started as a task alongside the corpus search rather than
awaited before it, so a miss absorbs it into work it was going to do anyway. The
first-ask figures above are indistinguishable from P13-005's at this sample size —
the difference is smaller than the model-call variance either side of it.

On a hit, `t_cache_lookup` is 77.5% of the turn. That is the shape of a cache
working: the lookup *is* the turn.

**24 of 30 turns hit.** The other six open the eligibility card and are never
cached, by design — a card creates server-side session state, so replaying one
would render a card for a flow nobody started. That property held without being
touched: `_cache_the_answer` refuses card turns exactly as `/chat` always did.

## A correctness bug this had to fix, not inherit

`/chat` returns its cached reply and stops — no `_open_conversation`, no
`_persist_turn`. A cached first turn therefore leaves **nothing in Postgres** and
never appears in anybody's history.

That is survivable on `/chat`, the fallback transport. It is not survivable here:
the client commits the chat to the rail and the address bar the moment it is sent,
so a conversation that does not exist server-side is a chat on screen with a dead
end behind it — precisely what `_open_conversation` exists to prevent.

So `_replay_cached` records the turn, *after* the reply has gone out. Verified
against the real database rather than against a mock: over the miss-then-hit pair,
**60 of 60 conversations exist with both a question and an answer**.

`/chat`'s own gap is left as it is. Fixing it means changing what that endpoint
returns and persists, which is a behaviour change on a path this phase does not
otherwise touch. Recorded here as open.

## Two bugs found while wiring it

**`cache_key` never used `namespace()`.** The function existed, its docstring said
"any key this module invents needs the same treatment, or the same flake comes
back", and it was used by the metrics counters and by nothing else. Answer keys —
and the lease keys derived from them — sat in the shared production namespace, so
a pytest run read and wrote the live cache.

Invisible for as long as `/chat/stream` never consulted the cache: tests wrote
entries nothing read back. Putting the cache on the transport every test drives
made it visible in one run, with `test_streaming.py` receiving real production
answers in place of its fake agent's. Fixed by namespacing the key, which retires
existing entries — one cold turn per distinct question, the cheapest possible
consequence.

`test_key_is_namespaced_and_bounded` asserted `startswith("aspire:answer:v1:")` —
the *un*-namespaced form. The test encoded the bug rather than catching it, because
the literal it pinned was exactly what the bug produced. It now asserts against
`namespace()`, and a second test checks two namespaces cannot collide on the same
question.

**The probe could not render a mixed population.** With 24 hits and 6 uncached card
turns in one run, the share column divided one population's p50 by another's and
produced **15880.6%**, with an unaccounted residual of **−874.1 ms**. The table now
carries an `n` column and shows a share only where a stage covers TTFT's turns; a
stage recorded on *fewer* turns is marked `n/a` rather than divided. Shares from a
stage measured over *more* turns are approximations and can exceed 100%, which the
table now says on its own face.

## What a cached answer looks like

The whole reply in one delta. Splitting it would not improve TTFT — the first chunk
is the first chunk either way — and pacing the pieces to imitate a model typing
would mean adding delay on purpose, in a workstream about removing it. The client
buffers deltas and reveals settled blocks, so it renders correctly either way.

A cached answer therefore appears at once rather than typing out. That is what a
cached answer is; if it should instead be paced to match a computed turn, that is a
deliberate decision to add latency and belongs to whoever owns the reading
experience.

## Cold and warm tables

### cache MISS (first ask) run

30 turns · cold-start turns: 0 · cache hits: 0 · turns with a visible token: 24

| stage | n | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---:|---|
| *`n` is how many turns recorded the stage. A share is shown only when `n` covers TTFT's turns, and is an approximation when `n` is larger — which is why one can exceed 100%.* | | | | | | | |
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | | |
| `t_lang` | 0 | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | 0 | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | 0 | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_retrieve_kickoff` | 30 | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | local: asyncio.create_task for the concurrent search |
| `t_identity` | 30 | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_cache_lookup` | 30 | 3.3 | 9.0 | 26.4 | 0.2% | 0.4% | Valkey: response-cache read (the whole turn on a hit) |
| `t_history` | 30 | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: window read + running summary |
| `t_concurrent_wait` | 30 | 838.4 | 1464.8 | 1536.3 | 50.6% | 61.0% | what the reader waits for the search AND the write, overlapped |
| `t_prompt_build` | 30 | 0.4 | 0.5 | 0.5 | 0.0% | 0.0% | local: assemble messages, count tokens (tiktoken) |
| `d_model_call` | 24 | 769.3 | 1243.3 | 1263.8 | 46.4% | 51.8% | derived: the one answering call, less every pre-model stage |
| `d_buffer_hold` | 24 | 0.1 | 0.3 | 0.3 | 0.0% | 0.0% | derived: TurnBuffer holding text before releasing it |
| *unaccounted at p50* | 24 | 46.5 | | | 2.8% | | framework overhead not inside any measured span |
| **Milestones** (cumulative from request received) | | | | | | | |
| `t_agent_first_tool` | 6 | 1624.8 | 2919.0 | 2919.0 | — | — | cumulative from request received |
| `t_agent_first_delta` | 24 | 1657.9 | 2401.3 | 2732.8 | — | — | cumulative from request received |
| `t_ttft` | 24 | 1658.0 | 2401.4 | 2732.9 | — | — | cumulative: request received -> first token to client |
| `t_total` | 30 | 4163.2 | 5924.4 | 5985.7 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | | |
| `t_open_conversation` | 30 | 817.9 | 943.6 | 1461.9 | — | — | concurrent: Neon upsert + question write (off the critical path) |
| `t_retrieve_wait` | 30 | 838.4 | 1464.8 | 1536.3 | — | — | of that block, the search alone (overlaps the write) |
| `t_embed` | 30 | 316.2 | 596.4 | 674.6 | — | — | concurrent: OpenAI embedding round trip (off the critical path) |
| `t_retrieve` | 30 | 528.5 | 1104.4 | 1135.3 | — | — | concurrent: Neon cosine scan over 332 rows (off the critical path) |
| `t_retrieve_total` | 30 | 843.0 | 1469.0 | 1541.5 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | 0 | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 1659.2 ms · p95 2403.1 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

### cache HIT (repeat ask) run

30 turns · cold-start turns: 0 · cache hits: 24 · turns with a visible token: 24

| stage | n | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT | share of p95 TTFT | what it is |
|---|---:|---:|---:|---:|---:|---:|---|
| *`n` is how many turns recorded the stage. A share is shown only when `n` covers TTFT's turns, and is an approximation when `n` is larger — which is why one can exceed 100%.* | | | | | | | |
| **TTFT budget** (durations; these sum to t_ttft) | | | | | | | |
| `t_lang` | 0 | n/a | n/a | n/a | — | — | no detection: `language` is supplied by the client (ChatRequest.language) |
| `t_persona` | 0 | n/a | n/a | n/a | — | — | no resolution: `persona` is forwarded to the agent config unread |
| `t_account` | 0 | n/a | n/a | n/a | — | — | no lookup: `account_status` arrives on the request; nothing reads it |
| `t_retrieve_kickoff` | 30 | 0.0 | 0.0 | 0.0 | 0.2% | 0.2% | local: asyncio.create_task for the concurrent search |
| `t_identity` | 30 | 0.0 | 0.0 | 0.0 | 0.0% | 0.0% | Neon: resolve the caller's owner id |
| `t_cache_lookup` | 30 | 4.8 | 7.1 | 7.9 | 77.5% | 77.7% | Valkey: response-cache read (the whole turn on a hit) |
| `t_history` | 6 | 0.0 | 0.0 | 0.0 | n/a | n/a | Neon: window read + running summary |
| `t_concurrent_wait` | 6 | 864.6 | 932.0 | 932.0 | n/a | n/a | what the reader waits for the search AND the write, overlapped |
| `t_prompt_build` | 6 | 0.3 | 0.6 | 0.6 | n/a | n/a | local: assemble messages, count tokens (tiktoken) |
| `d_model_call` | 0 | n/a | n/a | n/a | — | — | not recorded |
| `d_buffer_hold` | 0 | n/a | n/a | n/a | — | — | not recorded |
| *unaccounted at p50* | 24 | 1.4 | | | 22.3% | | framework overhead not inside any measured span — excludes `t_history`, `t_concurrent_wait`, `t_prompt_build`, recorded on FEWER turns than t_ttft and so on a different population |
| **Milestones** (cumulative from request received) | | | | | | | |
| `t_agent_first_tool` | 6 | 1853.6 | 4398.5 | 4398.5 | — | — | cumulative from request received |
| `t_agent_first_delta` | 0 | n/a | n/a | n/a | — | — | not recorded |
| `t_ttft` | 24 | 6.2 | 9.1 | 11.1 | — | — | cumulative: request received -> first token to client |
| `t_total` | 30 | 1634.9 | 6146.4 | 6185.9 | — | — | cumulative: request received -> last token to client |
| **Auxiliary** | | | | | | | |
| `t_open_conversation` | 30 | 804.2 | 826.3 | 897.2 | — | — | concurrent: Neon upsert + question write (off the critical path) |
| `t_retrieve_wait` | 6 | 864.6 | 932.0 | 932.0 | — | — | of that block, the search alone (overlaps the write) |
| `t_embed` | 30 | 7.4 | 394.2 | 410.2 | — | — | concurrent: OpenAI embedding round trip (off the critical path) |
| `t_retrieve` | 30 | 0.1 | 531.4 | 535.8 | — | — | concurrent: Neon cosine scan over 332 rows (off the critical path) |
| `t_retrieve_total` | 30 | 7.4 | 925.6 | 937.1 | — | — | t_embed + t_retrieve; excluded from the budget to avoid double-counting |
| `t_tts_first_byte` | 0 | n/a | n/a | n/a | — | — | voice path only; /voice/speak is a separate request |

Client-observed TTFT (cross-check, n=24): p50 8.2 ms · p95 29.1 ms

Turns that yielded no visible token (6): en-02, en-03, es-02, es-03, fr-02, fr-03 — these opened the eligibility card, whose turn is silenced by design (`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no `t_ttft`, and are excluded from every TTFT figure above.

---

# P13-007 — the audit: what is left in the pre-generation path

Two things: an audit of every LLM call that blocks the first token, and the one
change the audit found still to make.

- **Change:** `app/main.py::_prepare_messages`, `_resolve_owner`, both endpoints
- **Accounting:** `app/timing.py` — `t_session_wait` added, `t_identity` and
  `t_history` moved to auxiliary
- **Probe:** `backend/scripts/session_probe.py` (new — see *Why a second probe*)
- **Tests:** `tests/test_memory.py` (three, at the end), `tests/test_timing.py` (one)
- **Date:** 2026-08-04

## Deliverable: every LLM call that was in the pre-generation path

"Pre-generation" means *before the first visible token* — the thing the reader
waits through. Measured against the code, not against the brief's assumptions.

| # | Call the brief expected | Found? | What serves that purpose now | Effect on `t_ttft` |
|---|---|---|---|---|
| 1 | *(not in the brief)* **agent tool-selection round trip** | **Yes, and removed** | Fixed retrieve-then-answer. The corpus is searched on the request path, concurrently with the database work, and is in the prompt before the model is called at all — `app/agent.py` | **warm p95 8049.6 → 2941.3 ms (−5108.3, −63.5%)**; p50 4160.7 → 1819.3 (−56.3%). P13-005 |
| 2 | LLM language detection | **No — never existed** | `ChatRequest.language`, the client's own setting. The UI selection is already trusted; there is nothing to replace | none: `t_lang` reported absent, not zero |
| 3 | LLM persona classification | **No — never existed** | `ChatRequest.persona`, forwarded to the agent config unread | none: `t_persona` absent |
| 4 | LLM account-status routing | **No — never existed** | `ChatRequest.account_status`, carried so it can key the cache; nothing decides from it. Eligibility verdicts are deterministic Python in `app/eligibility/rules.py`, which imports no LangChain and calls no model | none: `t_account` absent |
| 5 | `condense_question` / history-aware retriever | **No — never existed** | Retrieval embeds the reader's own words verbatim. There is no rewrite step to remove | none |
| 6 | Rolling history summarisation on the request path | **No — already off it** | `summarise_conversation` is called only from the arq worker (`app/jobs.py`). `enqueue_summary` runs *after* the `done` event and never raises | none |

**There are now zero LLM calls in the pre-generation path.** Every model
invocation left in the backend, and where it sits:

| site | what | when |
|---|---|---|
| `main.py::chat_stream` | the answering call | **is** generation |
| `main.py::chat` | the answering call on the `/chat` fallback | is generation |
| `agent.py::suggest_follow_ups` | follow-up chips | after `text_end` **and** after `done` |
| `agent.py::suggest_title` | conversation title | a separate `/api/title` request |
| `agent.py::summarise_conversation` | rolling summary | arq worker only |

The embedding call (`app/rag.py`) is not a chat model and is not on the path
either: it is started as a task before anything is awaited.

So five of the brief's six items needed no work — three describe calls this
service never had, one was retired in P13-005, one was already in a worker. The
sixth is below.

## Item 6: the last sequential work before the model

`owner_id_for` and `load_context` are two independent Neon round trips and were
awaited one after the other. Nothing links them — the lookup needs only the
session token, the read needs only the thread id — so an authenticated caller on
a continuing turn paid both end to end before the model was called.

One `asyncio.gather` makes the pair cost the slower of the two.

This is invisible to `latency_probe.py` by construction, which is why it survived
six phases: that probe fires **anonymous opening turns**, and on those
`owner_id_for(None)` returns without touching the database (`t_identity` 0.0 ms)
and the window read is skipped by P13-003 (`t_history` 0.0 ms). Two stages that
are always zero cannot be overlapped.

### Why a second probe

`scripts/session_probe.py` mints a real anonymous session and asks on a thread
that already has a past. That is the only population where either stage costs
anything. It is additive: `latency_probe.py` is untouched and remains the
instrument for the opening-turn figures every table above reports.

## Deliverable: before/after

20 authenticated continuing turns per run, same host, same corpus, minutes apart.

| | before (sequential) | after (gathered) | after, repeat | delta |
|---|---:|---:|---:|---:|
| **what the reader waits for the pair** | **1214.8 ms** (`t_identity`+`t_history`) | **673.4 ms** (`t_session_wait`) | **692.5 ms** | **−541.4 / −522.3 ms** |
| **the same, p95** | **1597.1 ms** | **896.5 ms** | **906.4 ms** | **−700.6 / −690.7 ms** |
| `t_identity` p50 (the leg) | 530.2 | 520.0 | 526.1 | — |
| `t_history` p50 (the leg) | 684.6 | 673.2 | 692.3 | — |
| `t_concurrent_wait` p50 | 836.9 | 823.8 | 839.7 | unchanged |
| `t_ttft` p50 | 3032.7 | 2579.8 | 2618.0 | −452.9 / −414.7 ms |
| `t_ttft` p95 | 4327.5 | 3440.7 | **5640.0** | **see below** |

**The reliable number is the stage: ~541 ms removed at p50 and ~701 ms at p95,
reproduced on two separate runs.** What makes it reliable is not the size of the
delta but that the *legs barely moved between runs* — identity 530.2 → 520.0 →
526.1, history 684.6 → 673.2 → 692.3, under 2% drift. Neon was equally fast in
all three runs; the difference is the overlap and nothing else.

The mechanism is visible in the numbers: after the change `t_session_wait`
(673.4, 692.5) equals `t_history` (673.2, 692.3) to within 0.3 ms. The identity
lookup is absorbed **completely** — it costs the reader nothing, because it
finishes inside the window read it now runs beside.

### `t_ttft` p95 must not be quoted for this phase

It moved **−886.8 ms on one run and +1312.5 ms on the next**, on identical code.
`d_model_call` p95 over the same three runs: 2270.9 → 1437.1 → 4100.7. A single
slow provider response at n=19 owns that column outright, exactly as this
document has warned since P13-001.

`t_ttft` **p50** improved by 414.7–452.9 ms on both runs — same direction, and
slightly less than the 541 ms the stage saved, which is what it should be: the
model call moved the other way by ~85 ms between the before and after runs.

Quote 541 ms at p50 on the stage. Do not quote a p95 TTFT win.

### Who this helps, stated plainly

**Nobody anonymous, and nobody on an opening turn.** For the population
`latency_probe.py` measures this change is exactly 0 ms, and the tables from
P13-005 and P13-006 stand unaltered. It pays an authenticated reader continuing a
conversation — which is every returning user of a product built around a savings
account they come back to.

## Accounting: two stages left the budget

`t_identity` and `t_history` moved to the auxiliary block and `t_session_wait`
took their place, for the reason P13-005 established when `t_embed` and
`t_retrieve` moved: **summing two concurrent durations is not a budget, it is an
over-count.** Leaving both in would have deducted 1,193 ms of pre-model work from
a turn that only spent 673 ms on it, and understated the model call by the
overlap.

The budget closes to **1.8 ms unaccounted at p50** on the after run
(673.4 + 823.8 + 0.4 + 1084.0 = 2581.6 against `t_ttft` 2579.8), the tightest
figure any phase in this workstream has recorded.

## Behaviour: unchanged, and here is what was checked

No prompt, persona voice, factual content or safety behaviour is touched — this
phase moves two `await`s and adds no instruction to any model.

The one property that could have broken is *whose* conversation this is. The
owner id is resolved concurrently and then handed to `_open_conversation`; a
gather that returned the id but wrote the row anonymously would look fast and
quietly lose the conversation from its owner's history list.
`test_the_owner_id_reaches_the_conversation_write` pins exactly that.

The P13-004 ordering guarantee survives intact: the window is still read before
the question is recorded, because the write is still fired from `after_history`.
`test_history_is_read_before_the_question_is_recorded` and the behavioural
`test_a_continuing_turn_sends_the_question_exactly_once` both still pass.

Three tests were added, and two of them **verified to fail on the sequential
arrangement** — which is the only thing that makes them worth having:

| test | what it pins | fails before? |
|---|---|---|
| `test_the_owner_lookup_and_the_window_read_overlap` | the pair takes 1x a leg, not 2x — measured on the clock | **yes** (2 x 0.15 s) |
| `test_the_two_reads_are_gathered_not_sequential` | the mechanism, named, so a refactor fails loudly | **yes** |
| `test_the_owner_id_reaches_the_conversation_write` | the resolved id still reaches the write | no — it guards the new risk, not the old shape |

## Two things found while auditing, neither fixed here

**`FOLLOW_UPS_ALWAYS` defaults to `true`.** `config.py` sets
`follow_ups_always: bool = True` and nothing in `.env` overrides it, so every
continuing turn spends a second model call on chips — the flag's own comment calls
it "roughly a 2x multiplier on per-turn model calls". The test written to catch
this, `test_streaming.py::test_a_continuing_turn_does_not_pay_for_chips`, **is
failing on `main` today**, confirmed by running it on an unmodified checkout. It
is after `text_end`, so it costs `t_total` and not `t_ttft` — which is why it is
recorded here rather than fixed inside a TTFT phase. The P13-003 note predicted
exactly this and the flag has since drifted back.

**`_open_conversation` is still awaited before the model call**, and at
823–840 ms it is now the largest pre-model item left. It is ahead of the agent by
deliberate design — a question must be recorded before it is answered, so a failed
turn still leaves a conversation that can be reopened. Removing that await trades
a correctness guarantee for latency, so per rule 5 it is flagged and not
implemented.

## Not measured

- **The `/chat` fallback**, which got the same change so the two endpoints do not
  diverge. It has no TTFT to report and was not probed.
- **An authenticated *opening* turn.** `t_history` is 0 there, so the gather saves
  nothing and the identity lookup is exposed in full.
- **`t_total`.** It fell (5888.5 → 5412.9 / 5588.1 p50) but `FOLLOW_UPS_ALWAYS`
  puts a whole model call inside it, so that comparison is confounded in the same
  way P13-005's was. Not quoted.

---

# P14 — prompt cost, a second cache layer, streaming audio, and the overhead

Four workstreams in one tree, measured together because they touch the same
request. **Nothing here is committed**; this document is the record for review.

- **Date:** 2026-08-05
- **Probes:** `scripts/latency_probe.py` (unchanged), `scripts/voice_probe.py`
  (new), `scripts/semantic_margin.py` (new), `scripts/flush_probe_answers.py` (new)
- **Server:** `TIMINGS_ENDPOINT_ENABLED=1 CHAT_MESSAGES_PER_WINDOW=500 uvicorn app.main:app --port 8014`

## Where the briefs and the codebase disagree, again

Five assumptions did not survive contact with the code. Recorded rather than
worked around quietly, because each one changes what the phase could deliver.

1. **There are no four persona system prompts, and no few-shot blocks.** There
   is ONE `ASPIRE_SYSTEM_PROMPT` (1,138 tokens) shared by every persona, plus
   two additive tool sections. Nothing in it is a worked example, so the
   instruction to "cut long few-shot example blocks" has nothing to cut. Full
   per-block census below.
2. **k=3 was already live** (`RETRIEVER_K=3` in `.env`, set during P13-003).
   Re-validated rather than changed; the sweep is below and confirms k=3 is
   the knee.
3. **Embeddings are not BGE-M3 and do not run on CPU.** They are OpenAI
   `text-embedding-3-large` over the network, so "export to ONNX with int8
   quantization and warm up at startup" describes a deployment this service
   does not have. The latency it targets is real, and is addressed the other
   way: by not embedding repeat queries at all (P14-D).
4. **There is no account-status router injecting personalised content.** The
   field arrives on the request and nothing reads it (P13-001 finding 4, still
   true). It is in the cache key regardless, so the isolation the brief asks
   for holds by construction — verified below.
5. **The reverse proxy is nginx, not Caddy** (`deploy/nginx-aspire.conf`).

## The knowledge base changed underneath this phase

**Not by this workstream.** `backend/data/knowledge_base.csv` was edited at
**23:34 on 2026-08-04**, mid-session, adding **374 new `FIN-*` rows** (general
financial education: what money is, the EC$ peg, banknotes, budgeting) and
trimming one trailing space in `ASP-287`. The corpus went from **332 rows to
706** and has been re-ingested — Neon and the CSV agree at 706, fingerprint
`85d3e3efff0a`.

Rule 3 says not to touch the knowledge base and this workstream did not: no edit
here wrote that file. It is recorded because it **confounds the behaviour
comparison** — every "before" figure in this document's eval baselines was
measured against 332 rows and every "after" figure against 706. Five of the 75
eval cases now retrieve at least one of the new rows.

Two things it did NOT affect, checked rather than assumed:

- **Retrieval quality is unchanged**: 0.9500 hit rate / 0.9056 MRR, en 1.00 /
  es 0.90 / fr 0.95, the same three cases missing — identical to four decimal
  places against the 332-row corpus. Adding 374 rows neither helped nor hurt
  the golden set.
- **The cache handled it correctly and automatically.** The fingerprint is part
  of every key, so answers computed against the old corpus became unreachable
  the moment the file changed. That is the mechanism this phase raised the TTL
  to 7 days on the strength of, exercised for real by accident.

---

## P14-A — prompt cost, prefix caching, per-persona routing

### Every prompt block, counted

| block | tokens | on every turn? |
|---|---:|---|
| `ASPIRE_SYSTEM_PROMPT` | 1,138 | yes |
| `GAMES_INSTRUCTIONS` | 649 | yes, when games enabled |
| `ELIGIBILITY_INSTRUCTIONS` | 332 | yes, when eligibility enabled |
| `SIMPLE_MODE_INSTRUCTIONS` | 60 | only with the toggle on |
| `KNOWLEDGE_CONTEXT_PREFACE` | 36 | yes |
| `KNOWLEDGE_CONTEXT_EMPTY` | 95 | only when retrieval found nothing |
| **fixed system prefix** | **2,117** | |

**Nothing was cut, and that is the finding.** The 981 tokens of card
instructions are the only plausible cut, and P8-003 already made that
conditional on a number: how often a card actually starts. That number is now
measured — **16.4% of turns** (72 cards / 438 turns, 7-hour window) — which is
too high to call the instructions dead weight, and the cost of removing them is
a behaviour change on the two flows with the most test coverage in the product.

More decisively: **the prefix is already cached by the provider**, so its
marginal cost is a fraction of its token count. Measured below.

### Deliverable: input tokens and prefix-cache rate, per persona

93 streamed turns, all four personas, three languages.

| persona | n | our count (tiktoken) | provider input p50 | of which cached | **prefix cache rate** | t_ttft p50 | t_ttft p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| stella | 19 | 346 | 4,034 | 3,685 | **91.3%** | 5 ms | 1,851 ms |
| orion | 28 | 356 | 4,115 | 4,040 | **95.3%** | 5 ms | 1,997 ms |
| aurora | 28 | 369 | 4,134 | 4,054 | **95.8%** | 6 ms | 2,667 ms |
| nova | 18 | 350 | 4,038 | 3,685 | **91.0%** | 6 ms | 2,554 ms |

Two things this table says that are worth stating plainly.

**The prefix cache is already working at 91–96%**, without this phase enabling
anything: `openai:` models cache a static prefix above 1,024 tokens
automatically, and the assembly order — system prompt, then summary, then
window, then retrieved corpus, then the question — was already arranged so the
stable part is contiguous. P13-005's `memory.build_prompt` docstring says so in
as many words. **The brief's item 3 was already satisfied; this phase measured
it rather than implemented it.**

**Our token count and the provider's disagree by an order of magnitude** (≈350
against ≈4,100) because `input_token_count` counts only the messages the
endpoint assembles, and the provider counts those *plus* the system prompt and
tool schemas that `create_agent` holds. Both are correct about different things;
the provider's is the billed one, and it is the one now logged.

The `t_ttft p50` column is 5–6 ms because most probe turns were cache hits. Miss
figures are in the P14-B table.

### Per-persona model routing and output caps

Both are config dicts read in exactly one place each
(`agent.resolve_model_for`, `agent.resolve_max_tokens_for`), so they are tunable
from the environment without a code change — which is what the brief asked for.

**`CHAT_MODEL_BY_PERSONA` ships EMPTY, deliberately.** Routing Stella and Orion
to a smaller model changes the wording of every answer those personas get, and
rule 2 forbids shipping that silently in a latency phase. The mechanism is done;
the decision needs `python -m evals.run --answers` in front of it. Available
models on this account: `gpt-5.6-luna` (current), `gpt-5.6-sol`, `gpt-5.6-terra`,
`gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4-pro`.

**`MAX_TOKENS_BY_PERSONA={"": 4096}` ships ON**, as a runaway guard. Sizing it
needed a measurement the brief did not anticipate: on the Responses API the cap
covers **reasoning tokens too**, which the reader never sees. Measured on a real
grounded turn: 191 output tokens, of which **81 were reasoning** and 110 visible.
Across 123 probe turns the visible maximum was 100 tokens. So 4,096 leaves
**21x headroom on the real total** and no turn came within 41x of it. A cap
sized to the visible answer alone — say 512 — would have spent the budget on
thinking and truncated mid-sentence.

### k=3, re-validated

`--sweep-k` over all 60 golden cases:

| k | hit_rate | MRR | en | es | fr |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.8667 | 0.8667 | 0.90 | 0.85 | 0.85 |
| 2 | 0.9333 | 0.9000 | 0.95 | 0.90 | 0.95 |
| **3** | **0.9500** | **0.9056** | **1.00** | **0.90** | **0.95** |
| 4 | 0.9500 | 0.9056 | 1.00 | 0.90 | 0.95 |
| 6, 8, 12 | 0.9500 | 0.9056 | 1.00 | 0.90 | 0.95 |

**k=3 is the knee: k=4 and above buy exactly nothing** — identical hit rate,
identical MRR, identical per-language split, and the same three cases miss
(`es-x2`, `es-x4`, `fr-x4`). The brief's instruction to drop to k=3 was already
in force and is confirmed correct.

---

## P14-B — the second cache layer

### Layer 1 (exact, normalised) — already shipped in P13-006

Measured again here as the baseline for layer 2, and to report the deliverable.

| | `t_ttft` p50 | `t_ttft` p95 | `t_total` p50 |
|---|---:|---:|---:|
| miss (embedding cache warm) | 1,696.7 ms | 2,369.6 ms | 4,500.4 ms |
| **hit** | **4.3 ms** | **8.3 ms** | **2,264.3 ms** |

**Hit rate on the probe set: 24 of 30 (80%).** The other six open the
eligibility card and are never cached by design — a card creates server-side
session state, so replaying one would render a card for a flow nobody started.
Against the cacheable population the hit rate is **24/24 = 100%**.

`t_total` on a hit is 2.26 s rather than ~5 ms because the follow-up chips are
still a model call after the answer has gone out. The reader has the whole
answer at 4.3 ms; the chips land later. **Cached-response target (<50 ms end to
end): MET at 4.3 ms p50 / 8.3 ms p95.**

### Layer 2 (semantic) — built, measured, and left OFF

The machinery is complete: a per-(persona, language, account_status) shelf of
truncated query embeddings in Valkey, cosine-compared against the vector the
turn already computed for retrieval, with the threshold as an env var. It costs
a miss nothing — the probe runs concurrently and is consulted after the prompt
is assembled.

**`SEMANTIC_CACHE_ENABLED=false`, on the evidence of `scripts/semantic_margin.py`.**

At the brief's proposed 0.95 threshold, the two populations this gate must
separate **overlap**:

| population | n | cosine range (shelf dims) | misclassified at 0.95 |
|---|---:|---|---:|
| paraphrases of one question (want HIT) | 16 | 0.66 – 0.94 | **16** (none would hit) |
| distinct questions (want MISS) | 28 | 0.10 – 0.76 | 0 |
| adversarial near-pairs (must MISS) | 6 | 0.83 – **0.9645** | **1** |

The failing pair is the one that matters most on a product serving minors:

```
"Is ASPIRE for children aged 5 to 18?"  ~  "Is ASPIRE for children aged 5 to 12?"
cosine 0.9645  →  would be served the wrong eligibility answer, confidently
```

Meanwhile **not one genuine paraphrase reached 0.95**, so at any threshold safe
enough to exclude the adversarial pair, the layer's hit rate is zero. There is
no setting that is both useful and safe: cosine similarity on this embedding
model cannot distinguish "same question, different words" from "different
question, similar words" at the granularity a government FAQ needs.

Shipping it enabled would have traded a correctness guarantee for speed, which
rule 5 says to flag rather than implement. **Flagged.** It becomes viable with
either a different embedding model or an entailment check in front of the
threshold; the code is in place for whoever does that work.

### TTL, flush, and the safety properties

- **TTL raised to 7 days** (`RESPONSE_CACHE_TTL_SECONDS=604800`). Safe at that
  length only because the corpus fingerprint is part of every key, so a
  knowledge-base edit retires answers by key rotation rather than by expiry.
- **`flush_answers()` runs at the end of `ingest()`.** Verified live: 71 keys
  deleted, 0 remaining. Best effort — an unreachable Valkey must not fail an
  ingest that already committed, and the fingerprint carries correctness anyway.
- **`cache_layer` is logged** on every turn (`"exact"`, `"semantic"`, or null).

Verified against the live cache, not asserted:

| property | result |
|---|---|
| an answer stored under `account_status="holder"` is readable by | **nobody else** (anon, guardian, applicant all miss) |
| key separates on account_status / persona / language | yes / yes / yes |
| an edited corpus changes the key | yes |
| card turns cached | never (`quiet_turn` gate) |
| mid-thread turns cached | never (`thread_id` gate, both directions) |

---

## P14-C — first audio byte, decoupled from full synthesis

### The bug this phase actually found

The first implementation streamed `text_to_speech.convert()`'s iterator and
measured **no improvement at all** — first byte 1.6–2.1 s, statistically
identical to the buffered endpoint. `convert()` returns an iterator over a
response body the vendor only begins sending once synthesis is **complete**, so
chunking it client-side chunks a file that already exists.

`text_to_speech.stream()` is the API that emits audio as it is generated. One
word changed; the entire result follows from it. **Measuring before believing is
what caught this** — the code looked correct both times.

### Deliverable: before/after first audio byte

`eleven_flash_v2_5`, the lowest-latency tier, confirmed serving **all three
languages** (log: `model=eleven_flash_v2_5` on every EN/ES/FR row). No language
needs routing to the slower model.

| language | `/speak` (buffered) first byte p50 | `/speak-stream` first byte p50 | delta |
|---|---:|---:|---:|
| en | 1,030 ms | **221 ms** | **−809 ms (−79%)** |
| es | 658 ms | **265 ms** | **−393 ms (−60%)** |
| fr | 554 ms | **264 ms** | **−290 ms (−52%)** |

| language | `/speak` first-byte max | `/speak-stream` first-byte max |
|---|---:|---:|
| en | 1,418 ms | 263 ms |
| es | 763 ms | 292 ms |
| fr | 568 ms | 302 ms |

**First-audio-byte target (<800 ms): MET, 221–265 ms p50 and 302 ms worst
observed.** n is 2–3 per cell rather than 5: the voice rate limiter
(`MAX_SPEECH_PER_WINDOW=40`) returned 429 for the tail of the run, which is the
limiter working as designed. The separation is large enough that the small n is
not load-bearing — every streaming observation beat every buffered one in the
same language.

An earlier run of this probe measured the **quality** tier by accident, because
its cache-busting salt was a hex UUID and `has_many_numbers(text, threshold=3)`
routes any text with three or more digits to `eleven_multilingual_v2`. A hex
salt averages 3.75 digits. The probe now salts with letters only, and the
server log is checked for the model id rather than assumed.

### Failure isolation

The text response and the audio are separate requests, so a TTS failure cannot
touch the answer on screen — that property predates this phase and is unchanged.
What is new is discipline *within* the audio stream:

- **before the first chunk:** raises `VoiceUnavailable` → the same 503 and the
  same browser-speech fallback the buffered path gives. The first chunk is
  awaited before the `StreamingResponse` exists, because a `StreamingResponse`
  has already committed a 200 by the time its generator runs.
- **after bytes have gone out:** the stream ends early at the last complete
  frame; the player fires `onended` and the UI returns to Play. A truncated
  stream is **never cached**, so the truncation cannot be replayed.
- **on client abort:** the producer thread is signalled and the queue drained,
  so a cancelled playback stops billing instead of finishing into a queue
  nobody reads.

The client prefers MediaSource where the browser supports MP3 in MSE and falls
back to the blob path otherwise (Safari); the fallback still gains the
server-side half, because the download overlaps synthesis instead of following
it.

### The client half, verified in a real browser

A server that streams proves nothing about a client that has to consume it —
MSE is exactly the API that works in theory and throws `InvalidStateError` in
practice, and nothing else in the suite exercises it.
`.impeccable/voice-stream.mjs` drives the real page, clicks Play on a real
answer, and reports what the audio element actually did:

| measurement | result |
|---|---|
| endpoint the client chose | `/api/voice/speak-stream` |
| MediaSource buffers opened | 1 |
| chunks appended / append errors | **192 / 0** |
| `endOfStream()` calls | 1 |
| duration the element reported | 13.56 s |
| `currentTime` after 3.5 s | **3.20 s (playback advancing)** |
| media error / console errors | none / none |

All seven assertions pass. The audio is genuinely being fed in incrementally
and played, not downloaded whole and handed over.

---

## P14-D — the overhead

### Query-embedding cache

Keyed on the normalised query plus the embedding model name, so a model change
is a cold cache rather than a stale vector. Values are packed float32 (≈12 KB
for 3,072 dims, against ≈70 KB as JSON).

| stage | before (cold) | after (warm) | delta |
|---|---:|---:|---:|
| `t_embed` p50 | 345.7 ms | **3.0 ms** | **−342.7 ms (−99.1%)** |
| `t_embed` p95 | 874.2 ms | **14.6 ms** | **−859.6 ms (−98.3%)** |
| `t_concurrent_wait` p95 | 2,127.7 ms | **1,155.9 ms** | −971.8 ms |
| `t_ttft` p95 | 3,134.0 ms | 2,369.6 ms | −764.4 ms |
| `t_ttft` p50 | 1,713.2 ms | 1,696.7 ms | −16.5 ms |

**The stage figure is the claim; the p50 TTFT figure is honestly ~nothing.**
Embedding has been concurrent since P13-005, so removing 343 ms from it does not
remove 343 ms from the critical path — the conversation write (~830 ms) is still
what the reader waits on. What the cache genuinely removes is the embedding's
**tail**: `t_concurrent_wait` p95 falls by 972 ms because a slow embedding can no
longer be the thing the concurrent block is waiting for.

Retrieval quality is **unchanged and identical**: hit_rate 0.9500, MRR 0.9056,
en 1.00 / es 0.90 / fr 0.95 — the same figures to four decimal places as before
the refactor, which is the check that `retrieve_with_vector` returns what
`get_retriever().ainvoke()` returned.

### Connection and buffering

- **One module-level `httpx.AsyncClient`** for the readiness probe, closed at
  shutdown. It was constructed per probe, paying a TCP and TLS handshake on
  traffic that arrives like clockwork forever.
- **SSE is not compressed and not buffered.** Requested with
  `Accept-Encoding: gzip, deflate, br`; the response carries **no
  `content-encoding` header**, plus `x-accel-buffering: no`,
  `cache-control: no-cache`, `transfer-encoding: chunked`. `text/event-stream`
  is deliberately absent from `gzip_types`.
- **First byte before generation completes, confirmed with curl:**
  `ttfb=0.0032s` against `total=4.858s` — **1,500x** apart.
- **nginx**: `proxy_buffering off` added to `/chat` and `/api/`, plus
  `proxy_http_version 1.1`. The app already sent `X-Accel-Buffering: no` and
  nginx honours it per-response, but that put the guarantee in application code
  where a refactor can lose it silently. Now it is stated in both places.
  *(Config edited; not reloaded — this box does not run the production nginx.)*

### BGE-M3 / ONNX quantization

**Not applicable.** Embeddings are OpenAI over the network
(`EMBEDDINGS_PROVIDER=openai`), so there is no CPU model to quantize and no cold
start to warm. `fastembed` is wired and available as a provider if the service
ever moves local — at which point the ONNX work becomes real, and the
determinism argument in P13-002 makes it attractive for a second reason.

### Frontend typewriter — the reveal is not the bottleneck

`.impeccable/live-cadence.mjs` against the running service, measuring every
animation frame:

| measurement | value |
|---|---:|
| **token arrival → first paint** | **49 ms** |
| worst gap mid-answer | 19 ms |
| characters in the final frame | 13 |
| reveal finishing after text declared final | 226 ms |
| the service, before its first token | 3,178 ms |

**The render loop is not throttling below the token arrival rate.** The service
wrote for 269 ms; the reveal drew 270 characters over 679 ms and finished 226 ms
after the last token — it keeps up and lands just behind, which is the intended
feel. All six harness assertions pass.

The number worth staring at is the last row: **3,178 ms of that turn was the
service before its first token, against 49 ms of client**. Backend work is
visible to the user; the frontend is not where the remaining latency is.

---

## Final gate

### L0 baseline against current, every stage

L0 is the P13-001 warm baseline. "Current" is the P14 tree, warm, cache MISS —
the honest comparison, since L0 had no working cache.

| stage | L0 p50 | L0 p95 | P14 p50 | P14 p95 | note |
|---|---:|---:|---:|---:|---|
| `t_lang` | n/a | n/a | n/a | n/a | no detection; client supplies |
| `t_persona` | n/a | n/a | n/a | n/a | no resolution |
| `t_account` | n/a | n/a | n/a | n/a | no lookup |
| `t_identity` | 0.0 | 0.0 | 0.0 | 0.0 | anonymous probe; concurrent since P13-007 |
| `t_history` | 708.8 | 952.8 | 0.0 | 0.0 | opening turns skip it (P13-003) |
| `t_open_conversation` | 851.0 | 973.7 | ~830 | ~950 | concurrent since P13-005 |
| `t_embed` | 506.6 | 1,015.1 | **3.0** | **14.6** | Valkey cache (P14-D) |
| `t_retrieve` | 8.9 | 11.7 | 569.3 | 1,146.4 | Chroma local → pgvector network (P13-002) |
| `t_concurrent_wait` | — | — | 857.8 | 1,155.9 | did not exist at L0 |
| `t_prompt_build` | 0.2 | 0.4 | ~0.4 | ~0.9 | |
| `d_model_call_1` | 959.0 | 2,505.6 | **gone** | **gone** | one call now (P13-005) |
| `d_model_call_2` | 1,563.0 | 3,716.9 | 785.4 | 1,345.7 | now `d_model_call` |
| `d_buffer_hold` | 0.3 | 0.5 | ~0.1 | ~0.3 | |
| **`t_ttft`** | **4,825.2** | **7,563.0** | **1,696.7** | **2,369.6** | **−64.8% / −68.7%** |
| **`t_ttft` (cache hit)** | — | — | **4.3** | **8.3** | cache never hit at L0 |
| `t_total` | 7,860.9 | 12,964.6 | 4,500.4 | 7,432.4 | −42.7% / −42.7% |

### Targets

Reported as numbers, not softened.

| target | goal | actual | verdict |
|---|---|---:|---|
| Retrieval | ~10 ms | **569 ms** p50 | **MISSED — 57x over** |
| Embedding | ~30 ms (0 on hit) | **3.0 ms** warm / 345.7 cold | **MET on cache hit** |
| TTFT | 200–400 ms | **1,697 ms** miss / **4.3 ms** hit | **MISSED on miss; MET on hit** |
| First audio byte | < 800 ms | **221–265 ms** | **MET** |
| Cached response, end to end | < 50 ms | **4.3 ms** | **MET** |

**Why retrieval misses by 57x.** The ~10 ms target describes a local index.
Retrieval is a network round trip to Neon (P13-002 moved it there deliberately,
to get one source of truth). The scan itself is single-digit milliseconds; the
other ~560 ms is the round trip.

**But making retrieval faster would not improve TTFT by one millisecond**, and
the budget is what says so. At p50:

```
t_concurrent_wait   857.8   <- what the reader actually waits
t_open_conversation 856.8   <- the Neon write, inside it
t_retrieve_wait     567.1   <- the search, inside it, ENTIRELY in the write's shadow
```

The concurrent block costs the **slower** of its two members, and the write wins
by 290 ms. Retrieval is already free. Cutting it to 10 ms would leave
`t_concurrent_wait` at ~857 ms and TTFT unchanged. This corrects the obvious
reading of the retrieval row, and it reorders the work: **an in-memory index is
not the next change, it is the second one.**

**Why TTFT misses on a miss, and the only two levers that exist.** The p50
budget is `858 (concurrent block) + 785 (model call) + 53 (everything else)`.
Nothing else is big enough to matter, so there are exactly two levers:

1. **The conversation write, 858 ms.** It is awaited before the model because a
   question must be recorded before it is answered, so a failed turn still
   leaves a conversation somebody can reopen. Worth noting: the guarantee is
   about the *answer*, not the *prompt* — awaiting the write after the model
   call is launched but before the turn is announced would preserve it and take
   up to 290 ms off TTFT immediately (down to retrieval's 567 ms floor). That is
   a real change to a correctness-bearing ordering, so per rule 5 it is
   **flagged, not implemented**.
2. **The model call, 785 ms.** Provider latency for the first token. Only a
   smaller model touches this — which is what `CHAT_MODEL_BY_PERSONA` exists for
   and why it ships empty pending an eval.

Do (1) and then the in-memory index, and the floor becomes the model call alone:
roughly **840 ms**. Still not 200–400 ms. **That target is not reachable on a
cache miss with a hosted model and a durable write**, and saying so is more
useful than a plan that cannot get there. On the path the reader travels most it
is already met with room to spare: **a repeat question answers in 4.3 ms.**

### Configuration this phase added or changed

`.env` is gitignored, so these do not appear in a diff and are listed here for
whoever reviews the change.

| key | value | effect |
|---|---|---|
| `RESPONSE_CACHE_TTL_SECONDS` | `21600` → **`604800`** | 6 hours → 7 days |
| `SEMANTIC_CACHE_ENABLED` | **`false`** (new) | layer 2 built but off — see the margin measurement |
| `SEMANTIC_CACHE_THRESHOLD` | `0.95` (new) | inert while the layer is off |
| `EMBEDDING_CACHE_ENABLED` | **`true`** (new) | the −343 ms `t_embed` saving |
| `MAX_TOKENS_BY_PERSONA` | **`{"": 4096}`** (new) | runaway guard, 21x headroom |
| `CHAT_MODEL_BY_PERSONA` | `{}` (new) | routing mechanism, deliberately empty |

Every new key has a default in `config.py` matching the value above except
`RESPONSE_CACHE_TTL_SECONDS`, whose code default stays at 6 hours — the 7-day
setting is a deployment decision, and its `Field` ceiling was raised from 1 day
to 14 to permit it.

### The test suite: 602 passed, 3 failed, 1 xfailed

```
3 failed, 602 passed, 1 xfailed in 1314.53s (0:21:54)
FAILED tests/test_retriever_equivalence.py::test_both_backends_hold_the_same_number_of_chunks
FAILED tests/test_retriever_equivalence.py::test_any_top_5_difference_is_confined_to_near_ties
FAILED tests/test_streaming.py::test_a_continuing_turn_does_not_pay_for_chips
```

**None of the three is this phase's**, and each was predicted from the code
before the run finished rather than explained afterwards.

**The two equivalence failures are the corpus re-ingest.** That file compares
Neon against the legacy Chroma snapshot, and the two have desynced:

```
chroma.sqlite3 embeddings : 332   (P13-002 snapshot, never re-ingested)
Neon documents            : 706   (re-ingested 2026-08-04 23:34)
```

`test_both_backends_hold_the_same_number_of_chunks` asserts those counts are
equal, so it fails by arithmetic. `test_any_top_5_difference_is_confined_to_near_ties`
fails because pgvector can now return `FIN-*` rows that Chroma does not contain
at all — a set difference far outside the near-tie band it allows. Nothing in
P14 touches either store.

Worth noting what did **not** fail:
`test_rank_one_matches_chroma_for_every_probe_question` **passed**. Adding 374
rows changes what appears at ranks 2–5 on some questions and never displaces the
best chunk on any of the 30. That is a reassuring property of the corpus
addition, obtained for free from a test written for a different purpose.

These tests have been measuring a migration that completed in P13-002. With the
corpus diverged they now measure the divergence, and they want either a Chroma
re-ingest or retirement.

**The third failure is pre-existing**, recorded in P13-007 and confirmed then by
running it on an unmodified checkout: `FOLLOW_UPS_ALWAYS` defaults to `true`, so
a continuing turn does spend a model call on chips and the test that forbids it
fails. Unchanged by this phase, still open.

### Behaviour confirmations

| claim | how it was checked | result |
|---|---|---|
| no persona voice changed | no prompt file edited at all; `CHAT_MODEL_BY_PERSONA` empty, so every persona runs the same model with the same system prompt as before | **confirmed** |
| retrieval unchanged | `--retrieval` over all 60 golden cases | **confirmed, identical to 4 d.p.** |
| output cap cannot truncate | 4,096 against a measured 191-token real turn (110 visible + 81 reasoning); visible max 100 across 123 turns | **confirmed, 21x headroom** |
| no account-specific response reachable from cache | live Valkey: stored under `holder`, read attempted as anon / guardian / applicant | **confirmed, nobody else** |
| KB reload flushes the cache | `flush_answers()` at the end of `ingest()` | **confirmed, 71 → 0** |
| card turns never cached | `quiet_turn` gate, both endpoints | **confirmed** |
| no factual answer changed | `--answers`, 75 cases, LLM-judged | **see below — cannot be asserted cleanly** |

### The answers eval, reported rather than softened

75 cases, 0 errors, against the **706-row** corpus.

| metric | P13-005 baseline (332 rows) | now (706 rows) | delta |
|---|---:|---:|---:|
| retrieval hit rate | 0.9500 | 0.9500 | — |
| answerable correct | 0.9167 (55/60) | 0.9000 (54/60) | **−1 case** |
| grounded | 39/42 | 39/42 | — |
| exact | 15/18 | 15/18 | — |
| ambiguous correct | 5/5 | **5/5** | — |
| refusals correct | 10/10 | 9/10 | **−1 case** |
| refusals refused | 9/10 | 8/10 | −1 case |

**One case moved on each of two axes, in a suite this document already records
as having roughly that much run-to-run variance** (P13-005: "one case in sixty
on a single LLM-judged run… not treated as a finding").

The flagged refusal is `ref-09`, and it is worth reading rather than counting.
The harness's own `refused` flag is **True**; the reply opens *"No puedo decirte
si deberías retirar tu dinero"* — "I cannot tell you whether you should withdraw
your money" — and then explains the withdrawal rule, which is exactly what the
LIMITS rule requires ("offer the explanation instead"). The **judge** marked it
incorrect. Its retrieved context is `ASP-092, ASP-069`, both pre-existing rows,
so the corpus change is not the cause here either.

**What can be said honestly:** P14 contains no mechanism that could change an
answer — the prompts are untouched, persona routing and the semantic cache are
both disabled, the output cap has 21x headroom and truncated nothing, and
retrieval returns byte-identical results. What cannot be said is "no factual
answer changed, proven": the eval moved by one case on two axes, and the
baseline it is compared against was taken on a different corpus. **Re-run
`--answers` against a stable 706-row corpus to get a clean baseline before
reading anything into these two cases.**
