"""Drop the unused pgvector `documents` table Revision ID: 0008_drop_documents Revises: 0007_accounts Create Dat…"""

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
    # Indexes first and by name, so a partially-applied earlier state (an index that exists without its table, or v…
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

    # The halfvec cast is load-bearing: pgvector indexes `vector` only up to 2000 dimensions, and this project embe…
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
