"""Reranking twelve fused candidates down to the four the model reads.

Fusion decides which chunks are plausible. Reranking decides which are actually
about the question, and it can do that because it reads the question and the
chunk TOGETHER -- a bi-encoder embeds them separately and can only compare two
summaries after the fact.

## Why cutting to four matters more than the ordering does

Every extra chunk in the prompt is another set of figures the model can blend
into an answer and then attribute to none of them. Twelve chunks about
eligibility, deposits, deadlines and branches is twelve opportunities for a
sentence that is individually plausible and collectively invented. Four is
enough to answer from and few enough to check against.

So the reranker is a grounding control as much as a quality one.

## Two implementations, one interface

`CrossEncoderReranker` runs a real cross-encoder locally through fastembed --
no key, no network after the first download, single-digit milliseconds for
twelve pairs on CPU. It is the default when the model is available.

`LexicalReranker` is the fallback, and it is a real fallback rather than a
no-op: it scores on term overlap weighted by inverse document frequency, which
is a worse signal than a cross-encoder and a better one than fusion rank alone.
A deployment that cannot load the model gets degraded reranking rather than
none, and the log line says which one ran.

Both return scores in [0, 1] so `ground_check`'s telemetry means the same thing
either way.
"""

from __future__ import annotations

import logging
import math
import re
from functools import lru_cache
from typing import Protocol, Sequence

from app.graph.state import KBChunk

logger = logging.getLogger(__name__)

#: The cross-encoder. Small, English, and trained for exactly this: given a
#: query and a passage, how relevant is the passage.
DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    async def __call__(
        self, query: str, chunks: Sequence[KBChunk]
    ) -> list[float]: ...


# ── the real one ─────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _cross_encoder():
    """The model, loaded once per process, or None if it will not load.

    None rather than an exception, and cached either way: a deployment without
    the weights must not retry the load on every turn, and the first turn must
    not be the one that discovers a 90MB download.
    """
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
    """Cross-encoder logits to [0, 1].

    The model emits an unbounded logit, and `ground_check` records the top
    score as telemetry. Leaving it unbounded would make that number
    incomparable between the two rerankers and meaningless in a report.
    """
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


async def cross_encoder_scores(
    query: str, chunks: Sequence[KBChunk]
) -> list[float] | None:
    """Relevance for each chunk, or None if the model is unavailable.

    Runs in a worker thread. It is CPU-bound ONNX inference of about 5ms for
    twelve pairs, and 5ms of blocked event loop on every turn is 5ms nobody
    else can use -- on a service whose whole latency workstream is about not
    doing that.
    """
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

#: Words that carry no topical signal. Same list `ground_check` uses, so the
#: two agree about what a content word is.
_STOPWORDS = frozenset(
    "a an and are as at be by can could do does did for from had has have how i "
    "if in is it its me my of on or our so than that the their them there they "
    "this to us was we were what when where which who whom why will with would "
    "you your".split()
)


def lexical_scores(query: str, chunks: Sequence[KBChunk]) -> list[float]:
    """Term overlap weighted by inverse document frequency, normalised to [0,1].

    IDF is what stops this being a word count. In a corpus about a savings
    programme, "savings" appears in most rows and carries almost no signal,
    while "Gingerland" appears in two and carries a great deal. Weighting by
    rarity means a chunk matching the rare word wins over one matching the
    common one, which is the whole difference between this and counting.
    """
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
    """What `make_rerank` is given. Cross-encoder first, lexical if it cannot.

    Never raises and never returns a wrong-length list -- `make_rerank` zips
    these against the chunks, and a short list would silently drop the tail of
    the candidates.
    """
    scores = await cross_encoder_scores(query, chunks)
    if scores is not None and len(scores) == len(chunks):
        return scores
    return lexical_scores(query, chunks)


def reranker_available() -> bool:
    """Whether the cross-encoder loaded. Reported by `/ready`."""
    return _cross_encoder() is not None
