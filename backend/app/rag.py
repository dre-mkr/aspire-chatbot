"""Embeddings and the persistent Chroma vector store.

`build_embeddings` is the single switch point for the embeddings backend:
add a branch here (and a value to Settings.embeddings_provider) to move to a
hosted provider without touching ingestion, the agent, or the API.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

from app.config import Settings, get_settings

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


def build_embeddings(settings: Settings | None = None) -> Embeddings:
    """Construct the configured embeddings backend. The one place to extend."""
    settings = settings or get_settings()

    if settings.embeddings_provider == "openai":
        # Reads OPENAI_API_KEY from the environment, same as the chat model.
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=settings.embeddings_model)

    if settings.embeddings_provider == "fastembed":
        return FastEmbedEmbeddings(settings.embeddings_model)

    raise ValueError(f"Unsupported embeddings_provider: {settings.embeddings_provider!r}")


def build_vector_store(settings: Settings | None = None) -> Chroma:
    """Open (or create) the persistent Chroma collection."""
    settings = settings or get_settings()
    persist_dir = settings.resolved(settings.chroma_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)

    return Chroma(
        collection_name=settings.chroma_collection,
        embedding_function=build_embeddings(settings),
        persist_directory=str(persist_dir),
    )


@lru_cache(maxsize=1)
def get_vector_store() -> Chroma:
    """Process-wide vector store, so the embedding model is loaded only once."""
    return build_vector_store()


def count_documents(store: Chroma) -> int:
    """Number of vectors currently in the collection."""
    return store._collection.count()


def build_retriever(store: Chroma, settings: Settings | None = None) -> BaseRetriever:
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
    threshold = settings.retriever_score_threshold
    if threshold <= 0:
        return store.as_retriever(search_kwargs={"k": settings.retriever_k})

    return store.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={
            "k": settings.retriever_k,
            "score_threshold": threshold,
        },
    )
