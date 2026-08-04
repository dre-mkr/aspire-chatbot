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
