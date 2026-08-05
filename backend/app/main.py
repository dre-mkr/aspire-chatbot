"""FastAPI application: health, readiness, titles, and the routers.

The chat itself is not here any more. `POST /v2/chat/stream` (`app/api/stream.py`)
is the only way to hold a conversation with ASPIRE, and it runs every turn
through the graph: hydrate, guard, safety_in, a router confined to the agents
the access matrix granted, the agent, safety_out, persist.

What used to be here -- `/chat` and `/chat/stream`, a single agent behind a
single system prompt -- is gone rather than deprecated. See the note where it
stood, further down, for where each piece of it went.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from fastapi import Depends, FastAPI, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app import cache as response_cache
from app.agent import suggest_title
from app.config import get_settings
from app.accounts import router as accounts_router
from app.conversations import router as conversations_router
from app.auth import Principal
from app.limits import title_rate_limit
from app.sessions import router as sessions_router
from app.db import (
    check_schema,
    database_enabled,
    dispose as dispose_database,
    warm,
)
from app.eligibility import eligibility_enabled, eligibility_router
from app.games import games_enabled, games_router
from app.ingest import count_corpus, ingest_if_empty
from app.timing import (
    RING as TIMING_RING,
    timings_endpoint_enabled,
)
from app.schemas import (
    HealthResponse,
    TitleRequest,
    TitleResponse,
)
from app.voice import get_voice_settings, validate_registry, voice_router

logger = logging.getLogger(__name__)

# psycopg's async mode cannot run on Windows' default ProactorEventLoop, and the
# checkpointer is psycopg. Set at IMPORT time rather than in the lifespan,
# because by the time the lifespan runs the loop already exists and a policy
# change no longer affects it.
#
# THIS IS NOT SUFFICIENT UNDER UVICORN, and the comment here used to claim it
# was. uvicorn 0.52 builds its loop from an explicit `loop_factory`
# (`ProactorEventLoop` on win32 without --reload/--workers>1), and an explicit
# factory bypasses the event-loop policy entirely -- so this call is inert for
# the loop the API actually serves on, however early it runs. The symptom was a
# 30-second pool timeout and a graph running with no checkpointer at all, which
# reads as an unreachable database rather than as a product with no memory.
#
# `app/serve.py` is the entry point that fixes it, by supplying the loop factory
# itself. This line is kept because it DOES apply to every caller that goes
# through the policy: the scripts, the eval harness, pytest-anyio.
#
# No-op on Linux, where production runs.
if sys.platform == "win32":  # pragma: no cover - platform-specific
    from app.graph.checkpointer import install_windows_event_loop_policy

    if install_windows_event_loop_policy():
        logger.debug("Selector event loop installed so psycopg can connect.")

# Cap what we echo back so a long knowledge-base row can't bloat the response.
MAX_SOURCES = 6
MAX_SOURCE_CHARS = 600


async def _require_corpus(settings) -> None:
    """Refuse to start without a knowledge base. No fallback, by design.

    Postgres is the source of truth as of P13-002, which makes an unreachable or
    empty corpus a fatal condition rather than a degraded one. The alternative --
    starting anyway and letting retrieval return nothing -- is the worst outcome
    available: every turn would be a confident, ungrounded answer or a refusal to
    a question the programme can actually answer, on a government product serving
    minors, and nothing about it would look broken from the outside.

    Ordered after `check_schema` on purpose: `database_enabled()` only tells the
    truth once that has run.
    """
    if not database_enabled():
        raise RuntimeError(
            "The knowledge base lives in Postgres and the database is not "
            "available, so there is nothing to retrieve from. Set DATABASE_URL "
            "and run, from the backend directory:\n"
            "    alembic upgrade head\n"
            "    python -m app.ingest"
        )

    # Auto-ingest on a cold start so a fresh deployment is usable out of the box,
    # exactly as it was before the move off Chroma. Concurrency-safe: see the
    # advisory lock in `ingest_if_empty`.
    await ingest_if_empty(settings)

    chunks = await count_corpus()
    if chunks <= 0:
        raise RuntimeError(
            "The documents table is empty and auto-ingest wrote nothing. Refusing "
            "to serve: retrieval would return no context for every question. Run "
            "`python -m app.ingest` and check the log for why it produced no rows."
        )
    logger.info("Corpus holds %d chunks in Postgres.", chunks)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare the corpus and agent before the first request."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Neon scales to zero, so without this the first message after an idle
    # period pays the wake-up. Warming here rather than disabling scale-to-zero
    # keeps the overnight compute bill at zero and moves the cost to deploy
    # time, where nobody is waiting on it.
    #
    # Moved ahead of the corpus check, which now depends on it: the knowledge
    # base is in Postgres, so "is the database up and migrated" has to be settled
    # before anything can ask "is there a corpus".
    if database_enabled():
        await warm(settings)
        # Reachable is not the same as ready. Without this an unmigrated
        # database looks perfectly healthy until the first message of the first
        # conversation, which then 500s on a missing table. Checking here turns
        # a user-facing error into one loud startup log naming the command to
        # run, and persistence simply stays off.
        await check_schema()

    await _require_corpus(settings)

    # The authored curriculum into `modules` and `concepts`. Those tables exist
    # so `mastery.concept_id` has something to reference, and nothing else
    # writes them -- until this ran, every attempt to record what a child had
    # learned violated `mastery_concept_id_fkey`.
    #
    # Idempotent and non-fatal: a curriculum that cannot be seeded means mastery
    # does not record, which is logged as the degradation it is, not a reason to
    # refuse to start and answer nobody's questions.
    if database_enabled():
        from app.curriculum.seed import seed_curriculum

        await seed_curriculum()

    # Build the answer model eagerly so a bad model string or a missing key
    # surfaces at boot rather than in the middle of a child's first question.
    # Cheap: `init_chat_model` validates configuration and opens no connection.
    from app.agent import build_chat_model

    build_chat_model()

    # A missing voice mapping must fail here, not during a demo. Text chat is
    # unaffected either way: VOICE_ENABLED=false skips this entirely.
    if get_voice_settings().voice_enabled:
        validate_registry()
        logger.info("Voice layer enabled.")

    # Verified at boot rather than discovered mid-request. arq and redis-py talk
    # to Valkey unchanged -- it implements the Redis 7.2 command set -- so a
    # failure here is a bad URL or an unreachable host, not an incompatibility.
    if await response_cache.ping():
        logger.info("Valkey reachable; response cache and job queue enabled.")

    yield

    # Closed only when one was ever built: touching the cache here would
    # construct a client just to close it.
    if _probe_client.cache_info().currsize:
        await _probe_client().aclose()
    await dispose_database()


app = FastAPI(
    title="ASPIRE Backend",
    version="0.1.0",
    description="Phase 1 agentic RAG service for the ASPIRE assistant.",
    lifespan=lifespan,
)

# CORS for local development: the Vite dev server on :3000 is a different origin
# from this API on :8000, so the browser preflights every /chat.
#
# The default origin list is those two and nothing else -- it used to be `["*"]`,
# which let any website drive `POST /chat` from a visitor's browser at the
# programme's model cost. Production overrides it with its own origin; see
# `cors_allow_origins` in config.py for why the wildcard is now something a
# deployment has to ask for by name.
#
# allow_credentials stays False. Auth here is a bearer token in a header, not a
# cookie, so nothing needs credentialed cross-origin requests -- and turning it
# on would make the origin list load-bearing in a way it is not today.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


if get_voice_settings().voice_enabled:
    app.include_router(voice_router)

# The game card talks to these directly rather than through the agent: a tapped
# answer must be graded now, not after a model round trip. Same engine, same
# server-side session as the tools, so the two never disagree.
if games_enabled():
    app.include_router(games_router)

# The eligibility card talks to these directly too, and for a second reason
# beyond latency: the answers tapped into it are a minor's, and routing them
# through /chat would put an age band into a prompt, a checkpointer and a
# summary job. This way they reach the engine and nothing else.
if eligibility_enabled():
    app.include_router(eligibility_router)

# The graph, at /v2. Not a second transport any more -- the only one.
#
# `/chat` and `/chat/stream` are gone. They were a single agent behind a single
# system prompt, with no age band, no access matrix, no outbound gate and no
# router; keeping them alongside the graph would have meant a second door into
# the same product with none of those, which is exactly the door that gets left
# open. Everything they did that a reader depends on moved: persistence and the
# response cache to `app/turn.py`, card turns to `app/graph/nodes/cards.py`,
# follow-up chips to the agents that now emit them from what they actually did.
#
# Mounted unconditionally. `GRAPH_ENABLED` is gone with the endpoints it used
# to guard: a flag that can turn off the only chat path is not a safety control,
# it is an outage waiting for somebody to set it.
from app.api.stream import router as graph_router

app.include_router(graph_router)

# The admin portal, at /admin, on this app and behind its OWN auth realm. Same
# process and same database; a completely separate token type that neither door
# will accept from the other -- see app/api/admin/auth.py.
from app.api.admin.router import router as admin_router  # noqa: E402

app.include_router(admin_router)

# Reading a person's own transcripts back. Registered unconditionally: the
# routes answer 503 for themselves when there is no database, which is a
# clearer failure than a 404 that looks like the feature was never built.
app.include_router(conversations_router)
app.include_router(sessions_router)
app.include_router(accounts_router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness, plus whether the data layer actually connected.

    The cache counters live here because the hit rate has to be reported from
    somewhere, and an endpoint that already exists beats a metrics stack this
    service does not have yet.
    """
    return HealthResponse(
        status="ok",
        database=database_enabled(),
        cache=response_cache.cache_enabled(),
        cache_stats=await response_cache.stats(),
    )


@app.get("/debug/timings")
async def debug_timings(last: int | None = None) -> JSONResponse:
    """p50/p95/p99 per stage over the last N turns this process served.

    Gated on `TIMINGS_ENDPOINT_ENABLED`, and 404 rather than 403 when it is off:
    a disabled debug route should not confirm that it exists.

    The ring holds no message text -- durations, a persona, a language and token
    counts -- but how a service is performing is still reconnaissance, so this is
    something a measurement run switches on and switches off again. It is also
    per-process and per-restart by design; see `TimingRing` for why that is a
    feature of a debugging aid and a disqualifying property for a metric.
    """
    if not timings_endpoint_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return JSONResponse(TIMING_RING.summary(last=last))


#: How long a provider reachability check is trusted.
#:
#: The check costs a network round trip, and `/ready` may be polled every few
#: seconds by a load balancer. Sixty seconds is short enough to notice an outage
#: within a minute and long enough that probing cannot itself become traffic.
_PROVIDER_TTL_SECONDS = 60.0
_provider_checked_at = 0.0
_provider_reachable: bool | None = None


def _provider_probe() -> tuple[str, dict[str, str]] | None:
    """Where to knock, for whichever provider `CHAT_MODEL` selects.

    `chat_model` is a `provider:model` string passed to `init_chat_model`, so
    the provider is a configuration choice and this must not assume one. A
    provider it does not recognise, or one with no key, returns None and is
    reported as unknown rather than as broken.
    """
    settings = get_settings()
    provider = settings.chat_model.split(":", 1)[0].lower()

    if provider == "anthropic" and settings.anthropic_api_key:
        return (
            "https://api.anthropic.com/v1/models",
            {
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
        )
    if provider == "openai" and settings.openai_api_key:
        return (
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {settings.openai_api_key}"},
        )
    return None


@lru_cache(maxsize=1)
def _probe_client() -> httpx.AsyncClient:
    """The readiness probe's HTTP client, made once and closed at shutdown.

    `lru_cache` rather than a module global so tests can `cache_clear()` it,
    and so it is only ever constructed on a process that actually probes.
    """
    return httpx.AsyncClient(timeout=5.0)


async def _provider_ready() -> bool | None:
    """Whether the model provider answers. `None` when it cannot be checked.

    Cached, and deliberately not a model call: this asks whether the API is
    reachable and the key is accepted, not whether it will answer a question.
    Spending a completion on every readiness probe would make the probe the
    largest line on the bill.
    """
    global _provider_checked_at, _provider_reachable

    probe = _provider_probe()
    if probe is None:
        return None
    url, headers = probe

    now = time.monotonic()
    if _provider_reachable is not None and now - _provider_checked_at < _PROVIDER_TTL_SECONDS:
        return _provider_reachable

    try:
        # One process-wide client (P14-D): a fresh AsyncClient per probe paid a
        # new TCP + TLS handshake every time, and readiness probes are the one
        # traffic that arrives like clockwork forever.
        response = await _probe_client().get(url, headers=headers)
        # 401 and 403 are answers: the provider is up and the key is wrong,
        # which is a configuration failure and still "not ready".
        _provider_reachable = response.status_code < 400
    except Exception:
        logger.warning("Model provider did not answer a readiness check.", exc_info=True)
        _provider_reachable = False

    _provider_checked_at = now
    return _provider_reachable


@app.get("/ready")
async def ready() -> Response:
    """Whether this process can actually answer a question.

    Split from `/health` because they are different questions and were one.
    `/health` says the process is up; nothing external could distinguish that
    from "able to answer", so a provider outage looked healthy right up until
    every turn 502'd.

    The model provider is the dependency whose failure makes the product
    useless, and it was the one thing nothing checked. It is checked here, on a
    cached reachability probe rather than a completion.

    503 rather than a 200 with a false flag in it: a readiness probe is read by
    a load balancer, and load balancers read status codes.
    """
    database = database_enabled()
    cache = response_cache.cache_enabled()
    provider = await _provider_ready()

    # The cache is deliberately NOT required. It is an optimisation, and a
    # service that refuses traffic because its cache is down is worse than one
    # that answers a little slower.
    ok = database and provider is not False

    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "ready": ok,
            "database": database,
            "cache": cache,
            # `null` means no key is configured, which is a legitimate local
            # setup and not a readiness failure.
            "provider": provider,
        },
    )


# -- the v1 turn pipeline lived here -----------------------------------------
#
# Roughly 830 lines: `/chat`, `/chat/stream`, and the two dozen helpers between
# them. All of it is gone, and the parts a reader depends on moved rather than
# being deleted:
#
#   the conversation write, persistence,
#   the response cache, summarisation      -> app/turn.py
#   card turns without narration           -> app/graph/nodes/cards.py
#   the retrieve-then-answer chain         -> app/agents/qa/ (hybrid + reranked)
#   follow-up chips                        -> the agents' own `quick_replies`
#   the AG-UI envelope and `TurnBuffer`    -> app/graph/stream_interceptor.py
#
# What is NOT here any more, in either place, is the ability to answer a child
# without an age band, an access matrix and an outbound gate.


@app.post("/api/title", response_model=TitleResponse)
async def title(
    request: TitleRequest, principal: Principal = Depends(title_rate_limit)
) -> TitleResponse:
    """Name a conversation from its opening exchange.

    Separate from /chat on purpose. That call streams and is RAG-grounded, and
    asking it to also produce a title risks the title appearing in the answer the
    user is reading. This one is small, non-streaming, and fired once per chat
    after the first reply has landed.

    Never fails in a way the client has to handle: a model error or a
    non-substantive opening message both come back as `title: null`, and the
    client keeps its own fallback.
    """
    generated = await suggest_title(
        request.message, request.answer, request.language
    )
    return TitleResponse(title=generated)
