"""Recreate `documents` -- this time as the corpus retrieval actually reads Revision ID: 0009_documents_live Rev…"""

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
        # The knowledge-base row this chunk came from ("ASP-042"), so a served answer can be traced to a line in the CS…
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
    # The extension stays: another table in this database may use it, and dropping it would take their columns with…
