"""CSV knowledge base -> Documents -> persistent Chroma store.

Run directly to (re)build the store:

    python -m app.ingest
    python -m app.ingest --csv path/to/other.csv

Ingestion is idempotent: the collection is dropped and rebuilt from the CSV on
every run, so re-running never duplicates rows and deleted rows really disappear.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings, get_settings
from app.rag import build_vector_store, count_documents

logger = logging.getLogger(__name__)

# Recognised QA-style column names, lowercased. If a CSV has these we format the
# row nicely; otherwise we fall back to joining every column. Edit these sets to
# teach ingestion about new column names.
QUESTION_COLUMNS = {"question", "q", "prompt", "query", "title"}
ANSWER_COLUMNS = {"answer", "a", "response", "content", "body", "text"}
CATEGORY_COLUMNS = {"category", "topic", "section", "tag", "tags"}


def row_to_document(row: dict[str, str], row_number: int, source: str) -> Document | None:
    """Turn one CSV row into one Document.

    page_content is what gets embedded and shown to the model, so it is written to
    read as prose. Every original column is preserved verbatim in metadata.

    This is the only column-mapping logic in the codebase -- change it here.
    """
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
        # QA-shaped row: lead with the question so semantic search matches on it,
        # then any extra columns that aren't already represented.
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
        # Chroma metadata values must be scalars, so the original cells go in as-is.
        **values,
        "source": source,
        "row": row_number,
    }
    return Document(page_content=page_content, metadata=metadata)


def load_documents(csv_path: Path) -> list[Document]:
    """Read the CSV and return one Document per non-empty row."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Knowledge base CSV not found at {csv_path}. "
            "Set KNOWLEDGE_BASE_CSV in .env or place the file there."
        )

    documents: list[Document] = []
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


def chunk_documents(documents: list[Document], settings: Settings) -> list[Document]:
    """Split only the documents long enough to need it; short rows pass through whole."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        add_start_index=True,
    )
    return splitter.split_documents(documents)


def ingest(settings: Settings | None = None) -> int:
    """Rebuild the vector store from the configured CSV. Returns chunks written."""
    settings = settings or get_settings()
    csv_path = settings.resolved(settings.knowledge_base_csv)

    documents = load_documents(csv_path)
    if not documents:
        raise ValueError(f"{csv_path} contained no usable rows.")

    chunks = chunk_documents(documents, settings)

    store = build_vector_store(settings)
    # Clear existing vectors so re-running is a clean rebuild rather than an append.
    # We empty the collection in place instead of calling delete_collection(): dropping
    # it invalidates any Chroma handle already open on the same directory in this
    # process, which breaks startup auto-ingest.
    existing_ids = store.get(include=[])["ids"]
    if existing_ids:
        store.delete(ids=existing_ids)
    store.add_documents(chunks)

    logger.info(
        "Ingested %d rows from %s into %d chunks (collection %r)",
        len(documents),
        csv_path.name,
        len(chunks),
        settings.chroma_collection,
    )
    return len(chunks)


def ingest_if_empty(settings: Settings | None = None) -> int:
    """Ingest only when the persisted store is empty. Returns chunks written (0 if skipped)."""
    settings = settings or get_settings()
    store = build_vector_store(settings)
    existing = count_documents(store)

    if existing > 0:
        logger.info("Vector store already holds %d chunks; skipping ingest.", existing)
        return 0

    logger.info("Vector store is empty; running ingest.")
    return ingest(settings)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Build the ASPIRE vector store from a CSV.")
    parser.add_argument("--csv", type=Path, default=None, help="Override the CSV path.")
    args = parser.parse_args()

    settings = get_settings()
    if args.csv is not None:
        settings = settings.model_copy(update={"knowledge_base_csv": args.csv})

    try:
        written = ingest(settings)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr)
        return 1

    print(f"Ingest complete: {written} chunks in collection {settings.chroma_collection!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
