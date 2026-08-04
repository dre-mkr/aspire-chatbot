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

- **Refusal and ambiguous turns.** Expected to have a materially worse TTFT than
  the population above, because a turn that never calls the retriever is held by
  `TurnBuffer` until its message ends — making TTFT equal to full generation time.
  Stated as a hypothesis; it has not been measured and should not be quoted as a
  finding.
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

`RETRIEVER_K` was 4 for P13-001 and P13-002 and is 3 here, and
`FOLLOW_UPS_ALWAYS` is now true. Both changed outside this workstream, mid-session.
The before and after above were taken minutes apart under identical settings, so
the comparison holds — but these numbers are **not** comparable to the P13-001 and
P13-002 tables above, which were taken at k=4. `retrieved_chunk_count` in the
structured log is the way to tell which regime a measurement came from.

`FOLLOW_UPS_ALWAYS=true` also breaks
`tests/test_streaming.py::test_a_continuing_turn_does_not_pay_for_chips`, which
exists to assert that a continuing turn does not spend a model call on chips.
Confirmed by running that test under both values. It is a real assertion about
per-turn cost, and turning the flag on in a latency workstream is worth a second
look: its own config comment calls it "roughly a 2x multiplier on per-turn model
calls".
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
