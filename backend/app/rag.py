"""Embeddings, and retrieval over the `documents` table in Neon."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from functools import lru_cache
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document as LangchainDocument
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import session
from app.db.models import Document
from app.prompts import KNOWLEDGE_CONTEXT_EMPTY
from app.timing import (
    T_EMBED,
    T_RETRIEVE_TOTAL,
    annotate,
    record_stage,
)

logger = logging.getLogger(__name__)


class FastEmbedEmbeddings(Embeddings):
    """LangChain Embeddings backed by fastembed's local ONNX models."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None  # loaded lazily: the first use downloads the ONNX weights

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            logger.info("Loading embedding model %s (first run downloads weights)", self.model_name)
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self.model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # query_embed applies the model's query prefix, which BGE-style models are trained with.
        return next(iter(self.model.query_embed(text))).tolist()


class TimedEmbeddings(Embeddings):
    """Delegates to a real embeddings backend and times `embed_query`."""

    def __init__(self, inner: Embeddings) -> None:
        self.inner = inner

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        start = time.perf_counter()
        try:
            return self.inner.embed_query(text)
        finally:
            record_stage(T_EMBED, (time.perf_counter() - start) * 1000.0)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.inner.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        start = time.perf_counter()
        try:
            return await self.inner.aembed_query(text)
        finally:
            record_stage(T_EMBED, (time.perf_counter() - start) * 1000.0)


def build_embeddings(settings: Settings | None = None) -> Embeddings:
    """Construct the configured embeddings backend. The one place to extend."""
    settings = settings or get_settings()

    if settings.embeddings_provider == "openai":
        # Reads OPENAI_API_KEY from the environment, same as the chat model.
        from langchain_openai import OpenAIEmbeddings

        return TimedEmbeddings(OpenAIEmbeddings(model=settings.embeddings_model))

    if settings.embeddings_provider == "fastembed":
        return TimedEmbeddings(FastEmbedEmbeddings(settings.embeddings_model))

    raise ValueError(f"Unsupported embeddings_provider: {settings.embeddings_provider!r}")


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Process-wide embeddings, so a local model is loaded only once."""
    return build_embeddings()


def chroma_floor_as_cosine_distance(threshold: float) -> float | None:
    """Translate the old Chroma relevance floor into a cosine-distance cutoff."""
    if threshold <= 0:
        return None
    return (1.0 - threshold) / math.sqrt(2.0)


#: One loop for every synchronous retrieval in this process, created on demand.
_sync_loop: asyncio.AbstractEventLoop | None = None


def _run_sync(coro):
    """Drive a coroutine from sync code on this process's bridging loop."""
    global _sync_loop

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        # Deadlock, not slowness, so it is named rather than attempted.
        coro.close()
        raise RuntimeError(
            "Synchronous retrieval was called from inside a running event loop. "
            "Use `await retriever.ainvoke(...)` there."
        )

    if _sync_loop is None or _sync_loop.is_closed():
        _sync_loop = asyncio.new_event_loop()
    return _sync_loop.run_until_complete(coro)


class PgVectorRetriever(BaseRetriever):
    """Top-k nearest chunks from `documents`, by cosine distance."""

    embeddings: Embeddings
    #: Mutable so the eval sweep can vary k without rebuilding the retriever.
    k: int = 4
    #: None disables the relevance floor entirely.
    max_cosine_distance: float | None = None

    def _statement(self, vector: list[float]):
        distance = Document.embedding.cosine_distance(vector)
        statement = select(Document.content, Document.metadata_)
        if self.max_cosine_distance is not None:
            statement = statement.where(distance <= self.max_cosine_distance)
        return statement.order_by(distance).limit(self.k)

    def _scored_statement(self, vector: list[float]):
        """`_statement`, plus the distance itself as a third column."""
        distance = Document.embedding.cosine_distance(vector)
        statement = select(Document.content, Document.metadata_, distance.label("distance"))
        if self.max_cosine_distance is not None:
            statement = statement.where(distance <= self.max_cosine_distance)
        return statement.order_by(distance).limit(self.k)

    async def asearch_with_scores(
        self, vector: list[float]
    ) -> list[tuple[LangchainDocument, float]]:
        """Chunks with their cosine RELEVANCE, 1.0 being identical."""
        async with session() as db:
            if db is None:
                raise RuntimeError(
                    "No database configured, so there is no corpus to search. "
                    "Postgres is the source of truth for the knowledge base."
                )
            rows = (await db.execute(self._scored_statement(vector))).all()

        return [
            (
                LangchainDocument(page_content=content, metadata=dict(metadata or {})),
                max(0.0, 1.0 - float(distance)),
            )
            for content, metadata, distance in rows
        ]

    async def asearch_by_vector(self, vector: list[float]) -> list[LangchainDocument]:
        """The database half of a search, for callers that already embedded."""
        async with session() as db:
            if db is None:
                # Loud rather than empty.
                raise RuntimeError(
                    "No database configured, so there is no corpus to search. "
                    "Postgres is the source of truth for the knowledge base."
                )
            rows = (await db.execute(self._statement(vector))).all()

        # `metadata` is returned as stored, so a source keeps the shape it had under Chroma.
        return [
            LangchainDocument(page_content=content, metadata=dict(metadata or {}))
            for content, metadata in rows
        ]

    async def _search(self, query: str) -> list[LangchainDocument]:
        vector = await self.embeddings.aembed_query(query)
        return await self.asearch_by_vector(vector)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun, **kwargs: Any
    ) -> list[LangchainDocument]:
        return await self._search(query)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun, **kwargs: Any
    ) -> list[LangchainDocument]:
        """Synchronous bridge, for the eval harness and the CLI."""
        return _run_sync(self._search(query))


class TimedRetriever(BaseRetriever):
    """Times the whole retrieval call and counts what came back."""

    inner: BaseRetriever

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun, **kwargs: Any
    ) -> list[LangchainDocument]:
        start = time.perf_counter()
        try:
            documents = self.inner.invoke(query)
        finally:
            record_stage(T_RETRIEVE_TOTAL, (time.perf_counter() - start) * 1000.0)
        annotate(retrieved_chunk_count=len(documents))
        return documents

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun, **kwargs: Any
    ) -> list[LangchainDocument]:
        start = time.perf_counter()
        try:
            documents = await self.inner.ainvoke(query)
        finally:
            record_stage(T_RETRIEVE_TOTAL, (time.perf_counter() - start) * 1000.0)
        annotate(retrieved_chunk_count=len(documents))
        return documents


#: How retrieved chunks are joined into one block of prompt text.
CONTEXT_SEPARATOR = "\n\n"


def format_context(documents: list[LangchainDocument]) -> str:
    """The retrieved chunks as the model used to receive them from the tool."""
    return CONTEXT_SEPARATOR.join(document.page_content for document in documents)


def context_from(documents: list[LangchainDocument]) -> str:
    """The knowledge block for a prompt, including when nothing was retrieved."""
    return format_context(documents) if documents else KNOWLEDGE_CONTEXT_EMPTY


def build_retriever(settings: Settings | None = None) -> BaseRetriever:
    """The retriever, with a floor on how irrelevant a chunk may be."""
    settings = settings or get_settings()

    inner = PgVectorRetriever(
        embeddings=get_embeddings(),
        k=settings.retriever_k,
        max_cosine_distance=chroma_floor_as_cosine_distance(
            settings.retriever_score_threshold
        ),
    )
    # Timing only.
    return TimedRetriever(inner=inner)


@lru_cache(maxsize=1)
def get_retriever() -> BaseRetriever:
    """Process-wide retriever."""
    return build_retriever()


async def embed_query_cached(text: str) -> list[float]:
    """This query's embedding, served from Valkey when it has been asked before."""
    from app import cache as response_cache

    model = get_settings().embeddings_model
    start = time.perf_counter()
    cached = await response_cache.get_embedding(text, model)
    if cached is not None:
        record_stage(T_EMBED, (time.perf_counter() - start) * 1000.0)
        annotate(embed_cache_hit=True)
        return cached

    # TimedEmbeddings records T_EMBED around the real call.
    vector = await get_embeddings().aembed_query(text)
    await response_cache.put_embedding(text, model, vector)
    return vector


