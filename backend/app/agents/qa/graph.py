"""The Q&A subgraph, and the three agents that are all this one graph."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import START, StateGraph
from langgraph.types import Command

from app.agents.qa.nodes import (
    make_generate,
    make_ground_check,
    make_hybrid_retrieve,
    make_rerank,
    make_rewrite_query,
)
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: Lesson agents in preference order; the first one present in `allowed_agents` wins.
_LESSON_AGENTS: tuple[str, ...] = ("learn_agent", "learning_sample", "learning_preview")


async def _delegate(state: AspireState) -> Any:
    """QA is the default agent, so it hands clear non-QA intents to their owner."""
    from app.graph.nodes.intents import wants_lesson
    from app.graph.nodes.safety_in import latest_user_text

    message = latest_user_text(state)
    allowed = list(state.get("allowed_agents") or [])
    if message and wants_lesson(message):
        target = next((name for name in _LESSON_AGENTS if name in allowed), None)
        if target is not None:
            logger.info("QA handing a lesson request to %s.", target)
            return Command(
                graph=Command.PARENT,
                goto=target,
                update={"active_agent": target},
            )
    return {}


def build_qa_graph(
    *,
    search=None,
    corpus=None,
    rerank_score=None,
    rewrite_invoke=None,
    generate_invoke=None,
):
    """Compile the subgraph."""
    graph = StateGraph(AspireState)

    # No `destinations` on the handoff nodes: they leave via `Command(graph=Command.PARENT)`.
    graph.add_node("delegate", _delegate)
    graph.add_node("rewrite_query", make_rewrite_query(rewrite_invoke))
    graph.add_node("hybrid_retrieve", make_hybrid_retrieve(search, corpus))
    graph.add_node("rerank", make_rerank(rerank_score))
    graph.add_node("generate", make_generate(generate_invoke))
    graph.add_node("ground_check", make_ground_check())

    graph.add_edge(START, "delegate")
    graph.add_edge("delegate", "rewrite_query")
    graph.add_edge("rewrite_query", "hybrid_retrieve")
    graph.add_edge("hybrid_retrieve", "rerank")
    graph.add_edge("rerank", "generate")
    graph.add_edge("generate", "ground_check")

    return graph.compile()


# ── production wiring ────────────────────────────────────────────────────────


async def _search(query: str, k: int):
    """Dense retrieval against the existing pgvector corpus."""
    import time

    from app import timing
    from app.graph.state import KBChunk
    from app.rag import embed_query_cached, get_retriever
    from app.rag import PgVectorRetriever

    inner = getattr(get_retriever(), "inner", None)
    if not isinstance(inner, PgVectorRetriever):  # pragma: no cover - config error
        raise RuntimeError("The configured retriever cannot search by vector.")

    # Measured here rather than by `TimedRetriever`, which wraps `get_retriever()`
    # and which this function deliberately reaches THROUGH -- `inner.k` has to be
    # mutated for the wider QA fan-out. So the wrapper's instrumentation never
    # sees a QA turn, and `t_embed` / `t_retrieve` would stay blank without this.
    embed_started = time.perf_counter()
    vector = await embed_query_cached(query)
    timing.record_stage(timing.T_EMBED, (time.perf_counter() - embed_started) * 1000.0)

    previous_k = inner.k
    search_started = time.perf_counter()
    try:
        inner.k = k
        scored = await inner.asearch_with_scores(vector)
    finally:
        inner.k = previous_k
        timing.record_stage(timing.T_RETRIEVE, (time.perf_counter() - search_started) * 1000.0)

    timing.annotate(retrieved_chunk_count=len(scored))

    return [
        KBChunk(
            # Ingest writes the CSV id under `id`, so fall back to it when `kb_id` is missing.
            kb_id=str(
                document.metadata.get("kb_id")
                or document.metadata.get("id")
                or f"row-{index}"
            ),
            title=str(document.metadata.get("question") or document.metadata.get("title") or ""),
            content=document.page_content,
            # The REAL cosine relevance, 1.0 being identical.
            score=relevance,
            relevance=relevance,
            source="dense",
            metadata=dict(document.metadata),
        )
        for index, (document, relevance) in enumerate(scored)
    ]


#: The permitted corpus per audience, and the fingerprint it was read at.
#:
#: This was an unbounded `SELECT` of every document row on EVERY question, on
#: the critical path, followed by a Python-side permission filter. Measured on
#: this machine: 610-720 ms warm, 4.9 s on the first read of a cold process, for
#: a table that changes only when `ingest` runs.
_CORPUS: dict[str, list[tuple[str, str]]] = {}
_CORPUS_AT: str | None = None


def forget_corpus() -> None:
    """Drop the cached corpus. Called by `ingest` after it rewrites the table."""
    _CORPUS.clear()
    global _CORPUS_AT
    _CORPUS_AT = None


async def _corpus(audience: str) -> list[tuple[str, str]]:
    """Every corpus row this audience may see, as `(kb_id, text)`, for BM25."""
    from sqlalchemy import select

    from app.cache import corpus_fingerprint
    from app.db import session
    from app.db.models import Document

    # Keyed on the corpus fingerprint as well as cleared by `ingest`: the
    # fingerprint is a sha of the CSV, so editing the knowledge base and
    # restarting is enough to invalidate this without anyone remembering to.
    global _CORPUS_AT
    try:
        fingerprint = corpus_fingerprint()
    except Exception:  # pragma: no cover - no CSV on this box
        fingerprint = ""
    if fingerprint != _CORPUS_AT:
        _CORPUS.clear()
        _CORPUS_AT = fingerprint

    cached = _CORPUS.get(audience)
    if cached is not None:
        return cached

    async with session() as db:
        if db is None:
            return []
        rows = (
            await db.execute(
                select(Document.kb_id, Document.content, Document.metadata_)
            )
        ).all()

    from app.agents.qa.nodes import _permitted
    from app.graph.state import KBChunk

    permitted: list[tuple[str, str]] = []
    for kb_id, content, metadata in rows:
        if not kb_id or not content:
            continue
        chunk = KBChunk(kb_id=str(kb_id), content=content, metadata=dict(metadata or {}))
        if _permitted(chunk, audience):
            permitted.append((str(kb_id), content))

    _CORPUS[audience] = permitted
    return permitted


async def _generate_invoke(messages: list[Any]) -> str:
    from app.agent import build_chat_model

    response = await build_chat_model().ainvoke(messages)
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


async def _rewrite_invoke(system: str, user: str) -> str:
    """The rewrite runs on the CLASSIFIER's model, not the answer model."""
    from app.graph.nodes.classify import default_invoke

    return await default_invoke(system, user)


def build_production_qa():
    """The subgraph as the running service uses it."""
    from app.agents.qa.rerank import rerank_scores

    return build_qa_graph(
        search=_search,
        corpus=_corpus,
        rerank_score=rerank_scores,
        rewrite_invoke=_rewrite_invoke,
        generate_invoke=_generate_invoke,
    )


def register() -> None:
    """Register this subgraph for all three Q&A agent names."""
    from app.graph.main_graph import register_agent

    for name in ("qa_agent", "qa_agent_limited", "qa_agent_public"):
        register_agent(name, build_production_qa)
