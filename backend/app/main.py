"""FastAPI application: health, readiness, titles, and the routers."""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response
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

# psycopg's async mode cannot run on Windows' default ProactorEventLoop, and the checkpointer is psycopg.
if sys.platform == "win32":  # pragma: no cover - platform-specific
    from app.graph.checkpointer import install_windows_event_loop_policy

    if install_windows_event_loop_policy():
        logger.debug("Selector event loop installed so psycopg can connect.")

# Cap what we echo back so a long knowledge-base row can't bloat the response.
MAX_SOURCES = 6
MAX_SOURCE_CHARS = 600


async def _require_corpus(settings) -> None:
    """Refuse to start without a knowledge base."""
    if not database_enabled():
        raise RuntimeError(
            "The knowledge base lives in Postgres and the database is not "
            "available, so there is nothing to retrieve from. Set DATABASE_URL "
            "and run, from the backend directory:\n"
            "    alembic upgrade head\n"
            "    python -m app.ingest"
        )

    # Auto-ingest on a cold start so a fresh deployment is usable out of the box, exactly as it was before the move…
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

    # Third-party HTTP clients are capped at INFO however loud this service is told to be, and that is a privacy co…
    for noisy in ("openai", "httpx", "httpcore", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(max(logging.INFO, logging.getLogger().level))

    # Neon scales to zero, so without this the first message after an idle period pays the wake-up.
    if database_enabled():
        await warm(settings)
        # Reachable is not the same as ready.
        await check_schema()

    await _require_corpus(settings)

    # The authored curriculum into `modules` and `concepts`.
    if database_enabled():
        from app.curriculum.seed import seed_curriculum

        await seed_curriculum()

    # The teaching concepts into memory, so the tutor can resolve a topic.
    if database_enabled():
        from app.learning.concepts import get_store

        await get_store().reload()

    # Refuse to start without a usable signing key.
    from app.auth import _secret

    _secret()

    # Build the answer model eagerly so a bad model string or a missing key surfaces at boot rather than in the mid…
    from app.agent import build_chat_model

    build_chat_model()

    # A missing voice mapping must fail here, not during a demo.
    if get_voice_settings().voice_enabled:
        validate_registry()
        logger.info("Voice layer enabled.")

    # Verified at boot rather than discovered mid-request.
    if await response_cache.ping():
        logger.info("Valkey reachable; response cache and job queue enabled.")

    yield

    # Closed only when one was ever built: touching the cache here would construct a client just to close it.
    if _probe_client.cache_info().currsize:
        await _probe_client().aclose()
    await dispose_database()


app = FastAPI(
    title="ASPIRE Backend",
    version="0.1.0",
    description="Phase 1 agentic RAG service for the ASPIRE assistant.",
    lifespan=lifespan,
)

# CORS for local development: the Vite dev server on :3000 is a different origin from this API on :8000, so the…
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


if get_voice_settings().voice_enabled:
    app.include_router(voice_router)

# The game card talks to these directly rather than through the agent: a tapped answer must be graded now, not…
if games_enabled():
    app.include_router(games_router)

# The eligibility card talks to these directly too, and for a second reason beyond latency: the answers tapped…
if eligibility_enabled():
    app.include_router(eligibility_router)

# The graph, at /v2.
from app.api.stream import router as graph_router

app.include_router(graph_router)

# The admin portal, at /admin, on this app and behind its OWN auth realm.
from app.api.admin.router import router as admin_router  # noqa: E402

app.include_router(admin_router)

# Reading a person's own transcripts back.
app.include_router(conversations_router)
app.include_router(sessions_router)
app.include_router(accounts_router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness, plus whether the data layer actually connected."""
    return HealthResponse(
        status="ok",
        database=database_enabled(),
        cache=response_cache.cache_enabled(),
        cache_stats=await response_cache.stats(),
    )


@app.get("/debug/timings")
async def debug_timings(last: int | None = None) -> JSONResponse:
    """p50/p95/p99 per stage over the last N turns this process served."""
    if not timings_endpoint_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return JSONResponse(TIMING_RING.summary(last=last))


#: How long a provider reachability check is trusted.
_PROVIDER_TTL_SECONDS = 60.0
_provider_checked_at = 0.0
_provider_reachable: bool | None = None


def _provider_probe() -> tuple[str, dict[str, str]] | None:
    """Where to knock, for whichever provider `CHAT_MODEL` selects."""
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
    """The readiness probe's HTTP client, made once and closed at shutdown."""
    return httpx.AsyncClient(timeout=5.0)


async def _provider_ready() -> bool | None:
    """Whether the model provider answers."""
    global _provider_checked_at, _provider_reachable

    probe = _provider_probe()
    if probe is None:
        return None
    url, headers = probe

    now = time.monotonic()
    if _provider_reachable is not None and now - _provider_checked_at < _PROVIDER_TTL_SECONDS:
        return _provider_reachable

    try:
        # One process-wide client (P14-D): a fresh AsyncClient per probe paid a new TCP + TLS handshake every time, and…
        response = await _probe_client().get(url, headers=headers)
        # 401 and 403 are answers: the provider is up and the key is wrong, which is a configuration failure and still…
        _provider_reachable = response.status_code < 400
    except Exception:
        logger.warning("Model provider did not answer a readiness check.", exc_info=True)
        _provider_reachable = False

    _provider_checked_at = now
    return _provider_reachable


@app.get("/ready")
async def ready() -> Response:
    """Whether this process can actually answer a question."""
    database = database_enabled()
    cache = response_cache.cache_enabled()
    provider = await _provider_ready()

    # The cache is deliberately NOT required.
    ok = database and provider is not False

    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "ready": ok,
            "database": database,
            "cache": cache,
            # `null` means no key is configured, which is a legitimate local setup and not a readiness failure.
            "provider": provider,
        },
    )


# -- the v1 turn pipeline lived here ----------------------------------------- Roughly 830 lines: `/chat`, `/ch…


@app.post("/api/title", response_model=TitleResponse)
async def title(
    request: TitleRequest, principal: Principal = Depends(title_rate_limit)
) -> TitleResponse:
    """Name a conversation from its opening exchange."""
    generated = await suggest_title(
        request.message, request.answer, request.language
    )
    return TitleResponse(title=generated)
