"""Recreate `documents` -- this time as the corpus retrieval actually reads

Revision ID: 0009_documents_live
Revises: 0008_drop_documents
Create Date: 2026-08-04

0008 dropped this table because it had always held 0 rows: the pgvector schema
was built and indexed in 0001/0002, never written to, and retrieval ran on Chroma
the whole time. This recreates it for the opposite reason -- it is now the source
of truth, ingestion writes to it, and `app/rag.py` reads it on every turn.

The two migrations are not a mistake and a correction of that mistake. 0008
removed a table nothing used; this adds a table something uses. Keeping both in
the chain is what makes that sequence legible to anyone reading the history, and
0008's `downgrade()` is deliberately NOT what this reuses.

## No vector index, on purpose

0002 built an HNSW index over `(embedding::halfvec(3072))`. This does not, and
the reasoning is the whole design:

* **332 rows.** A sequential scan computes 332 dot products of 3072 floats --
  about a million multiply-adds, which Postgres does in single-digit
  milliseconds. HNSW exists to avoid scanning millions of rows; at this size the
  graph traversal has nothing to save and would examine most of the corpus
  regardless.
* **It would cost exactness twice.** HNSW is approximate by construction, and
  pgvector cannot index `vector` beyond 2000 dimensions, so 3072 forces a
  `halfvec` cast -- float16, which perturbs scores in the fourth decimal place.
  The retrieval floor this corpus is served with sits at cosine similarity
  0.434315 (see `app/rag.py`), and a chunk within float16 noise of that boundary
  would be admitted or dropped by rounding rather than by relevance.
* **The equivalence test demands it.** `tests/test_retriever_equivalence.py`
  asserts this retriever returns the same top-5 as the Chroma one it replaces.
  An approximate index turns any failure there into an argument about tolerance
  instead of a bug report.

If the corpus ever outgrows a scan, 0002 is the recipe -- and note its warning
that the query must cast identically or the planner silently ignores the index.

The b-tree on `language` stays. It is in the WHERE clause of every search.
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_documents_live"
down_revision: str | None = "0008_drop_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `text-embedding-3-large`. Kept in step with app.db.models.EMBEDDING_DIMENSIONS.
EMBEDDING_DIMENSIONS = 3072


def upgrade() -> None:
    # Installed per database on Neon, not per project, so this runs here too.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSIONS),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column(
            "persona_tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "account_status_tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        # The knowledge-base row this chunk came from ("ASP-042"), so a served
        # answer can be traced to a line in the CSV without matching on prose.
        # Not unique: a long row splits into several chunks that share it.
        sa.Column("kb_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index("ix_documents_language", "documents", ["language"])
    op.create_index("ix_documents_kb_id", "documents", ["kb_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_kb_id", table_name="documents")
    op.drop_index("ix_documents_language", table_name="documents")
    op.drop_table("documents")
    # The extension stays: another table in this database may use it, and
    # dropping it would take their columns with it.
