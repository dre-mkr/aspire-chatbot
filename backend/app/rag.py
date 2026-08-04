"""Embeddings, and retrieval over the `documents` table in Neon.

`build_embeddings` is the single switch point for the embeddings backend: add a
branch there (and a value to Settings.embeddings_provider) to move provider
without touching ingestion, the agent, or the API.

`build_retriever` is the single switch point for retrieval. As of P13-002 it
searches Postgres with pgvector, and Postgres is the source of truth for the
corpus. It previously searched a local Chroma store; see
`chroma_floor_as_cosine_distance` for the one piece of that implementation that
had to be carried across exactly rather than reimplemented.
"""

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
from app.timing import (
    T_EMBED,
    T_RETRIEVE_TOTAL,
    annotate,
    record_stage,
)

logger = logging.getLogger(__name__)


class FastEmbedEmbeddings(Embeddings):
    """LangChain Embeddings backed by fastembed's local ONNX models.

    Used instead of langchain-community's wrapper because that package now pulls
    in langchain-classic (the deprecated pre-1.0 chain APIs) as a dependency.
    fastembed's own surface is small and stable, so wrapping it directly keeps
    the dependency tree clean.
    """

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
        # query_embed applies the model's query prefix where one is expected
        # (BGE models are trained with an asymmetric query/passage prompt).
        return next(iter(self.model.query_embed(text))).tolist()


class TimedEmbeddings(Embeddings):
    """Delegates to a real embeddings backend and times `embed_query`.

    Only the query side is timed. `embed_documents` runs at ingest, which is not
    a request and is not what the latency workstream is measuring.

    Wrapping rather than editing each backend is what keeps the measurement
    honest across a provider switch: `EMBEDDINGS_PROVIDER=openai` is a network
    round trip and `fastembed` is local ONNX inference, and `t_embed` has to mean
    the same thing -- "what embedding this query cost" -- in both cases.
    """

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
    """Translate the old Chroma relevance floor into a cosine-distance cutoff.

    This function is the whole reason the retrieval floor survived the move off
    Chroma unchanged, so it is worth being explicit about the arithmetic.

    `RETRIEVER_SCORE_THRESHOLD` was written against Chroma's
    `similarity_score_threshold`, which keeps a chunk when
    `relevance >= threshold`. What Chroma computed for `relevance` was NOT cosine
    similarity, despite what the comment in `config.py` used to say:

      * the collection was created with the DEFAULT distance metric, `l2` --
        `build_vector_store` never passed a `collection_configuration`, so the
        cosine setting nobody wrote was never in effect;
      * Chroma's `l2` space returns the SQUARED euclidean distance;
      * so the relevance function selected was `_euclidean_relevance_score_fn`,
        which is `1 - distance / sqrt(2)`.

    Measured against the live collection to confirm rather than assume: for the
    query "What is ASPIRE Day?" Chroma reported 0.49243456, and the same pair of
    vectors gives `2 - 2*cos_sim = 0.49244264`. Squared L2, as expected.

    The embeddings are unit vectors (measured: norms within 4e-4 of 1.0), so
    `L2^2 = 2 * (1 - cos_sim) = 2 * cos_dist`, and the keep condition unrolls:

        1 - (2 * cos_dist) / sqrt(2)  >=  threshold
        cos_dist                      <=  (1 - threshold) / sqrt(2)

    At the configured 0.2 that is `cos_dist <= 0.565685`, i.e. cosine similarity
    >= 0.434315. `tests/test_retriever_equivalence.py` checks the consequence
    end to end rather than trusting this derivation.

    Returns None when the floor is switched off, which `RETRIEVER_SCORE_THRESHOLD=0`
    has always meant.
    """
    if threshold <= 0:
        return None
    return (1.0 - threshold) / math.sqrt(2.0)


#: One loop for every synchronous retrieval in this process, created on demand.
#:
#: `asyncio.run` per call does NOT work here and the failure is not obvious: it
#: opens a fresh loop and closes it on the way out, while the SQLAlchemy engine is
#: process-wide and its pooled asyncpg connections stay bound to whichever loop
#: first created them. The second call then reaches for a socket whose loop is
#: gone and dies with "Event loop is closed" -- which is exactly what
#: `evals/run.py` hit on its second question.
#:
#: Reusing one loop keeps the pool valid across calls. The consequence worth
#: knowing: a single process should retrieve either synchronously or
#: asynchronously, not both. Nothing does -- the server is async throughout and
#: the eval harness and CLI are sync throughout.
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
    """Top-k nearest chunks from `documents`, by cosine distance.

    Deliberately NOT filtered by language. The corpus is English-only and
    `evals/golden.yaml` is built on exactly that: every Spanish and French probe
    question has to match an English chunk, so cross-lingual matching is the
    design rather than an oversight. Adding `WHERE language = :lang` here would
    silently return nothing for two of the three supported languages.

    There is no vector index and that is intentional -- see migration 0009. At
    332 rows a sequential scan is exact and costs single-digit milliseconds,
    while an HNSW index over `halfvec(3072)` would be approximate twice over.
    """

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

    async def _search(self, query: str) -> list[LangchainDocument]:
        vector = await self.embeddings.aembed_query(query)

        async with session() as db:
            if db is None:
                # Loud rather than empty. An empty result set is indistinguishable
                # from "nothing matched", which would turn a misconfigured
                # deployment into a service that confidently answers nothing.
                raise RuntimeError(
                    "No database configured, so there is no corpus to search. "
                    "Postgres is the source of truth for the knowledge base."
                )
            rows = (await db.execute(self._statement(vector))).all()

        # `metadata` is returned as stored, so a source on the wire has exactly
        # the shape it had under Chroma.
        return [
            LangchainDocument(page_content=content, metadata=dict(metadata or {}))
            for content, metadata in rows
        ]

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun, **kwargs: Any
    ) -> list[LangchainDocument]:
        return await self._search(query)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun, **kwargs: Any
    ) -> list[LangchainDocument]:
        """Synchronous bridge, for the eval harness and the CLI.

        The request path is async and never lands here. This exists because
        `evals/run.py` calls `retriever.invoke(...)` from sync code.
        """
        return _run_sync(self._search(query))


class TimedRetriever(BaseRetriever):
    """Times the whole retrieval call and counts what came back.

    The span covers embedding *and* the vector query, because the retriever
    embeds the question before it can search and there is no seam between them
    from out here. `TurnTimings.payload` subtracts `t_embed` to report the vector
    query on its own -- see the note there.
    """

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


def build_retriever(settings: Settings | None = None) -> BaseRetriever:
    """The retriever, with a floor on how irrelevant a chunk may be.

    `k` alone returns the top four chunks regardless of distance, so an
    out-of-scope question -- "what is the capital of France" -- still put four
    irrelevant knowledge-base rows into the prompt. Refusal correctness measures
    10/10 today, which means the system prompt is carrying it entirely: grounding
    depends on prompt discipline with no retrieval-side backstop, and a future
    prompt edit could remove it without anything failing.

    So this is defence in depth, not a fix for a live defect. The threshold is
    deliberately permissive -- it is calibrated to drop chunks that are plainly
    unrelated, not to second-guess borderline ones, because a retrieval floor
    that starves a real question is a much worse failure than one that lets a
    weak chunk through to a prompt that will refuse anyway.

    Set `RETRIEVER_SCORE_THRESHOLD=0` to switch it off entirely.
    """
    settings = settings or get_settings()

    inner = PgVectorRetriever(
        embeddings=get_embeddings(),
        k=settings.retriever_k,
        max_cosine_distance=chroma_floor_as_cosine_distance(
            settings.retriever_score_threshold
        ),
    )
    # Timing only. `TimedRetriever` forwards the query unchanged and returns
    # exactly what the inner retriever returned, so `k`, the threshold and the
    # documents that reach the prompt are all untouched.
    return TimedRetriever(inner=inner)
