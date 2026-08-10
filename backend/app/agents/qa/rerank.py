"""Reranking twelve fused candidates down to the four the model reads."""

from __future__ import annotations

import logging
import math
import re
from functools import lru_cache
from typing import Protocol, Sequence

from app.graph.state import KBChunk

logger = logging.getLogger(__name__)

#: The cross-encoder.
DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    async def __call__(
        self, query: str, chunks: Sequence[KBChunk]
    ) -> list[float]: ...


# ── the real one ─────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _cross_encoder():
    """The model, loaded once per process, or None if it will not load."""
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        model = TextCrossEncoder(model_name=DEFAULT_MODEL)
        # Warmed here so a failure surfaces at load rather than mid-turn.
        list(model.rerank("warm", ["warm"]))
        logger.info("Cross-encoder reranker loaded: %s", DEFAULT_MODEL)
        return model
    except Exception:
        logger.warning(
            "Could not load the cross-encoder %s; falling back to lexical "
            "reranking. Retrieval still works and is a little worse.",
            DEFAULT_MODEL,
            exc_info=True,
        )
        return None


def _sigmoid(value: float) -> float:
    """Cross-encoder logits to [0, 1]."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


async def cross_encoder_scores(
    query: str, chunks: Sequence[KBChunk]
) -> list[float] | None:
    """Relevance for each chunk, or None if the model is unavailable."""
    model = _cross_encoder()
    if model is None or not chunks:
        return None

    import asyncio

    passages = [chunk.content for chunk in chunks]
    try:
        raw = await asyncio.to_thread(lambda: list(model.rerank(query, passages)))
    except Exception:
        logger.warning("Cross-encoder scoring failed; keeping fusion order.", exc_info=True)
        return None
    return [_sigmoid(float(score)) for score in raw]


# ── the fallback ─────────────────────────────────────────────────────────────

_WORD = re.compile(r"[a-z0-9$]+")

#: Words that carry no topical signal.
_STOPWORDS = frozenset(
    "a an and are as at be by can could do does did for from had has have how i "
    "if in is it its me my of on or our so than that the their them there they "
    "this to us was we were what when where which who whom why will with would "
    "you your".split()
)


def lexical_scores(query: str, chunks: Sequence[KBChunk]) -> list[float]:
    """Term overlap weighted by inverse document frequency, normalised to [0,1]."""
    if not chunks:
        return []

    terms = [token for token in _WORD.findall(query.lower()) if token not in _STOPWORDS]
    if not terms:
        return [0.0 for _ in chunks]

    tokenised = [set(_WORD.findall(chunk.content.lower())) for chunk in chunks]
    total = len(chunks)

    scores: list[float] = []
    for tokens in tokenised:
        score = 0.0
        for term in set(terms):
            if term not in tokens:
                continue
            appearances = sum(1 for other in tokenised if term in other)
            score += math.log(1 + total / appearances)
        scores.append(score)

    peak = max(scores, default=0.0)
    return [score / peak if peak > 0 else 0.0 for score in scores]


# ── the node's dependency ────────────────────────────────────────────────────


async def rerank_scores(query: str, chunks: Sequence[KBChunk]) -> list[float]:
    """What `make_rerank` is given."""
    scores = await cross_encoder_scores(query, chunks)
    if scores is not None and len(scores) == len(chunks):
        return scores
    return lexical_scores(query, chunks)


def reranker_available() -> bool:
    """Whether the cross-encoder loaded. Reported by `/ready`."""
    return _cross_encoder() is not None
