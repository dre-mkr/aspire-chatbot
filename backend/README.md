# ASPIRE Backend

A FastAPI service that answers questions about ASPIRE, built on **LangGraph**.

Every turn runs through one graph — hydrate, guard, safety_in, a router confined
to the agents an access matrix has granted, the agent itself, safety_out, persist
— exposed as server-sent events at `POST /v2/chat/stream`. That endpoint is the
whole chat surface; the older `/chat` and `/chat/stream` are gone rather than
deprecated.

Retrieval is hybrid (vector + lexical, RRF-fused, then reranked) over a corpus
that lives in **Postgres with pgvector**. The CSV in `data/` is the source of
truth that `python -m app.ingest` loads from; it is not what the service reads at
request time.

**So this service does not start without a database.** See Setup.

## Requirements

- Python 3.12+
- An API key for your chat model (OpenAI by default, using `gpt-5.6-luna`)

Both the chat model and the embeddings use OpenAI, so **one `OPENAI_API_KEY` covers
everything**. Embeddings default to `text-embedding-3-large` (3072 dims) and are
configured separately from the chat model, since they're a separate API.

> **Model access is granted per OpenAI project.** Not every key can use every
> model — an unavailable one fails with a 403 `does not have access to model`. To
> see what your key can actually use:
>
> ```bash
> python -c "from app.config import get_settings; get_settings()
> from openai import OpenAI; print(sorted(m.id for m in OpenAI().models.list()))"
> ```

Ingest calls the embeddings API once per chunk, so rebuilding the store costs a
small amount. A local no-key alternative is one config line away — see
[Swapping models](#swapping-models).

## Setup

```bash
cd backend
cp .env.example .env          # then edit .env and add your key
```

**Pick one of the two paths below and stick with it.** They both create `.venv`,
and running one over the other leaves a mixed environment: `python -m venv` swaps
the interpreter but leaves the previously installed packages in place, so you end
up with (for example) a Python 3.13 interpreter trying to load binaries compiled
for 3.14. That surfaces as a confusing import error like:

```
ImportError: ... (No module named 'pydantic_core._pydantic_core')
```

If you hit that, delete `.venv` and reinstall with a single path.

With [uv](https://docs.astral.sh/uv/) (preferred):

```bash
uv sync
uv run python -m app.ingest      # prefix commands with `uv run`
```

Or with a plain venv:

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Both paths use exact pinned versions and both target the Python in
`.python-version` (3.13), so they agree on the interpreter.

### Minimum config

Three values are required. The service refuses to start without any of them, and
says which one is missing.

```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://user:pass@host/db     # Postgres 16+ with pgvector
SESSION_SECRET=...                              # >= 32 bytes; see below
```

`SESSION_SECRET` signs session tokens. There is no default on purpose — a
signing key with a fallback is a key an attacker also has — and a key shorter
than 32 bytes is refused for the same reason a missing one is. Generate one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`DATABASE_URL` is required because the knowledge base lives in Postgres. TLS is
required for every host except loopback, so a local container works without
certificates and a remote host cannot be downgraded by accident.

Everything else has a working default — the chat model defaults to
`openai:gpt-5.6-luna`. See `.env.example`, which lists every setting the code
reads.

### Then create the schema and load the corpus

Neither happens by itself, and the service will not serve without them:

```bash
alembic upgrade head       # 15 migrations; creates pgvector + every table
python -m app.ingest       # loads data/knowledge_base.csv into `documents`
```

Auto-ingest runs at startup when `documents` is empty, so in practice the
explicit ingest is only needed after editing the CSV. `alembic upgrade head` is
never automatic.

A local Postgres for development:

```bash
docker run -d --name aspire-pg -e POSTGRES_PASSWORD=aspire   -e POSTGRES_USER=aspire -e POSTGRES_DB=aspire -p 5432:5432   pgvector/pgvector:pg16
# DATABASE_URL=postgresql://aspire:aspire@127.0.0.1:5432/aspire
```

Valkey (`VALKEY_URL`) is optional. Without it the response cache, the embedding
cache and the rate limiters are simply off; the service starts and answers.

## The knowledge base

Put your CSV at **`backend/data/knowledge_base.csv`**, or point
`KNOWLEDGE_BASE_CSV` somewhere else.

> A **sample CSV ships in this repo** so the service runs end to end out of the
> box. Its contents are invented placeholder data — replace it with the real
> knowledge base.

**No rigid schema is required.** Each row becomes one document:

- If the CSV has QA-style columns (`question`/`answer`, plus optionally
  `category`), rows are formatted as readable Q&A text.
- Otherwise every column is joined as `Column: value` lines.
- Either way, all original column values are preserved in document metadata and
  come back in the `sources` field of a `/chat` response.

That mapping lives in one function — `row_to_document` in `app/ingest.py`. To
teach it new column names, edit the `QUESTION_COLUMNS` / `ANSWER_COLUMNS` /
`CATEGORY_COLUMNS` sets at the top of that file.

## Ingest

```bash
uv run python -m app.ingest            # or: python -m app.ingest
uv run python -m app.ingest --csv path/to/other.csv
```

Ingest is **idempotent**: it drops and rebuilds the Chroma collection each run, so
re-running never duplicates rows and deleted rows really disappear. It logs how
many rows and chunks were written.

You usually don't need to run this by hand — **the server auto-ingests on startup
if the vector store is empty** and logs that it did so. Run it manually whenever
the CSV changes.

The store persists to `./data/chroma` (gitignored — rebuild it with the command
above).

## Run the server

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Interactive docs: http://localhost:8000/docs

## API

### `GET /health`

```json
{ "status": "ok" }
```

### `POST /chat`

Request — omit `thread_id` on the first turn:

```json
{
  "message": "Explain compound interest simply",
  "thread_id": null,
  "simple_mode": false
}
```

`simple_mode` backs the client's "Explain it simply" toggle. It asks for plainer
language without changing any fact, and both modes share one conversation thread,
so it can be flipped mid-conversation without losing context.

Response:

```json
{
  "reply": "Compound interest means **your money earns money**...",
  "thread_id": "6508aef3-7da8-42e9-862a-85fe41d36dd1",
  "sources": [
    {
      "content": "Category: Investing Basics\nQuestion: What is compound interest?\n...",
      "metadata": { "category": "Investing Basics", "row": 2, "source": "knowledge_base.csv" }
    }
  ],
  "follow_ups": [
    "How is this different from simple interest?",
    "What if I save EC$50 a month?"
  ]
}
```

`reply` is markdown, limited by the system prompt to prose, `-` bullets, and
occasional `**bold**`. `follow_ups` are two suggested next questions, produced by
a small extra model call; it is best effort, and an empty list just means the
client shows no suggestions.

`sources` contains the snippets the agent **actually retrieved on this turn**, so
answers are inspectable. It is empty when the agent answered without searching
(greetings, small talk).

**Send the returned `thread_id` back on the next request to continue the
conversation** — that's what gives the agent memory of what you already discussed.

### Example

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How much does ASPIRE cost?"}'
```

Follow-up on the same thread:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "And what about the application deadline?",
       "thread_id": "PASTE_THREAD_ID_HERE"}'
```

## Running with the frontend

The React client in `../frontend` calls this service directly from the browser.
Start both, backend first:

```bash
# terminal 1
cd backend && uv run uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && npm run dev          # http://localhost:3000
```

The client reads `VITE_ASPIRE_API_URL` (default `http://localhost:8000`). CORS is
already open for local dev, so no proxy is needed.

**Keep the knowledge base and the tool description in sync.** The agent decides
whether to retrieve by reading `RETRIEVER_TOOL_DESCRIPTION` in `app/prompts.py`.
If you replace the CSV with content on a different subject and leave that
description describing the old subject, the agent will answer general questions
from its own knowledge instead of searching — the reply still looks fine but
`sources` comes back empty and the numbers stop matching your CSV. An empty
`sources` array on a question your CSV covers is the signal.

## Voice layer (ElevenLabs)

Speech-to-text and text-to-speech, entirely inside `app/voice/`. It can be
reviewed, demoed, or switched off in one move, and it never affects text chat.

### Audio is never stored

**Recordings are held in memory for the length of one request and then
discarded.** They are not written to disk, not written to a temp file, not put
in a database, and not written to any log. The only things logged about a
transcription are the request's byte size, the duration, and the detected
language — never the audio and never the transcript text. There is a test that
fails if transcript text reaches the log.

This matters because ASPIRE is a government programme serving children as young
as five, and someone will ask.

Two related guarantees:

- **The API key is server-side only.** It never appears in a response body.
- **Consent is required.** `/api/voice/transcribe` returns **403** unless the
  request carries `voice_consent: true`. The frontend gates this behind a
  one-time consent screen.

### Turning it on

Voice is **off by default**. Enabling it makes a missing voice id a hard startup
failure (deliberately — better than a 500 mid-demo), and a fresh checkout has no
ids, so leaving it on by default would stop the text service from booting.

```bash
VOICE_ENABLED=true
ELEVENLABS_API_KEY=sk_...
VOICE_STELLA=<voice_id>     # one id per persona covers all three languages
VOICE_ORION=<voice_id>
VOICE_AURORA=<voice_id>
VOICE_NOVA=<voice_id>
```

Voice ids come from your ElevenLabs voice library (copy the **Voice ID**, not the
name). Override a single language with `VOICE_STELLA_ES=...`. All twelve
persona × language combinations are checked at startup; a gap fails the boot with
a message naming the exact variables to set.

> **Free plans cannot use *library* voices via the API.** A library voice returns
> `402 paid_plan_required` on every call, which the service reports as a 503
> `voice_unavailable` — so the symptom is "voice never works" with no obvious
> cause. Use **premade** voices (or your own cloned ones) unless the account is on
> a paid plan. To list what a key can actually use:
>
> ```bash
> uv run python -c "
> from app.voice.config import get_voice_settings
> from elevenlabs.client import ElevenLabs
> c = ElevenLabs(api_key=get_voice_settings().elevenlabs_api_key)
> for v in c.voices.get_all().voices:
>     print(v.voice_id, v.category, v.name)"
> ```

The current mapping picks premade voices against each persona's brief: Jessica
(playful, bright) for Stella, Liam (energetic) for Orion, Sarah (mature,
reassuring) for Aurora, and Alice (clear educator) for Nova.

Delivery per persona lives in `app/voice/registry.py` — Stella runs at `speed`
0.9 because five-year-olds need it slower, Aurora at 1.0 with the highest
stability because she is the voice a parent has to trust.

### Endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /api/voice/transcribe` | multipart audio → text. Requires `voice_consent`. |
| `POST /api/voice/speak` | `{text, persona, language}` → `audio/mpeg` |
| `GET /api/voice/config` | personas, languages and current limits, so the client renders from the server instead of hardcoding numbers that drift |
| `POST /api/voice/realtime-token` | stretch goal; returns 501 |

A transcript is treated as **untrusted user input**. `/transcribe` returns the
text to the client, which submits it to `/chat` through exactly the same
validation a typed message gets. It is never interpolated into a prompt, a tool
argument, or a persona decision.

### Models and cost

| Use | Model | Cost |
| --- | --- | --- |
| Speech-to-text | `scribe_v2` | ~$0.22 per hour of audio |
| Live replies | `eleven_flash_v2_5` | 1 credit per **2** characters (~500 credits / 1000 chars) |
| Prewarmed + figure-heavy | `eleven_multilingual_v2` | 1 credit per character (~1000 credits / 1000 chars) |

`scribe_v1` and `eleven_turbo_v2_5` are deprecated; do not reintroduce them.

Domain keyterms (ASPIRE, ECCB, Basseterre, Warner Park…) are sent with every
transcription to fix local-name recognition. **They add a flat 20% to the cost of
each call** — set `KEYTERMS_ENABLED=false` to price-test without them.

### The number-reading trap

ASPIRE's content is full of `EC$500`, `5-18` and `13 December 2023`, and a TTS
model reading those as digits sounds wrong. ElevenLabs can normalise numbers
itself, but **`apply_text_normalization='on'` is Enterprise-only on the v2.5
Flash model** used for live replies — on a standard plan Flash ignores it.

So `app/voice/speakable.py` spells numbers out in text before synthesis, per
language (`$500` → *five hundred dollars* / *quinientos dólares* / *cinq cents
dollars*). Figure-heavy text is additionally routed to `eleven_multilingual_v2`
as a second net. `speakable()` also strips markdown, citations and URLs, because
sources belong on screen and every wasted character is billed.

### Caching and prewarming

Synthesised MP3s are cached under `data/voice_cache/` (git-ignored), keyed by
`sha256(text + voice_id + model_id + settings)`, with an LRU cap
(`VOICE_CACHE_MAX_BYTES`, default 256 MB). A cache hit never calls the API.

```bash
uv run python scripts/prewarm_voice.py --dry-run   # cost estimate, synthesises nothing
uv run python scripts/prewarm_voice.py             # all personas x languages
uv run python scripts/prewarm_voice.py --persona stella --language en
```

Prewarming uses `eleven_multilingual_v2`: these lines are generated once and
played thousands of times, so quality beats latency. Run it before a demo and the
fixed content no longer depends on live API latency.

### When ElevenLabs is down

Voice failing must never break text chat.

- Timeouts: 5 s for STT, 8 s for TTS.
- On upstream error or timeout: **503** with
  `{"error": "voice_unavailable", "fallback": "browser"}`, so the client falls
  back to the browser's Web Speech API instead of showing a dead button.
- After 3 consecutive failures a circuit breaker short-circuits for 60 seconds
  rather than hammering a failing API.
- `VOICE_ENABLED=false` unmounts the whole module.

### Rate limiting, and its honest limits

Roughly 20 transcriptions and 40 speech calls per 10 minutes, returning **429**
with `Retry-After`.

**This is abuse dampening, not a security boundary.** The chat endpoint has no
authentication, so the only session identifier available is the client's own
`thread_id`, which anyone can regenerate. It stops a stuck retry loop or a demo
laptop from draining the account; it does not stop a determined caller. A real
per-user limit needs real auth, which is a later phase.

It is also **in-memory and per-process**: with several uvicorn workers each holds
its own window, so the effective limit multiplies by the worker count. The same
applies to the circuit breaker.

## Tests

```bash
uv run pytest
```

Six smoke checks covering `/health`, CSV row mapping (both schema paths), and
source extraction, plus the voice suite in `tests/voice/`. Nothing here calls the
LLM or ElevenLabs, so the whole suite runs without any API key.

```bash
uv run pytest tests/voice -q     # voice layer only
```

## Layout

```
backend/
  app/
    main.py      FastAPI app, routes, startup (auto-ingest + agent warmup)
    config.py    pydantic-settings; every tunable lives here
    agent.py     chat model + retriever tool + checkpointer -> create_agent
    rag.py       embeddings and the persistent Chroma store
    ingest.py    CSV -> Documents -> vector store (runnable)
    prompts.py   system prompt + retriever tool description
    schemas.py   request/response models
  data/
    knowledge_base.csv   sample; replace with the real one
    chroma/              persisted vector store (gitignored)
  tests/test_smoke.py
```

## Swapping models

**Chat model** — change one line in `.env`. The value goes to `init_chat_model`, so
`provider:model` selects the provider. `langchain-openai` and `langchain-anthropic`
are both installed, so either works with no code change:

```
CHAT_MODEL=anthropic:claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

Three gotchas with the current default:

- **Use the full `gpt-5.6-luna` ID.** The bare `gpt-5.6` alias routes to Sol, a
  different (pricier) model in the same generation.
- **Don't set `CHAT_TEMPERATURE` on a GPT-5 family model.** They accept only their
  default temperature and return an error for any other value, which would fail
  every request. Leaving it unset omits the parameter. It's safe to set for models
  that do support it, such as Claude or `gpt-4o`.
- **The GPT-5 family needs the Responses API to use tools.** On
  `/v1/chat/completions` these models reject function tools while reasoning is
  active, which breaks retrieval entirely. `OPENAI_USE_RESPONSES_API=true` (the
  default) routes through `/v1/responses` and keeps both working. It is applied
  only when `CHAT_MODEL` starts with `openai:`, so other providers are unaffected.

**Embeddings** — `build_embeddings` in `app/rag.py` is the single switch point.
Defaults to `openai` / `text-embedding-3-large`. `text-embedding-3-small` (1536
dims) is cheaper, if your project has access to it. Or drop to local embeddings to
run with no key and no per-token cost:

```
EMBEDDINGS_PROVIDER=fastembed
EMBEDDINGS_MODEL=BAAI/bge-small-en-v1.5
```

**Changing the embeddings provider or model changes the vector dimensions, and
the `documents.embedding` column has a fixed width.** `text-embedding-3-large` is
3072; `BAAI/bge-small-en-v1.5` is 384. Switching is therefore NOT one config
line — it needs a migration that recreates the column at the new width, then a
full re-ingest, because the vectors themselves are different numbers.

`app/ingest.py` refuses rather than letting this fail per-row on INSERT:

```
EMBEDDINGS_MODEL='BAAI/bge-small-en-v1.5' produces 384-dim vectors but
documents.embedding is 3072-dim. Write a migration to change the column width,
then re-ingest.
```

(Earlier revisions of this file said to delete `data/chroma`. Chroma was removed
when the corpus moved into Postgres; deleting that directory does nothing.)

`fastembed` stays installed so the local path keeps working. If you're sure you
won't use it, `uv remove fastembed` slims the dependency tree considerably (it
pulls in onnxruntime).

## Notes and Phase 1 limits

- **Memory is in Postgres.** `app/graph/checkpointer.py` uses LangGraph's
  `AsyncPostgresSaver` against the same database, so conversations survive a
  restart and are shared across workers. (This note previously described
  `InMemorySaver`, which is no longer what runs.)
- **CORS is wide open** (`allow_origins=["*"]`) for local dev. Narrow it via
  `CORS_ALLOW_ORIGINS` before deploying.
- Errors are logged server-side with tracebacks; clients get a generic message.
- Out of scope by design: auth, streaming, reranking/query-rewriting, Docker,
  deployment.

### A note on LangChain versions

LangChain's APIs moved a lot around v1. Two things commonly found in older
tutorials do not work here:

- `create_retriever_tool` is imported from **`langchain_core.tools.retriever`**.
  The v0.3 path `langchain.tools.retriever` no longer exists.
- Text splitters need the separate **`langchain-text-splitters`** package;
  `langchain.text_splitter` is gone.

Both are verified against the pinned versions in `pyproject.toml`.
