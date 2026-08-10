"""The pgvector retriever must return what the Chroma one returned."""

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
# The probe lives in a `scripts/` directory that not every checkout carries; a missing module must be a skip, n…
_latency_probe = pytest.importorskip(
    "scripts.latency_probe", reason="scripts/ is not in this checkout"
)
load_cases = _latency_probe.load_cases

pytestmark = pytest.mark.slow

#: How far apart two chunks may be and still be considered order-unstable.
NOISE_BAND = 2e-3


class _Fixed(Embeddings):
    """Returns one prepared vector, so both backends search with the same query."""

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
def baseline_ids(chroma_store) -> set[str]:
    """The knowledge-base ids the frozen Chroma snapshot actually holds."""
    metadatas = chroma_store.get(include=["metadatas"])["metadatas"]
    return {str(m["id"]) for m in metadatas if m and m.get("id")}


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


def _restrict(neon_corpus, among: set[str] | None):
    """The corpus narrowed to `among`, preserving order. None means all of it."""
    ids, matrix = neon_corpus
    if among is None:
        return ids, matrix
    keep = [i for i, kb_id in enumerate(ids) if kb_id in among]
    return [ids[i] for i in keep], matrix[keep]


def _exact(neon_corpus, vector: list[float], k: int, among: set[str] | None = None) -> list[str]:
    ids, matrix = _restrict(neon_corpus, among)
    query = np.array(vector, dtype=np.float64)
    query /= np.linalg.norm(query)
    distances = 1.0 - (matrix @ query)
    return [ids[i] for i in np.argsort(distances)[:k]]


def _distances(
    neon_corpus, vector: list[float], among: set[str] | None = None
) -> dict[str, float]:
    ids, matrix = _restrict(neon_corpus, among)
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
    """Rederived from Chroma's transform, independently of the implementation."""
    for threshold in (0.05, 0.2, 0.35, 0.5):
        cutoff = chroma_floor_as_cosine_distance(threshold)
        assert cutoff is not None
        relevance = 1.0 - (2.0 * cutoff) / math.sqrt(2.0)
        assert relevance == pytest.approx(threshold, abs=1e-9)


# --- the retriever is exact ----------------------------------------------


def test_pgvector_ranking_is_exact(neon_corpus, probe_vectors):
    """The real correctness gate, and it involves no provider nondeterminism."""
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
    """Regression: `asyncio.run` per call broke on the second question."""
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
    """The defence-in-depth `build_retriever` describes, actually working."""
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
    """The companion to the test above: without the floor, chunks do come back."""
    retriever = PgVectorRetriever(
        embeddings=get_embeddings(), k=4, max_cosine_distance=None
    )
    assert len(retriever.invoke("What is the capital of France?")) == 4


# --- against Chroma ------------------------------------------------------


@requires_chroma
def test_the_move_to_postgres_dropped_nothing(baseline_ids, neon_corpus):
    """Every chunk the baseline holds is still in Postgres."""
    ids, _ = neon_corpus
    missing = sorted(baseline_ids - set(ids))
    assert not missing, (
        f"{len(missing)} chunk(s) in the Chroma baseline are absent from Postgres: "
        f"{missing[:10]}"
    )


@requires_chroma
def test_rank_one_matches_chroma_for_every_probe_question(
    chroma_store, probe_vectors, neon_corpus, baseline_ids
):
    """The best chunk is never a coin flip: it has a clear margin on all 30."""
    divergences = []
    for question, vector in probe_vectors:
        expected = [_key(d) for d in chroma_store.similarity_search_by_vector(vector, k=5)]
        actual = _exact(neon_corpus, vector, 5, among=baseline_ids)
        if expected[:1] != actual[:1]:
            divergences.append((question, expected, actual))

    assert not divergences, "the top chunk changed:\n" + "\n".join(
        f"  {q!r}\n    chroma:   {e}\n    pgvector: {a}" for q, e, a in divergences
    )


@requires_chroma
def test_any_top_5_difference_is_confined_to_near_ties(
    chroma_store, probe_vectors, neon_corpus, baseline_ids
):
    """Sets may differ, but only among chunks too close to order reliably."""
    offenders = []
    for question, vector in probe_vectors:
        expected = [_key(d) for d in chroma_store.similarity_search_by_vector(vector, k=5)]
        actual = _exact(neon_corpus, vector, 5, among=baseline_ids)
        if expected == actual:
            continue

        distances = _distances(neon_corpus, vector, among=baseline_ids)
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
    # The columns the CSV carries, which the Chroma implementation also stored verbatim.
    for field in ("id", "category", "question", "answer", "audience", "source_url"):
        assert field in metadata, f"{field} missing from retrieved metadata"
    assert metadata["source"] == "knowledge_base.csv"
    assert isinstance(metadata["row"], int)
