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
