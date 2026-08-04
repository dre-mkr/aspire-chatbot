"""FastAPI application: /health and /chat."""

from __future__ import annotations

import json
import logging
import time
import uuid
import uuid as uuid_module
from contextlib import asynccontextmanager

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from app import cache as response_cache
from app.agent import get_agent, suggest_follow_ups, suggest_title
from app.config import get_settings
from app.accounts import router as accounts_router
from app.conversations import router as conversations_router
from app.auth import Principal, chat_principal
from app.limits import chat_rate_limit, title_rate_limit
from app.sessions import owner_id_for, router as sessions_router
from app.db import (
    check_schema,
    database_enabled,
    dispose as dispose_database,
    session,
    warm,
)
from app.db.repository import (
    ConversationContext,
    append_turn,
    ensure_conversation,
    load_context,
)
from app.jobs import enqueue_summary
from app.memory import build_prompt, count_tokens, log_prompt_cost
from app.eligibility import eligibility_enabled, eligibility_router
from app.games import games_enabled, games_router
from app.ingest import count_corpus, ingest_if_empty
from app.streaming import agui_stream
from app.timing import (
    RING as TIMING_RING,
    T_AGENT_FIRST_DELTA,
    T_AGENT_FIRST_TOOL,
    T_HISTORY,
    T_IDENTITY,
    T_OPEN_CONVERSATION,
    T_PROMPT_BUILD,
    annotate as annotate_timings,
    begin as begin_timings,
    bind as bind_timings,
    mark_stage,
    record_stage,
    stage as timed_stage,
    timings_endpoint_enabled,
    turn as timed_turn,
)
from app.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    Source,
    StartedEligibilityCheck,
    TitleRequest,
    TitleResponse,
)
from app.voice import get_voice_settings, validate_registry, voice_router

logger = logging.getLogger(__name__)

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

    # Build the agent eagerly so model/config errors surface at boot, not mid-request.
    get_agent()

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
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
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


def _messages_from_this_turn(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Slice off prior conversation history, keeping only the latest exchange.

    The checkpointer returns the full thread, so we walk back to the most recent
    user message and take everything after it.
    """
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index + 1 :]
    return messages


def _extract_sources(messages: list[BaseMessage]) -> list[Source]:
    """Collect the documents the retriever tool actually returned this turn."""
    sources: list[Source] = []
    seen: set[str] = set()

    for message in _messages_from_this_turn(messages):
        if not isinstance(message, ToolMessage):
            continue

        # Set by response_format="content_and_artifact" on the retriever tool.
        documents = message.artifact if isinstance(message.artifact, list) else []
        for document in documents:
            if not isinstance(document, Document):
                continue

            content = document.page_content.strip()
            key = content[:200]
            if key in seen:  # the agent may retrieve twice and overlap
                continue
            seen.add(key)

            truncated = content[:MAX_SOURCE_CHARS]
            if len(content) > MAX_SOURCE_CHARS:
                truncated += "..."
            sources.append(Source(content=truncated, metadata=dict(document.metadata)))

    return sources[:MAX_SOURCES]


def _started_game(messages: list[BaseMessage]) -> dict | None:
    """The game this turn started, or None.

    Read from the tool result rather than from the model's prose, because the
    prose is exactly what we are about to throw away. Scoped to this turn by
    `_messages_from_this_turn`, so a game started ten messages ago does not keep
    reporting itself.

    Only a SUCCESSFUL start counts. A decline renders no card, so that turn is
    an ordinary answer and has to keep its text.
    """
    for message in _messages_from_this_turn(messages):
        if not isinstance(message, ToolMessage) or message.name != "start_game":
            continue

        content = message.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if not isinstance(content, dict) or not content.get("started"):
            continue

        return {
            "game_type": content.get("game"),
            "display_name": content.get("name"),
            "kind": content.get("kind"),
            "total": content.get("total"),
        }
    return None


def _started_eligibility(messages: list[BaseMessage]) -> dict | None:
    """The eligibility check this turn opened, or None.

    Read from the tool result rather than the model's prose, exactly as
    `_started_game` is and for the same reason: the prose is what we are about
    to throw away. Only a SUCCESSFUL start counts -- a decline renders no card,
    so that turn is an ordinary answer and keeps its text.
    """
    for message in _messages_from_this_turn(messages):
        if not isinstance(message, ToolMessage):
            continue
        if message.name != "start_eligibility_check":
            continue

        content = message.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if not isinstance(content, dict) or not content.get("started"):
            continue

        return {"check": content.get("check") or "aspire_eligibility"}
    return None


def message_text(content: Any) -> str:
    """Prose from a message's content, whatever shape the provider used.

    One function because there are two readers -- the whole-turn path and the
    streaming path -- and they disagreed. The streaming path tested
    `isinstance(content, str)` and emitted anything that passed. With this
    provider an assistant message's content is a LIST of typed blocks, so that
    test was false for every chunk of the answer and true for exactly one thing
    per turn: the ToolMessage carrying the retriever's output. The result was a
    stream containing all of the context and none of the answer.

    A shape that is neither a string nor a list of blocks is logged rather than
    stringified. `str()` of a Document or a dict is exactly the kind of thing
    that reads as content and is not, which is how this reached a user.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    logger.warning(
        "Message content is %s, not text or content blocks; dropping it rather "
        "than coercing it to a string.",
        type(content).__name__,
    )
    return ""


def _extract_reply(messages: list[BaseMessage]) -> str:
    """Text of the agent's final message."""
    if not messages:
        return ""
    return message_text(messages[-1].content).strip()


async def _prepare_messages(request: ChatRequest, thread_id: str) -> list[BaseMessage]:
    """The messages for this turn.

    With MEMORY_WINDOW_ENABLED off -- the default -- this is exactly what it has
    always been: the new question alone, with the checkpointer supplying the
    rest. Turning the flag off restores that behaviour completely, which is why
    it is a flag rather than a rewrite.

    With it on, history comes from Postgres instead: a window of recent messages
    plus a running summary of everything older.
    """
    settings = get_settings()
    if not settings.memory_window_enabled:
        # No history to fetch and nothing to assemble: the checkpointer supplies
        # the rest inside the agent. Both stages are recorded as having happened
        # and cost nothing, rather than left absent, because "this deployment
        # does no history work" is a measurement, not a missing one.
        annotate_timings(input_token_count=count_tokens(request.message))
        record_stage(T_HISTORY, 0.0)
        record_stage(T_PROMPT_BUILD, 0.0)
        return [HumanMessage(content=request.message)]

    # The window read: one round trip to Neon for the recent turns and the
    # running summary. Summarisation itself is never here -- it runs in the arq
    # worker, off the request path, which is what makes the window affordable.
    with timed_stage(T_HISTORY):
        context = ConversationContext()
        async with session() as db:
            if db is not None:
                context = await load_context(
                    db, thread_id, window_turns=settings.memory_window_turns
                )

    # Assembly plus the tiktoken pass `build_prompt` does to cost it. Local CPU,
    # no network -- and the encoding is fetched and cached on first use, which is
    # part of why the first turn in a process is slower than the rest.
    with timed_stage(T_PROMPT_BUILD):
        prepared = build_prompt(request.message, context)

    annotate_timings(input_token_count=prepared.tokens)
    log_prompt_cost(thread_id, prepared)
    return prepared.messages


async def _cached_reply(request: ChatRequest) -> ChatResponse | None:
    """Serve a repeat question without a model call, or return None.

    ONLY EVER THE FIRST TURN of a conversation. A question asked mid-thread
    depends on everything said before it, so two identical strings in two
    different conversations are not the same question and must not share an
    answer. That single condition is what makes an exact-match cache safe here.
    """
    if request.thread_id:
        return None

    hit = await response_cache.get_answer(
        request.message,
        language=request.language,
        persona=request.persona,
        account_status=request.account_status,
    )

    if hit is None:
        # A miss used to let every concurrent caller run the full agent --
        # retrieval plus two model calls, each, all computing the same answer.
        # The four landing starter chips are the highest-collision strings in
        # the product, so a classroom tapping one against a cold cache is N
        # simultaneous billed runs.
        #
        # Single-flight: the first caller here takes the lease and returns None
        # to go and compute. The rest wait briefly for its answer.
        key = response_cache.cache_key(
            request.message,
            language=request.language,
            persona=request.persona,
            account_status=request.account_status,
        )
        if not await response_cache.acquire_lease(key):
            hit = await response_cache.await_leader(key)
            if hit is None:
                # The leader was slow, or died. Computing it ourselves is right:
                # this is a cost optimisation, never a correctness gate, and a
                # slower answer beats no answer.
                logger.info("single-flight wait expired; computing anyway")

    await response_cache.record(hit is not None)
    if hit is None:
        return None

    logger.info("cache hit on a first-turn question (language=%s)", request.language)
    return ChatResponse(
        reply=hit["reply"],
        # A fresh thread id even on a hit: the answer is reusable, the
        # conversation it starts is not.
        thread_id=str(uuid.uuid4()),
        sources=[Source(**source) for source in hit.get("sources", [])],
        follow_ups=hit.get("follow_ups", []),
    )


async def _follow_ups_for(
    request: ChatRequest, reply: str, *, quiet_turn: bool
) -> list[str]:
    """The chips under an answer, when they are worth a model call.

    They used to be generated on EVERY non-card turn: a third model call per
    turn, on top of the answer and (once per conversation) the title. Roughly a
    2x multiplier on per-turn model calls for a UI affordance -- and one whose
    value is entirely front-loaded. A reader on turn one does not yet know what
    to ask; by turn twelve they plainly do, because they have been asking.

    So: the opening turn of a conversation only. `request.thread_id is None` is
    exactly that turn and costs nothing to check -- no count, no extra query, on
    a path where the point is to remove work rather than move it.

    `FOLLOW_UPS_ALWAYS=true` restores the old behaviour for anyone who wants to
    measure the difference or disagrees with the trade.

    `quiet_turn` still wins outright. A game or eligibility card is asking a
    question and waiting for a tap; chips underneath it would invite someone out
    of the flow they just started, on the turn they started it.
    """
    if quiet_turn:
        return []
    if request.thread_id is not None and not get_settings().follow_ups_always:
        return []
    return await suggest_follow_ups(request.message, reply)


def _game_history_line(game: dict) -> str:
    """What a game turn leaves in the transcript in place of prose.

    An empty assistant turn would be worse than useless: with the memory window
    on, the model reads its own history back and would find a question followed
    by silence, then wonder why nobody replied. This is a factual note that the
    card was shown -- it never contains the puzzle text or the answer, so
    re-reading history cannot leak either.

    English regardless of the conversation's language, on purpose. It is context
    for the model, not copy for the reader; nothing renders it.
    """
    name = game.get("display_name") or game.get("game_type") or "a game"
    total = game.get("total")
    items = f", {total} items" if total else ""
    return f"[Started the {name} game{items}. The interactive card is on screen.]"


def _eligibility_history_line() -> str:
    """What an eligibility turn leaves in the transcript in place of prose.

    Same job as `_game_history_line`: with the memory window on the model reads
    its own history back, and a question followed by silence reads as a turn
    that never got answered.

    What it deliberately does NOT carry is the flow's outcome or any answer.
    The verdict is not here, the age band is not here, and nothing about
    citizenship, island or school is here. That is not caution for its own sake
    -- this string is written to Postgres inside a transcript that identifies a
    conversation, and the anonymised outcome row exists precisely so that the
    two never sit together.

    What it does carry is enough to stop the model re-asking: the check
    happened, it is on screen, and it already covered those details. English
    regardless of the conversation's language, like the games line -- it is
    context for the model, not copy for a reader, and nothing renders it.
    """
    return (
        "[Opened the ASPIRE eligibility check. The interactive card is on screen "
        "and it asks its own questions, shows the result, the document checklist "
        "and the application steps. I cannot see the answers or the outcome. Do "
        "not re-ask their age, citizenship, parish or school -- the card covered "
        "them -- and do not restate any eligibility rule.]"
    )


#: Matches the client's own truncation, because the two produce the same list.
_TITLE_MAX = 60


def _provisional_title(question: str) -> str:
    """The first question, tidied and truncated.

    The middle rung of the fallback ladder: better than "New chat", worse than a
    generated title, and replaced by one as soon as it arrives.
    """
    clean = " ".join(question.split())
    if not clean:
        return ""
    if len(clean) > _TITLE_MAX:
        return clean[: _TITLE_MAX - 1] + "…"
    return clean


async def _open_conversation(
    request: ChatRequest, thread_id: str, owner_id: uuid_module.UUID | None
) -> None:
    """Create the conversation and record the question, before answering it.

    Deliberately ahead of the agent rather than after it. A first message whose
    answer fails must still leave a conversation behind: the client commits the
    chat the instant it is sent -- it is in the address bar and in the rail --
    and a chat that exists on screen with nothing behind it is a dead end with
    no route out. Recording the question here is what lets that conversation be
    reopened and the question asked again.

    It also happens to be truer. The question *was* received; whether a reply
    could be produced for it is a separate fact.

    Swallows its own failures for the same reason `_persist_turn` does: the user
    is owed an answer, and losing the record of the question is our problem.
    """
    if not database_enabled():
        record_stage(T_OPEN_CONVERSATION, 0.0)
        return

    # On the critical path and ahead of the model, so it is timed: two writes to
    # Neon that the reader waits through before the first token can even start.
    with timed_stage(T_OPEN_CONVERSATION):
        try:
            async with session() as db:
                if db is None:
                    return
                await ensure_conversation(
                    db,
                    thread_id,
                    language=request.language,
                    persona=request.persona,
                    account_status=request.account_status,
                    # Recorded on creation only, so the first turn settles whose
                    # conversation this is and no later request can take it over.
                    owner_id=owner_id,
                    title=_provisional_title(request.message),
                )
                await append_turn(db, thread_id, role="user", content=request.message)
        except Exception:
            logger.warning(
                "Could not open conversation %s; the turn was still served.",
                thread_id,
                exc_info=True,
            )


async def _persist_turn(
    request: ChatRequest,
    thread_id: str,
    *,
    reply: str,
    sources: list[Source],
    follow_ups: list[str],
    game: dict | None = None,
    eligibility: dict | None = None,
    owner_id: uuid_module.UUID | None = None,
) -> None:
    """Write the exchange to Postgres, whole.

    Called after the reply exists and immediately before it is returned, so
    persistence cannot influence what the user is told. Nothing here is read
    back yet -- the model's view of a conversation is unchanged by this step.

    Swallows its own failures on purpose. The user has an answer; losing the
    record of it is a problem for us, not a reason to turn their working
    response into a 500.
    """
    if not database_enabled():
        return

    try:
        async with session() as db:
            if db is None:
                return
            # `_open_conversation` already created the row and recorded the
            # question before the model ran. This is an upsert and a no-op when
            # that succeeded; it stays because that call swallows its own
            # failures, and a turn whose opening write failed should still be
            # persisted rather than silently losing its question.
            await ensure_conversation(
                db,
                thread_id,
                language=request.language,
                persona=request.persona,
                account_status=request.account_status,
                owner_id=owner_id,
                title=_provisional_title(request.message),
            )

            # A game or eligibility turn has no prose by design, so it stores a
            # structured record instead: enough for the model to keep the
            # thread, and enough for counting to have an event to count.
            if game:
                content = _game_history_line(game)
            elif eligibility:
                content = _eligibility_history_line()
            else:
                content = reply

            await append_turn(
                db,
                thread_id,
                role="assistant",
                content=content,
                extra={
                    "sources": [source.model_dump() for source in sources],
                    "follow_ups": follow_ups,
                    "simple_mode": request.simple_mode,
                    **(
                        {
                            "event": "game_started",
                            "game_type": game.get("game_type"),
                            "display_name": game.get("display_name"),
                            "kind": game.get("kind"),
                            "total": game.get("total"),
                        }
                        if game
                        else {}
                    ),
                    # The event and nothing else. No verdict, no criterion, no
                    # answers -- see `_eligibility_history_line`.
                    **({"event": "eligibility_started"} if eligibility else {}),
                },
            )
    except Exception:
        logger.warning(
            "Could not persist the turn for thread %s; the answer was still served.",
            thread_id,
            exc_info=True,
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, principal: Principal | None = Depends(chat_rate_limit)
) -> ChatResponse:
    # Anonymous callers are welcome here and always have been: asking a question
    # has never required identifying yourself. `who` being None simply means the
    # conversation is stored unowned and will not appear in anybody's list.
    # A new thread_id starts a fresh conversation; reuse it to keep context.
    thread_id = request.thread_id or str(uuid.uuid4())

    # Measured on this path too, even though it has no TTFT to report -- there is
    # no first token when the whole reply arrives at once, so `t_ttft` is simply
    # absent here and `t_total` is the number that matters. What this path does
    # have and the streaming one does not is the response cache, which is why
    # `cache_hit` is recorded rather than hardcoded.
    with timed_turn(
        endpoint="/chat", persona=request.persona, lang=request.language
    ):
        with timed_stage(T_IDENTITY):
            who = await owner_id_for(principal)

        cached = await _cached_reply(request)
        if cached is not None:
            annotate_timings(cache_hit=True, output_token_count=count_tokens(cached.reply))
            return cached

        # Before the model, not after: see `_open_conversation`.
        await _open_conversation(request, thread_id, who)

        prepared = await _prepare_messages(request, thread_id)

        return await _serve_chat(request, thread_id, who, prepared)


async def _serve_chat(
    request: ChatRequest,
    thread_id: str,
    who: uuid_module.UUID | None,
    prepared: list[BaseMessage],
) -> ChatResponse:
    """The rest of `/chat`, unchanged, split out only so the turn can wrap it.

    Extracted rather than re-indented so the diff for this phase stays a diff
    about measurement. Nothing below moved relative to anything else below.
    """
    try:
        result = await get_agent(request.simple_mode).ainvoke(
            {"messages": prepared},
            # `configurable` is how per-request context reaches the tools. The
            # agent itself is process-wide and cached, so a tool cannot close
            # over the caller -- it reads thread_id and persona from here. Both
            # are injected by LangChain and stay out of the schema the model
            # sees, so the model can neither read nor forge them.
            config={
                # `language` joins thread_id and persona here so the eligibility
                # card opens in the language the conversation is being held in.
                # Injected the same way and for the same reason: the model can
                # neither read it nor forge it, so it cannot start a French
                # speaker's check in English by deciding to.
                "configurable": {
                    "thread_id": thread_id,
                    "persona": request.persona,
                    "language": request.language,
                }
            },
        )
    except Exception:
        # Log the traceback server-side; return something generic to the client.
        logger.exception("Agent invocation failed for thread %s", thread_id)
        raise HTTPException(
            status_code=502,
            detail="The assistant is temporarily unavailable. Please try again.",
        ) from None

    messages = result.get("messages", [])
    reply = _extract_reply(messages)
    game = _started_game(messages)
    eligibility = _started_eligibility(messages)

    if eligibility is not None:
        # Same rule as a game turn, for a sharper reason. The card is about to
        # give an audited, personalised answer to "am I eligible"; anything the
        # model says in the same turn is a second answer to that question with
        # none of the auditing. Dropped HERE rather than hidden in the client,
        # so it never crosses the wire, never reaches history and never reaches
        # the chip generator.
        #
        # The prompt asks for silence and usually gets it. This is the half that
        # does not depend on the model complying.
        if reply:
            logger.info(
                "Dropping %d characters of narration from an eligibility turn.",
                len(reply),
            )
        reply = ""
    elif game is not None:
        # The card is the answer. Anything the model said alongside it restates
        # the puzzle it is already showing, so it is dropped HERE rather than
        # hidden in the client -- the prose then never crosses the wire, never
        # reaches history, and never reaches the chip generator.
        #
        # The prompt asks for silence and usually gets it; this is the half that
        # does not depend on the model complying.
        if reply:
            logger.info(
                "Dropping %d characters of narration from a game-start turn.",
                len(reply),
            )
        reply = ""
    elif not reply:
        logger.error("Agent produced an empty reply for thread %s", thread_id)
        raise HTTPException(status_code=502, detail="The assistant returned an empty response.")

    sources = _extract_sources(messages)
    annotate_timings(output_token_count=count_tokens(reply) if reply else 0)

    # No chips on a game turn, and the reason is not tidiness.
    #
    # `suggest_follow_ups` never had access to game state -- it sees only the
    # question and the reply. It was giving the puzzle away because the reply
    # CONTAINED the puzzle: handed "Unscramble these letters: NOEYM" it simply
    # solved it and suggested "Is the answer MONEY?".
    #
    # So the input is cut rather than the output filtered: on a game turn the
    # call is not made at all. Filtering its suggestions would leave the model
    # still being shown the scramble, one prompt change away from leaking it
    # again.
    #
    # An eligibility turn is suppressed for a different reason: the card is
    # asking a question and waiting for a tap, and chips underneath it offering
    # "Am I eligible?" would be inviting someone out of the flow they just
    # started, on the very turn they started it.
    quiet_turn = game is not None or eligibility is not None
    # See `record_turn` in app/cache.py: how often a card actually starts is the
    # number P8-003 needs before the 979 tokens of card instructions can be
    # shortened or moved behind a router turn. Recorded on both transports.
    await response_cache.record_turn(quiet_turn)
    follow_ups = await _follow_ups_for(request, reply, quiet_turn=quiet_turn)

    await _persist_turn(
        request,
        thread_id,
        reply=reply,
        sources=sources,
        follow_ups=follow_ups,
        game=game,
        eligibility=eligibility,
        owner_id=who,
    )

    # Once the conversation has outgrown its window, the turns that fell out
    # need folding into the summary. Enqueued, never awaited: compression costs
    # a model call, and paying for it here would just move the latency.
    settings = get_settings()
    if settings.memory_window_enabled and database_enabled():
        await enqueue_summary(thread_id)

    # Only the opening turn is cacheable -- see `_cached_reply` -- and never a
    # game or eligibility turn: both create server-side session state, so
    # replaying a cached "answer" would render a card for a flow nobody started.
    #
    # This matters more for eligibility than for games, because "Who is eligible
    # for ASPIRE?" is a landing-page starter chip and therefore the most
    # cacheable string in the product. Caching that turn would serve every later
    # asker an empty reply with no card at all.
    if not request.thread_id:
        key = response_cache.cache_key(
            request.message,
            language=request.language,
            persona=request.persona,
            account_status=request.account_status,
        )
        if quiet_turn is False:
            await response_cache.put_answer(
                request.message,
                {
                    "reply": reply,
                    "sources": [source.model_dump() for source in sources],
                    "follow_ups": follow_ups,
                },
                language=request.language,
                persona=request.persona,
                account_status=request.account_status,
            )
        # Released whether or not anything was cached. A card turn is not
        # cacheable, but callers waiting on the lease must still be let go
        # rather than sitting out the full wait for an answer that is never
        # coming. The lease also expires on its own, so a crash costs the next
        # caller a lease's worth of waiting and nothing more.
        await response_cache.release_lease(key)

    return ChatResponse(
        reply=reply,
        thread_id=thread_id,
        sources=sources,
        follow_ups=follow_ups,
        game_started=game,
        eligibility_started=(
            StartedEligibilityCheck(check=eligibility["check"], language=request.language)
            if eligibility
            else None
        ),
    )


def _chat_request_from(body: dict) -> ChatRequest:
    """Reads a `ChatRequest` out of whatever shape the caller sent.

    AG-UI clients wrap application fields in `forwardedProps` and put their own
    correlation ids at the top level; a direct caller (curl, a test, the
    fallback path) sends the flat object `/chat` takes. Both are accepted, with
    `forwardedProps` winning, so the endpoint is usable without pulling a
    client library in to talk to it.
    """
    forwarded = body.get("forwardedProps")
    merged = {**body, **(forwarded if isinstance(forwarded, dict) else {})}
    return ChatRequest.model_validate(merged)


@app.post("/chat/stream")
async def chat_stream(
    body: dict, principal: Principal | None = Depends(chat_rate_limit)
) -> StreamingResponse:
    """The same turn as `/chat`, delivered as AG-UI server-sent events.

    Additive. `/chat` is unchanged and remains the fallback -- a client that
    cannot stream, or a caller that would rather have one JSON object, still
    gets exactly what it always did.

    The post-processing is deliberately identical to `/chat`'s, and shares its
    helpers rather than reimplementing them: the same reply extraction, the same
    dropping of prose on a card turn, the same sources, the same follow-ups, the
    same persistence. Two code paths that answer the same question differently
    is how the streaming version quietly becomes a second product.
    """
    request = _chat_request_from(body)
    thread_id = request.thread_id or str(uuid.uuid4())

    # The clock starts here, before the identity round trip, because "request
    # received" is what TTFT is measured from and `owner_id_for` is already part
    # of what the reader is waiting through.
    timings = begin_timings(
        endpoint="/chat/stream", persona=request.persona, lang=request.language
    )
    # Bound here as well as inside `run()`: this await happens before the
    # generator is ever driven, so without it `t_identity` would have no turn to
    # attach to and would land in the derived model-call figure instead.
    with bind_timings(timings, finish_on_exit=False):
        with timed_stage(T_IDENTITY):
            who = await owner_id_for(principal)

    async def run() -> AsyncIterator[dict]:
        """Publishes the turn's timings for everything below, including the agent.

        The bind lives out here rather than inside `_run` so that it covers the
        whole stream: the retriever and the embedding call happen several frames
        down inside langgraph, and a ContextVar is the only way they can find the
        turn they belong to. Closing it here is also what emits the line, which
        is why it wraps the iteration rather than preceding it.
        """
        with bind_timings(timings):
            async for event in _run():
                yield event

    async def _run() -> AsyncIterator[dict]:
        # Recorded before the model runs, exactly as `/chat` does, so a turn
        # that fails still leaves a conversation that can be reopened.
        await _open_conversation(request, thread_id, who)
        prepared = await _prepare_messages(request, thread_id)

        collected: list[BaseMessage] = []
        #: The answer as it was actually sent, for persistence and the done
        #: payload. `_extract_reply` reads the LAST element, which on this path
        #: is a single chunk rather than a whole message — so the turn was being
        #: persisted, and announced, with an empty reply.
        streamed: list[str] = []
        last_message_id: str | None = None
        try:
            async for chunk, _meta in get_agent(request.simple_mode).astream(
                {"messages": prepared},
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "persona": request.persona,
                        "language": request.language,
                    }
                },
                stream_mode="messages",
            ):
                collected.append(chunk)

                # Message boundaries, so the buffer knows when a tool-calling
                # message has ended and the answer has begun. Without them every
                # delta after the first tool call still looks like part of the
                # message that requested it, and nothing is ever released.
                chunk_id = getattr(chunk, "id", None)
                if chunk_id is not None and chunk_id != last_message_id:
                    last_message_id = chunk_id
                    yield {"message": chunk_id}

                # A tool call names what kind of turn this is. Forwarded first so
                # the buffer can silence a card turn before any of its prose is
                # released.
                for call in getattr(chunk, "tool_call_chunks", None) or []:
                    # The first tool call is the end of model call #1, and that
                    # call is the single largest thing standing between the
                    # request and the first visible token -- nothing can be
                    # released before a tool has run (see app/streaming.py).
                    mark_stage(T_AGENT_FIRST_TOOL)
                    yield {"tool": call.get("name")}
                for call in getattr(chunk, "tool_calls", None) or []:
                    mark_stage(T_AGENT_FIRST_TOOL)
                    yield {"tool": call.get("name")}

                # A tool's OUTPUT is never the assistant speaking. It is kept in
                # `collected` because that is where sources come from, and it is
                # not a delta: streaming it put the retrieved knowledge-base rows
                # on screen in place of the answer, whole, in one frame.
                if isinstance(chunk, ToolMessage):
                    continue

                text = message_text(getattr(chunk, "content", ""))
                if text:
                    # The model has produced text. Whether the *reader* sees it
                    # yet is `TurnBuffer`'s decision, and t_ttft is stamped there;
                    # the gap between the two is what the suppression rule costs.
                    mark_stage(T_AGENT_FIRST_DELTA)
                    streamed.append(text)
                    yield {"delta": text}
        except Exception:
            logger.exception("Agent stream failed for thread %s", thread_id)
            yield {"error": "The assistant is temporarily unavailable. Please try again."}
            return

        # Everything the reader's screen needs is derivable from `collected`
        # right now, without another round trip anywhere. Computed before the
        # turn is announced so that announcing it costs nothing.
        game = _started_game(collected)
        eligibility = _started_eligibility(collected)
        reply = "".join(streamed).strip() or _extract_reply(collected)
        # The card is the whole turn; anything said beside it is dropped here,
        # for the same reasons set out in `/chat`.
        if game is not None or eligibility is not None:
            reply = ""

        sources = _extract_sources(collected)
        quiet_turn = game is not None or eligibility is not None

        # Counted with the same encoder the memory window uses, so the number in
        # a timing line and the number in a prompt-cost line mean the same thing.
        annotate_timings(output_token_count=count_tokens(reply) if reply else 0)

        # The prose is complete here, and nothing below this line is prose.
        yield {"text_end": True}

        # The turn, as soon as it is known -- and crucially before the two slow
        # things left to do. Follow-ups are a second model call and persistence
        # is a database round trip; together they measured two to five seconds,
        # and the client cannot settle a turn until this event arrives. So the
        # answer sat finished on screen with no sources, no actions and no
        # chips, waiting on work that none of them depend on.
        #
        # Follow-ups are the one thing here that genuinely is not ready yet, so
        # they are sent on their own once they are.
        yield {
            "done": {
                "reply": reply,
                "thread_id": thread_id,
                "sources": [source.model_dump() for source in sources],
                "follow_ups": [],
                "game_started": game,
                "eligibility_started": (
                    {"check": eligibility["check"], "language": request.language}
                    if eligibility
                    else None
                ),
            }
        }

        await response_cache.record_turn(quiet_turn)
        follow_ups = await _follow_ups_for(request, reply, quiet_turn=quiet_turn)

        # Past this point the reader already has the answer, so nothing here may
        # take it away. Persistence failing is a real fault and is logged as one,
        # but it is not a reason to replace a correct answer on screen with an
        # error -- which is what letting it raise would now do.
        try:
            await _persist_turn(
                request,
                thread_id,
                reply=reply,
                sources=sources,
                follow_ups=follow_ups,
                game=game,
                eligibility=eligibility,
                owner_id=who,
            )

            settings = get_settings()
            if settings.memory_window_enabled and database_enabled():
                await enqueue_summary(thread_id)
        except Exception:
            logger.exception("Persisting the turn failed for thread %s", thread_id)

        yield {"follow_ups": follow_ups}

    return StreamingResponse(
        agui_stream(thread_id=thread_id, run_events=run(), timings=timings),
        media_type="text/event-stream",
        headers={
            # Long-lived response through a proxy: without this nginx buffers the
            # whole thing and delivers it at once, which is the one outcome that
            # makes streaming pointless.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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
