"""Vector and tag indexes for documents Revision ID: 0002_indexes Revises: 0001_documents Create Date: 2026-08-0…"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_indexes"
down_revision: str | None = "0001_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 3072

# pgvector indexes the `vector` type up to 2000 dimensions.
HALFVEC_EXPRESSION = f"(embedding::halfvec({EMBEDDING_DIMENSIONS}))"
HALFVEC_INDEX_ELEMENT = f"({HALFVEC_EXPRESSION} halfvec_cosine_ops)"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX ix_documents_embedding_en ON documents "
        f"USING hnsw {HALFVEC_INDEX_ELEMENT} "
        f"WHERE language = 'en'"
    )

    # GIN, because both columns are arrays tested with the containment operator (`persona_tags @> ARRAY['student']`…
    op.execute(
        "CREATE INDEX ix_documents_persona_tags ON documents USING gin (persona_tags)"
    )
    op.execute(
        "CREATE INDEX ix_documents_account_status_tags ON documents "
        "USING gin (account_status_tags)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_account_status_tags")
    op.execute("DROP INDEX IF EXISTS ix_documents_persona_tags")
    op.execute("DROP INDEX IF EXISTS ix_documents_embedding_en")
