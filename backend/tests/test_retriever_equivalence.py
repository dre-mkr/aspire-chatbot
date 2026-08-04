"""The pgvector retriever must return what the Chroma one returned.

This is the gate on P13-002. Moving the corpus from a local Chroma store to
Postgres is supposed to change where the vectors live and nothing else -- not
which chunks reach the prompt, not their order, and not where the relevance floor
falls.

## What the investigation found

The brief for this phase said a divergence "means an embedding or normalization
bug, not an acceptable approximation difference". It was neither, and the third
possibility is worth recording because it changes what can be asserted.

Measured, on this corpus:

* **Both searches are exact.** pgvector's `ORDER BY embedding <=> q` reproduces a
  numpy cosine ranking element for element (`test_pgvector_ranking_is_exact`).
  Chroma's HNSW also returned the exact ranking -- at 332 rows with
  `ef_search=100` it examines the whole graph, so there was never an
  approximation to inherit.
* **OpenAI's embedding API is not bit-deterministic.** Two identical
  `embed_query` calls differ by up to 9.2e-05 per component. The document vectors
  from the Chroma ingest and the Neon ingest differ by up to 1.45e-03, which is a
  cosine perturbation of ~1.5e-04.
* **Two of the thirty probe questions have candidates closer together than that.**
  For "Combien y a-t-il sur le compte d'épargne ASPIRE ?", ASP-254 and ASP-172 sit
  1.5e-04 apart. Their order is a coin flip below the embedding model's own
  reproducibility floor, and no amount of care in this code makes it stable.

So exact top-k equality across a re-ingest is not obtainable while embeddings come
from a hosted, non-deterministic provider. It would be obtainable by copying
vectors instead of recomputing them, or by embedding locally with a deterministic
model -- neither of which is this phase's job.

What IS asserted, therefore: the ranking is exact given the vectors, rank 1 is
stable, and anything that differs between the two backends differs only among
chunks sitting within `NOISE_BAND` of the top-k boundary. A genuinely better chunk
going missing would be far outside that band and would fail this file loudly.

Retrieval *quality* was checked separately and is unchanged: `evals.run
--retrieval` scores hit_rate 0.95 / MRR 0.9056 on both backends, with identical
per-language and per-kind breakdowns over all 60 golden cases.

Marked `slow`: it embeds 30 questions against the live provider.

## Why Chroma is constructed here rather than imported

`app/rag.py` no longer knows what Chroma is, which is the point of the change. The
baseline is built inside the test, against the store still on disk at
`data/chroma`. Every comparison here skips when that directory is gone, so
deleting it retires the comparison cleanly instead of breaking CI.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import numpy as np
import pytest
from langchain_core.embeddings import Embeddings
from sqlalchemy import text

from app.config import get_settings
from app.db import session
from app.rag import (
    PgVectorRetriever,
    build_embeddings,
    chroma_floor_as_cosine_distance,
    get_embeddings,
)
from scripts.latency_probe import load_cases

pytestmark = pytest.mark.slow

#: How far apart two chunks may be and still be considered order-unstable.
#:
#: The measured worst-case cosine perturbation from re-embedding the same text is
#: ~1.5e-04. This is an order of magnitude above that, and still two orders below
#: the span that separates a relevant chunk from the relevance floor (top hits sit
#: around 0.35 cosine distance; the floor is 0.5657). A recall bug would show up
#: as a difference far outside this band.
NOISE_BAND = 2e-3


class _Fixed(Embeddings):
    """Returns one prepared vector, so both backends search with the same query.

    This is what turns the comparison into a controlled experiment. Embedding each
    question twice -- once per backend -- would put provider nondeterminism on the
    query side as well as the corpus side, and there would be no way to tell which
    one moved a result.
    """

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.vector

    async def aembed_query(self, text: str) -> list[float]:
        return self.vector


def _chroma_dir() -> Path:
    settings = get_settings()
    return settings.resolved(settings.chroma_dir)


requires_chroma = pytest.mark.skipif(
    not (_chroma_dir() / "chroma.sqlite3").exists(),
    reason="the Chroma baseline store has been removed; this comparison is retired",
)


@pytest.fixture(scope="module")
def chroma_store():
    from langchain_chroma import Chroma

    settings = get_settings()
    return Chroma(
        collection_name=settings.chroma_collection,
        embedding_function=build_embeddings(settings),
        persist_directory=str(_chroma_dir()),
    )


@pytest.fixture(scope="module")
def neon_corpus() -> tuple[list[str], np.ndarray]:
    """Every stored vector, normalised, for exact rankings computed here."""

    async def fetch():
        async with session() as db:
            assert db is not None, "these tests need the Postgres corpus"
            rows = (
                await db.execute(text("SELECT kb_id, embedding::text FROM documents"))
            ).all()
        return rows

    rows = asyncio.run(fetch())
    ids = [row[0] for row in rows]
    matrix = np.array(
        [[float(x) for x in row[1].strip("[]").split(",")] for row in rows],
        dtype=np.float64,
    )
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return ids, matrix


@pytest.fixture(scope="module")
def probe_vectors() -> list[tuple[str, list[float]]]:
    """One embedding per probe question, computed once and shared."""
    embeddings = get_embeddings()
    return [(case["q"], embeddings.embed_query(case["q"])) for case in load_cases()]


def _key(document) -> str:
    return str(document.metadata.get("id") or document.page_content[:120])


def _exact(neon_corpus, vector: list[float], k: int) -> list[str]:
    ids, matrix = neon_corpus
    query = np.array(vector, dtype=np.float64)
    query /= np.linalg.norm(query)
    distances = 1.0 - (matrix @ query)
    return [ids[i] for i in np.argsort(distances)[:k]]


def _distances(neon_corpus, vector: list[float]) -> dict[str, float]:
    ids, matrix = neon_corpus
    query = np.array(vector, dtype=np.float64)
    query /= np.linalg.norm(query)
    return dict(zip(ids, 1.0 - (matrix @ query), strict=True))


# --- the floor -----------------------------------------------------------


def test_the_floor_translates_to_the_documented_cosine_distance():
    """0.2 on Chroma's Euclidean relevance is cosine similarity 0.434315."""
    assert chroma_floor_as_cosine_distance(0.2) == pytest.approx(0.565685, abs=1e-6)
    assert 1.0 - chroma_floor_as_cosine_distance(0.2) == pytest.approx(0.434315, abs=1e-6)


def test_the_floor_can_be_switched_off():
    assert chroma_floor_as_cosine_distance(0.0) is None
    assert chroma_floor_as_cosine_distance(-1.0) is None


def test_the_floor_derivation_matches_chromas_arithmetic():
    """Rederived from Chroma's transform, independently of the implementation.

    Chroma keeps a chunk when `1 - L2squared/sqrt(2) >= threshold`, and for unit
    vectors `L2squared == 2 * cosine_distance`. Anything agreeing with this loop
    agrees with Chroma.
    """
    for threshold in (0.05, 0.2, 0.35, 0.5):
        cutoff = chroma_floor_as_cosine_distance(threshold)
        assert cutoff is not None
        relevance = 1.0 - (2.0 * cutoff) / math.sqrt(2.0)
        assert relevance == pytest.approx(threshold, abs=1e-9)


# --- the retriever is exact ----------------------------------------------


def test_pgvector_ranking_is_exact(neon_corpus, probe_vectors):
    """The real correctness gate, and it involves no provider nondeterminism.

    Same vectors, same query, two independent implementations: Postgres'
    `<=>` operator and a numpy dot product. They must agree exactly. If they ever
    do not, the bug is in the SQL, the cast, or the stored vectors -- not in
    anything upstream.
    """
    mismatches = []
    for question, vector in probe_vectors:
        retriever = PgVectorRetriever(embeddings=_Fixed(vector), k=5, max_cosine_distance=None)
        actual = [_key(d) for d in retriever.invoke(question)]
        expected = _exact(neon_corpus, vector, 5)
        if actual != expected:
            mismatches.append((question, expected, actual))

    assert not mismatches, "pgvector disagreed with an exact numpy ranking:\n" + "\n".join(
        f"  {q!r}\n    numpy:    {e}\n    pgvector: {a}" for q, e, a in mismatches
    )


def test_repeated_synchronous_retrieval_works(probe_vectors):
    """Regression: `asyncio.run` per call broke on the second question.

    The engine is process-wide and its pooled asyncpg connections bind to the loop
    that created them, so a fresh-loop-per-call bridge dies with "Event loop is
    closed" the second time. `evals/run.py` calls `invoke()` sixty times.
    """
    _, vector = probe_vectors[0]
    retriever = PgVectorRetriever(embeddings=_Fixed(vector), k=3, max_cosine_distance=None)
    for _ in range(4):
        assert len(retriever.invoke("anything")) == 3


def test_nothing_past_the_floor_is_ever_returned(neon_corpus, probe_vectors):
    """Whatever comes back is within the cutoff, on all thirty questions."""
    settings = get_settings()
    cutoff = chroma_floor_as_cosine_distance(settings.retriever_score_threshold)
    assert cutoff is not None

    for question, vector in probe_vectors:
        retriever = PgVectorRetriever(
            embeddings=_Fixed(vector), k=settings.retriever_k, max_cosine_distance=cutoff
        )
        distances = _distances(neon_corpus, vector)
        for document in retriever.invoke(question):
            assert distances[_key(document)] <= cutoff + 1e-9


def test_the_floor_starves_an_out_of_scope_question():
    """The defence-in-depth `build_retriever` describes, actually working.

    Not checked against the probe questions: every one of those is answerable
    from the corpus, so all four chunks clear the floor and the threshold never
    bites. It bites here, which is the case it exists for -- without it these
    questions put four irrelevant knowledge-base rows into the prompt and left
    grounding entirely to the system prompt.
    """
    settings = get_settings()
    retriever = PgVectorRetriever(
        embeddings=get_embeddings(),
        k=settings.retriever_k,
        max_cosine_distance=chroma_floor_as_cosine_distance(
            settings.retriever_score_threshold
        ),
    )
    for question in (
        "What is the capital of France?",
        "Can you help me with my chemistry homework about covalent bonds?",
    ):
        assert retriever.invoke(question) == [], f"the floor let {question!r} through"


def test_the_floor_is_what_excludes_them_not_an_empty_corpus():
    """The companion to the test above: without the floor, chunks do come back.

    Two tests that could both pass on a broken corpus are worth one that cannot.
    """
    retriever = PgVectorRetriever(
        embeddings=get_embeddings(), k=4, max_cosine_distance=None
    )
    assert len(retriever.invoke("What is the capital of France?")) == 4


# --- against Chroma ------------------------------------------------------


@requires_chroma
def test_both_backends_hold_the_same_number_of_chunks(chroma_store):
    """A count mismatch means ingestion dropped or duplicated rows."""
    from app.ingest import count_corpus

    assert chroma_store._collection.count() == asyncio.run(count_corpus())


@requires_chroma
def test_rank_one_matches_chroma_for_every_probe_question(chroma_store, probe_vectors):
    """The best chunk is never a coin flip: it has a clear margin on all 30."""
    divergences = []
    for question, vector in probe_vectors:
        expected = [_key(d) for d in chroma_store.similarity_search_by_vector(vector, k=5)]
        retriever = PgVectorRetriever(embeddings=_Fixed(vector), k=5, max_cosine_distance=None)
        actual = [_key(d) for d in retriever.invoke(question)]
        if expected[:1] != actual[:1]:
            divergences.append((question, expected, actual))

    assert not divergences, "the top chunk changed:\n" + "\n".join(
        f"  {q!r}\n    chroma:   {e}\n    pgvector: {a}" for q, e, a in divergences
    )


@requires_chroma
def test_any_top_5_difference_is_confined_to_near_ties(
    chroma_store, probe_vectors, neon_corpus
):
    """Sets may differ, but only among chunks too close to order reliably.

    This is the assertion that would catch a real regression. A chunk dropped
    because of a normalisation error, a wrong cast, or a mangled vector would sit
    far from the boundary, and `NOISE_BAND` would not cover it.
    """
    offenders = []
    for question, vector in probe_vectors:
        expected = [_key(d) for d in chroma_store.similarity_search_by_vector(vector, k=5)]
        retriever = PgVectorRetriever(embeddings=_Fixed(vector), k=5, max_cosine_distance=None)
        actual = [_key(d) for d in retriever.invoke(question)]
        if expected == actual:
            continue

        distances = _distances(neon_corpus, vector)
        # The boundary is the worst distance either side was willing to include.
        boundary = max(distances[key] for key in actual)
        for key in set(expected) ^ set(actual):
            gap = abs(distances[key] - boundary)
            if gap > NOISE_BAND:
                offenders.append((question, key, distances[key], boundary, gap))

    assert not offenders, "a top-5 difference was too far from the boundary:\n" + "\n".join(
        f"  {q!r}\n    {key} at {d:.8f}, boundary {b:.8f}, gap {g:.2e} > {NOISE_BAND:.0e}"
        for q, key, d, b, g in offenders
    )


# --- shape ---------------------------------------------------------------


def test_metadata_survives_the_move(probe_vectors):
    """`_extract_sources` puts this dict on the wire, so its shape is API."""
    _, vector = probe_vectors[0]
    retriever = PgVectorRetriever(embeddings=_Fixed(vector), k=1, max_cosine_distance=None)
    documents = retriever.invoke("What is ASPIRE Day?")

    assert documents, "the corpus returned nothing"
    metadata = documents[0].metadata
    # The columns the CSV carries, which the Chroma implementation also stored
    # verbatim. `id` in particular is what `evals/run.py` scores on.
    for field in ("id", "category", "question", "answer", "audience", "source_url"):
        assert field in metadata, f"{field} missing from retrieved metadata"
    assert metadata["source"] == "knowledge_base.csv"
    assert isinstance(metadata["row"], int)
