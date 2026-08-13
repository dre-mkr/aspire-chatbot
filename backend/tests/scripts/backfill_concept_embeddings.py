"""Give already-seeded concepts the embeddings they were written without.

`seed_concepts.py` embeds in Pass E, but a concept written while the embedding
provider was refusing calls lands in Postgres with `embedding = NULL`. The rows are
otherwise complete, so re-running the seeder would spend the whole LLM pipeline to
fix one column -- and would rewrite the concept text as a side effect.

This reads the rows that are missing a vector, embeds `embedding_text()` with the
product's own embedding model, and writes only that column back.

    cd backend && .venv/Scripts/python.exe tests/scripts/backfill_concept_embeddings.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND))

logger = logging.getLogger("backfill_concept_embeddings")

#: One column, by id. Everything else about the row is left alone.
_UPDATE = "UPDATE concepts SET embedding = CAST(:embedding AS vector) WHERE id = :id"


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


async def backfill(*, batch: int = 64, dry_run: bool = False) -> int:
    from sqlalchemy import text

    from app.db.engine import get_sessionmaker
    from app.learning.concepts import SELECT_COLUMNS, TeachingConcept

    maker = get_sessionmaker()
    if maker is None:
        logger.error("No database configured; nothing to do.")
        return 1

    async with maker() as session:
        result = await session.execute(text(f"SELECT {SELECT_COLUMNS} FROM concepts"))
        rows = [dict(row) for row in result.mappings()]

    concepts = [TeachingConcept.from_row(row) for row in rows]
    missing = [concept for concept in concepts if not concept.embedding]

    logger.info(
        "%d concepts, %d already embedded, %d to do.",
        len(concepts),
        len(concepts) - len(missing),
        len(missing),
    )
    if not missing:
        return 0

    if dry_run:
        for concept in missing[:10]:
            logger.info("  would embed %s (%s)", concept.id, concept.title)
        return 0

    from app.rag import get_embeddings

    embeddings = get_embeddings()
    written = 0

    for start in range(0, len(missing), batch):
        window = missing[start : start + batch]
        vectors = await embeddings.aembed_documents(
            [concept.embedding_text() for concept in window]
        )
        async with maker() as session:
            for concept, vector in zip(window, vectors, strict=True):
                await session.execute(
                    text(_UPDATE),
                    {"id": concept.id, "embedding": _vector_literal(list(vector))},
                )
            await session.commit()
        written += len(window)
        logger.info("  %d/%d written.", written, len(missing))

    logger.info("Done. %d concepts embedded.", written)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return asyncio.run(backfill(batch=args.batch, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
