"""Drop the unused pgvector `documents` table

Revision ID: 0008_drop_documents
Revises: 0007_accounts
Create Date: 2026-08-04

The table has 0 rows and has always had 0 rows. Nothing reads it and nothing
writes it: retrieval runs on Chroma (`app/rag.py`), which is where the corpus
actually lives.

What it did carry was cost and a false impression. An HNSW index over
`(embedding::halfvec(3072))`, two GIN indexes on tag arrays and a language btree
all existed for a table nobody used, `check_embedding_dimensions()` ran at every
boot to validate a column nothing writes, and the schema implied a retrieval path
that does not exist -- which is what made the original audit brief assume this
service used pgvector in the first place.

Decision (P7-007, owner, 2026-08-04): drop it. The alternative was to finish the
pgvector migration and delete Chroma, which is a real piece of work and not one
to do by accident because a table was sitting there.

## This is reversible

`downgrade()` recreates the table and every index exactly as 0001 and 0002 built
them. There is no data to lose -- that is the entire premise -- so a rollback
restores the schema completely, and re-adopting pgvector later means writing the
retrieval code, not recovering anything from here.

## Safety

`DROP TABLE ... CASCADE` is deliberately NOT used. Nothing references this table,
and if something did, this migration should fail loudly rather than quietly
delete whatever that was.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0008_drop_documents"
down_revision: str | None = "0007_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 3072


def upgrade() -> None:
    # Indexes first and by name, so a partially-applied earlier state (an index
    # that exists without its table, or vice versa) does not stop this.
    op.execute("DROP INDEX IF EXISTS ix_documents_account_status_tags")
    op.execute("DROP INDEX IF EXISTS ix_documents_persona_tags")
    op.execute("DROP INDEX IF EXISTS ix_documents_embedding_en")
    op.execute("DROP INDEX IF EXISTS ix_documents_language")
    op.execute("DROP TABLE IF EXISTS documents")


def downgrade() -> None:
    """Rebuild the table and its indexes exactly as 0001 and 0002 had them."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column(
            "persona_tags", ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "account_status_tags", ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_documents_language", "documents", ["language"])

    # The halfvec cast is load-bearing: pgvector indexes `vector` only up to
    # 2000 dimensions, and this project embeds at 3072. See 0002 for the full
    # note -- and for why the query must cast identically or the planner
    # silently falls back to a sequential scan.
    op.execute(
        "CREATE INDEX ix_documents_embedding_en ON documents "
        "USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops) "
        "WHERE language = 'en'"
    )
    op.execute(
        "CREATE INDEX ix_documents_persona_tags ON documents "
        "USING gin (persona_tags)"
    )
    op.execute(
        "CREATE INDEX ix_documents_account_status_tags ON documents "
        "USING gin (account_status_tags)"
    )
