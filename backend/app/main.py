"""FastAPI application: /health and /chat."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from app.agent import get_agent, suggest_follow_ups
from app.config import get_settings
from app.ingest import ingest_if_empty
from app.rag import count_documents, get_vector_store
from app.schemas import ChatRequest, ChatResponse, HealthResponse, Source
from app.voice import get_voice_settings, validate_registry, voice_router

logger = logging.getLogger(__name__)

# Cap what we echo back so a long knowledge-base row can't bloat the response.
MAX_SOURCES = 6
MAX_SOURCE_CHARS = 600


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare the vector store and agent before the first request."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Auto-ingest on a cold start so the service is usable out of the box.
    ingest_if_empty(settings)
    logger.info("Vector store holds %d chunks.", count_documents(get_vector_store()))

    # Build the agent eagerly so model/config errors surface at boot, not mid-request.
    get_agent()

    # A missing voice mapping must fail here, not during a demo. Text chat is
    # unaffected either way: VOICE_ENABLED=false skips this entirely.
    if get_voice_settings().voice_enabled:
        validate_registry()
        logger.info("Voice layer enabled.")

    yield


app = FastAPI(
    title="ASPIRE Backend",
    version="0.1.0",
    description="Phase 1 agentic RAG service for the ASPIRE assistant.",
    lifespan=lifespan,
)

# Permissive CORS for local development: the Vite dev server on :3000 is a
# different origin from this API on :8000, so the browser preflights every /chat.
# TODO: before deploying, restrict allow_origins to the real frontend origin(s).
#
# allow_credentials stays False because the default origin list is "*", and a
# wildcard is not a legal Access-Control-Allow-Origin for a credentialed request.
# Phase 1 has no cookies or auth, so nothing needs it. Turn it on only alongside
# an explicit origin list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


if get_voice_settings().voice_enabled:
    app.include_router(voice_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


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


def _extract_reply(messages: list[BaseMessage]) -> str:
    """Text of the agent's final message."""
    if not messages:
        return ""

    content = messages[-1].content
    if isinstance(content, str):
        return content.strip()

    # Some providers return content as a list of typed blocks.
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts).strip()


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    # A new thread_id starts a fresh conversation; reuse it to keep context.
    thread_id = request.thread_id or str(uuid.uuid4())

    try:
        result = await get_agent(request.simple_mode).ainvoke(
            {"messages": [HumanMessage(content=request.message)]},
            config={"configurable": {"thread_id": thread_id}},
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
    if not reply:
        logger.error("Agent produced an empty reply for thread %s", thread_id)
        raise HTTPException(status_code=502, detail="The assistant returned an empty response.")

    return ChatResponse(
        reply=reply,
        thread_id=thread_id,
        sources=_extract_sources(messages),
        follow_ups=await suggest_follow_ups(request.message, reply),
    )
