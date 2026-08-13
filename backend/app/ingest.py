"""CSV knowledge base -> embeddings -> the `documents` table in Neon."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import uuid
from pathlib import Path

from langchain_core.documents import Document as LangchainDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, func, select, text

from app.config import Settings, get_settings
from app.db import session
from app.db.models import EMBEDDING_DIMENSIONS, Document, dimensions_for
from app.rag import build_embeddings

logger = logging.getLogger(__name__)

# Recognised QA-style column names, lowercased.
QUESTION_COLUMNS = {"question", "q", "prompt", "query", "title"}
ANSWER_COLUMNS = {"answer", "a", "response", "content", "body", "text"}
CATEGORY_COLUMNS = {"category", "topic", "section", "tag", "tags"}

#: CSV columns read into real table columns.
ID_COLUMNS = {"id", "kb_id", "ref", "code"}
AUDIENCE_COLUMNS = {"audience", "persona", "audiences", "for"}
SOURCE_URL_COLUMNS = {"source_url", "url", "source", "link"}
LANGUAGE_COLUMNS = {"language", "lang", "locale"}

#: Used when the CSV names no language.
DEFAULT_LANGUAGE = "en"

#: Advisory lock key, so two processes booting at once cannot both rewrite an empty table.
_INGEST_LOCK_KEY = 0x4153503133  # "ASP13"


def row_to_document(
    row: dict[str, str], row_number: int, source: str
) -> LangchainDocument | None:
    """Turn one CSV row into one Document."""
    # Drop empty cells and normalise keys so lookup is case/whitespace insensitive.
    values = {
        (key or "").strip(): (value or "").strip()
        for key, value in row.items()
        if key and (value or "").strip()
    }
    if not values:
        return None

    by_lower = {key.lower(): key for key in values}

    def first_match(candidates: set[str]) -> str | None:
        for lowered, original in by_lower.items():
            if lowered in candidates:
                return original
        return None

    question_key = first_match(QUESTION_COLUMNS)
    answer_key = first_match(ANSWER_COLUMNS)
    category_key = first_match(CATEGORY_COLUMNS)

    if question_key and answer_key:
        # QA-shaped row: lead with the question so semantic search matches on it.
        lines = []
        if category_key:
            lines.append(f"Category: {values[category_key]}")
        lines.append(f"Question: {values[question_key]}")
        lines.append(f"Answer: {values[answer_key]}")

        handled = {question_key, answer_key, category_key}
        extras = [f"{key}: {value}" for key, value in values.items() if key not in handled]
        lines.extend(extras)
        page_content = "\n".join(lines)
    else:
        # Unknown schema: join every column as "Column: value" lines.
        page_content = "\n".join(f"{key}: {value}" for key, value in values.items())

    metadata: dict[str, str | int] = {
        # Scalars only, as Chroma stored them: this dict is handed back to the client as a source.
        **values,
        "source": source,
        "row": row_number,
    }
    return LangchainDocument(page_content=page_content, metadata=metadata)


def load_documents(csv_path: Path) -> list[LangchainDocument]:
    """Read the CSV and return one Document per non-empty row."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Knowledge base CSV not found at {csv_path}. "
            "Set KNOWLEDGE_BASE_CSV in .env or place the file there."
        )

    documents: list[LangchainDocument] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path} has no header row.")

        # start=2 so the number matches the line in the file (row 1 is the header).
        for row_number, row in enumerate(reader, start=2):
            document = row_to_document(row, row_number, csv_path.name)
            if document is not None:
                documents.append(document)

    return documents


def chunk_documents(
    documents: list[LangchainDocument], settings: Settings
) -> list[LangchainDocument]:
    """Split only the documents long enough to need it; short rows pass through whole."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        add_start_index=True,
    )
    return splitter.split_documents(documents)


def _pick(metadata: dict, candidates: set[str]) -> str | None:
    """First metadata value whose key matches, case-insensitively."""
    for key, value in metadata.items():
        if str(key).lower() in candidates:
            text_value = str(value).strip()
            if text_value:
                return text_value
    return None


def _rows_for(chunks: list[LangchainDocument], vectors: list[list[float]]) -> list[Document]:
    """Pair chunks with their vectors and shape them into table rows."""
    if len(chunks) != len(vectors):
        raise ValueError(
            f"Embedded {len(vectors)} vectors for {len(chunks)} chunks; refusing to write."
        )

    # Counted per source row, so a long row's chunks are numbered 0, 1, 2 within that row.
    seen: dict[str, int] = {}
    rows: list[Document] = []

    for chunk, vector in zip(chunks, vectors, strict=True):
        metadata = dict(chunk.metadata)
        kb_id = _pick(metadata, ID_COLUMNS)
        key = kb_id or f"row:{metadata.get('row')}"
        index = seen.get(key, 0)
        seen[key] = index + 1

        audience = _pick(metadata, AUDIENCE_COLUMNS)

        rows.append(
            Document(
                id=uuid.uuid4(),
                content=chunk.page_content,
                embedding=vector,
                language=_pick(metadata, LANGUAGE_COLUMNS) or DEFAULT_LANGUAGE,
                # The CSV's `audience` vocabulary -- general | parent | student | teacher.
                persona_tags=[audience] if audience else [],
                account_status_tags=[],
                source_url=_pick(metadata, SOURCE_URL_COLUMNS),
                chunk_index=index,
                kb_id=kb_id,
                metadata_=metadata,
            )
        )

    return rows


def _check_dimensions(settings: Settings, vectors: list[list[float]]) -> None:
    """Refuse to write vectors the column cannot hold."""
    expected = dimensions_for(settings.embeddings_model)
    if expected is not None and expected != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"EMBEDDINGS_MODEL={settings.embeddings_model!r} produces {expected}-dim "
            f"vectors but documents.embedding is {EMBEDDING_DIMENSIONS}-dim. Write a "
            "migration to change the column width, then re-ingest."
        )
    if vectors and len(vectors[0]) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embeddings came back {len(vectors[0])}-dimensional but "
            f"documents.embedding is {EMBEDDING_DIMENSIONS}-dimensional."
        )


async def ingest(settings: Settings | None = None) -> int:
    """Rebuild the corpus in Neon from the configured CSV. Returns rows written."""
    settings = settings or get_settings()
    csv_path = settings.resolved(settings.knowledge_base_csv)

    documents = load_documents(csv_path)
    if not documents:
        raise ValueError(f"{csv_path} contained no usable rows.")

    chunks = chunk_documents(documents, settings)

    # Embedded before the transaction opens.
    logger.info("Embedding %d chunks with %s...", len(chunks), settings.embeddings_model)
    vectors = build_embeddings(settings).embed_documents([c.page_content for c in chunks])
    _check_dimensions(settings, vectors)

    rows = _rows_for(chunks, vectors)

    async with session() as db:
        if db is None:
            raise RuntimeError(
                "No database configured. Postgres is the source of truth for the "
                "knowledge base -- set DATABASE_URL and run `alembic upgrade head`."
            )
        # Empty-and-rewrite in one transaction: readers see the old corpus until commit.
        await db.execute(delete(Document))
        db.add_all(rows)

    logger.info(
        "Ingested %d rows from %s into %d chunks in Postgres.",
        len(documents),
        csv_path.name,
        len(rows),
    )

    # A reloaded knowledge base must never be served from cache.
    try:
        from app.cache import flush_answers

        flushed = await flush_answers()
        logger.info("Flushed %d cached entries after the corpus reload.", flushed)
    except Exception:
        logger.warning("Cache flush after ingest failed; the corpus fingerprint "
                       "still retires stale answers.", exc_info=True)

    return len(rows)


async def count_corpus() -> int:
    """How many chunks the corpus holds. -1 when there is no database."""
    async with session() as db:
        if db is None:
            return -1
        return int((await db.execute(select(func.count()).select_from(Document))).scalar() or 0)


async def ingest_if_empty(settings: Settings | None = None) -> int:
    """Ingest only when the corpus is empty."""
    settings = settings or get_settings()

    async with session() as db:
        if db is None:
            raise RuntimeError(
                "No database configured, so there is no knowledge base to serve. "
                "Set DATABASE_URL and run `alembic upgrade head`."
            )
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INGEST_LOCK_KEY})
        existing = int(
            (await db.execute(select(func.count()).select_from(Document))).scalar() or 0
        )
        if existing > 0:
            logger.info("Corpus already holds %d chunks; skipping ingest.", existing)
            return 0

    logger.info("Corpus is empty; running ingest.")
    return await ingest(settings)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Build the ASPIRE corpus from a CSV.")
    parser.add_argument("--csv", type=Path, default=None, help="Override the CSV path.")
    args = parser.parse_args()

    settings = get_settings()
    if args.csv is not None:
        settings = settings.model_copy(update={"knowledge_base_csv": args.csv})

    try:
        written = asyncio.run(ingest(settings))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr)
        return 1

    print(f"Ingest complete: {written} chunks in the documents table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
