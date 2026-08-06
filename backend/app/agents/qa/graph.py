"""The Q&A subgraph, and the three agents that are all this one graph.

    rewrite_query → hybrid_retrieve → rerank → generate → ground_check
                                                              │
                                        grounded ─────────────┴───── ungrounded
                                            │                            │
                                         return                 Command(goto=
                                                                "escalate_agent")

## Card turns never get here

"Can I join?" and "let's play" are answered by a card, and both are recognised
in the MAIN graph, ahead of the classifier (`graph/nodes/cards.py`). That
placement is load-bearing rather than tidy: the classifier is free to route a
request to play a game at `learn_agent` or `escalate_agent`, and a matcher
living inside this subgraph would simply never run on those turns. Measured --
"let's play a game" escalated, and "can we play true or false" started a
lesson.

## qa_agent, qa_agent_limited and qa_agent_public are the same graph

They differ by a filter on `hybrid_retrieve` and by nothing else. That is a
deliberate choice with a specific failure in mind: three separate subgraphs
means three grounding checks, three citation paths and three places to forget
one -- and the one that gets forgotten will be the one serving children,
because it is the one nobody demos.

`nodes._audience` reads `state.active_agent` to pick the corpus slice. One
retrieval path, one grounding check, one place to get it right.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import START, StateGraph

from app.agents.qa.nodes import (
    make_generate,
    make_ground_check,
    make_hybrid_retrieve,
    make_rerank,
    make_rewrite_query,
)
from app.graph.state import AspireState

logger = logging.getLogger(__name__)


def build_qa_graph(
    *,
    search=None,
    corpus=None,
    rerank_score=None,
    rewrite_invoke=None,
    generate_invoke=None,
):
    """Compile the subgraph. Every model call and every I/O path is injected.

    Not for testability alone -- though that matters, and this subgraph is
    tested end to end with no network at all. It is because the three retrieval
    dependencies (dense search, the BM25 corpus, the cross-encoder) each have a
    different availability story, and a subgraph that constructed them itself
    would be a subgraph that cannot start when one of them is missing.
    """
    graph = StateGraph(AspireState)

    graph.add_node("rewrite_query", make_rewrite_query(rewrite_invoke))
    graph.add_node("hybrid_retrieve", make_hybrid_retrieve(search, corpus))
    graph.add_node("rerank", make_rerank(rerank_score))
    graph.add_node("generate", make_generate(generate_invoke))
    # No `destinations` here, deliberately. `ground_check` hands off with
    # `Command(graph=PARENT, goto="escalate_agent")`, and a destination
    # declaration would make langgraph look for a LOCAL node of that name --
    # which does not and should not exist in this subgraph.
    graph.add_node("ground_check", make_ground_check())

    graph.add_edge(START, "rewrite_query")
    graph.add_edge("rewrite_query", "hybrid_retrieve")
    graph.add_edge("hybrid_retrieve", "rerank")
    graph.add_edge("rerank", "generate")
    graph.add_edge("generate", "ground_check")

    return graph.compile()


# ── production wiring ────────────────────────────────────────────────────────


async def _search(query: str, k: int):
    """Dense retrieval against the existing pgvector corpus.

    Reuses `app.rag`'s embedding cache and retriever rather than opening a
    second path to the same table. The corpus, the embedding model and the
    cache are all already tuned; this subgraph is a consumer of that work, not
    a replacement for it.
    """
    from app.graph.state import KBChunk
    from app.rag import embed_query_cached, get_retriever
    from app.rag import PgVectorRetriever

    inner = getattr(get_retriever(), "inner", None)
    if not isinstance(inner, PgVectorRetriever):  # pragma: no cover - config error
        raise RuntimeError("The configured retriever cannot search by vector.")

    vector = await embed_query_cached(query)
    previous_k = inner.k
    try:
        inner.k = k
        scored = await inner.asearch_with_scores(vector)
    finally:
        inner.k = previous_k

    return [
        KBChunk(
            # `id` is the key the ingest actually writes -- it carries the CSV
            # column verbatim, and the `kb_id` column on the table is derived
            # from it rather than mirrored into the metadata. Reading only
            # `kb_id` gave every dense chunk a synthetic `row-N` id, which had
            # two consequences and both were silent: fusion could not match a
            # dense hit to the same row from BM25, and every answer's citation
            # -- taken by the model from the row text, which DOES carry the real
            # id -- was rejected by `ground_check` as invented.
            kb_id=str(
                document.metadata.get("kb_id")
                or document.metadata.get("id")
                or f"row-{index}"
            ),
            title=str(document.metadata.get("question") or document.metadata.get("title") or ""),
            content=document.page_content,
            # The REAL cosine relevance, 1.0 being identical. This is the
            # number `ground_check`'s floor compares against, and it is the
            # only calibrated similarity in the system -- a rank-derived score
            # would give the floor something to compare that means nothing.
            score=relevance,
            relevance=relevance,
            source="dense",
            metadata=dict(document.metadata),
        )
        for index, (document, relevance) in enumerate(scored)
    ]


async def _corpus(audience: str) -> list[tuple[str, str]]:
    """Every corpus row this audience may see, as `(kb_id, text)`, for BM25.

    Reads the whole table on every turn, which is affordable at 338 rows and
    would not be at ten thousand. Deliberately not cached: a cached corpus is a
    corpus that keeps answering from yesterday's knowledge base after somebody
    corrects a row, and correcting a row is the main way this content changes.

    The audience filter is applied HERE rather than after the search, because a
    row that must not be shown must not be able to displace one that may -- and
    a post-filter on the top-k does exactly that.
    """
    from sqlalchemy import select

    from app.db import session
    from app.db.models import Document

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
    """The rewrite runs on the CLASSIFIER's model, not the answer model.

    It is a mechanical transformation -- resolve a pronoun, restore an elided
    noun -- and paying answer-model prices for it on every mid-conversation turn
    would be a second expensive call in front of every question.
    """
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
    """Register this subgraph for all three Q&A agent names.

    One graph, three names, one filter. See the module docstring.
    """
    from app.graph.main_graph import register_agent

    for name in ("qa_agent", "qa_agent_limited", "qa_agent_public"):
        register_agent(name, build_production_qa)
