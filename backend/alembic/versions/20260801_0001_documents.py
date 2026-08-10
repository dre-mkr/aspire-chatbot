"""pgvector extension and the documents table Revision ID: 0001_documents Revises: Create Date: 2026-08-01 The r…"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_documents"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `text-embedding-3-large`. Kept in step with app.db.models.EMBEDDING_DIMENSIONS.
EMBEDDING_DIMENSIONS = 3072


def upgrade() -> None:
    # pgvector ships on every Neon plan but is installed PER DATABASE, so this runs in each one rather than once pe…
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

    # Language is in the WHERE clause of every retrieval and is what the partial vector indexes partition on, so it…
    op.create_index("ix_documents_language", "documents", ["language"])


def downgrade() -> None:
    op.drop_index("ix_documents_language", table_name="documents")
    op.drop_table("documents")
    # The extension is deliberately NOT dropped: another table in the same database may be using it, and dropping i…
