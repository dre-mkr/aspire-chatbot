"""Vector and tag indexes for documents

Revision ID: 0002_indexes
Revises: 0001_documents
Create Date: 2026-08-01

Read the halfvec note below before changing anything here.

HNSW rather than IVFFlat, as specified: IVFFlat's lists are trained against the
data present when the index is built, so it needs rebuilding as the corpus
grows. HNSW does not.

PARTIAL PER LANGUAGE, not one global index plus a filter. Filtered vector search
is HNSW's weak spot -- the graph walk finds nearest neighbours and only then are
they tested against the WHERE clause, so a selective filter can spend `ef_search`
on rows that get discarded and the query under-returns. A partial index per
language gives each partition its own graph and clean recall inside it.

ONLY `en` IS BUILT. The knowledge base is 332 English rows with no Spanish or
French content, so an `es` or `fr` index would cover zero rows -- and building
an index for content that does not exist is how you end up believing you have
multilingual retrieval. When real per-language content lands, one more migration
adds them:

    CREATE INDEX ix_documents_embedding_es ON documents
      USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
      WHERE language = 'es';

MAINTENANCE_WORK_MEM IS DELIBERATELY NOT SET. That guidance is for indexes that
do not fit the default budget; this one is 332 vectors and builds in well under
a second. Setting a large value would be cargo cult, and on Neon it takes memory
from a compute sized for the workload. Revisit above roughly 100k chunks.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_indexes"
down_revision: str | None = "0001_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 3072

# pgvector indexes the `vector` type up to 2000 dimensions. This project embeds
# with text-embedding-3-large at 3072, which STORES fine but cannot take an HNSW
# or IVFFlat index directly -- `CREATE INDEX ... USING hnsw (embedding ...)`
# fails with "column cannot have more than 2000 dimensions for hnsw index".
#
# The supported route is `halfvec`, which indexes up to 4000. It is half
# precision, so this is an approximation of an approximation; the recall cost at
# this dimensionality is small, and it is the only way to index 3072 at all.
#
# THE QUERY MUST USE THE SAME EXPRESSION or the planner will not use this index
# and will silently fall back to a sequential scan -- no error, no warning, just
# latency discovered months later. The retrieval code added in a later step
# casts identically and says so in the same words.
#
# Note the doubled parentheses and where the operator class sits. An expression
# index wraps the expression in its own parens, and the opclass goes INSIDE the
# index-element list with it:
#
#     USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
#
# Writing `USING hnsw (expr) halfvec_cosine_ops` -- opclass outside -- is a
# plain syntax error at the `::`, which is a confusing place to be pointed at
# when the real fault is a paren two tokens later.
HALFVEC_EXPRESSION = f"(embedding::halfvec({EMBEDDING_DIMENSIONS}))"
HALFVEC_INDEX_ELEMENT = f"({HALFVEC_EXPRESSION} halfvec_cosine_ops)"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX ix_documents_embedding_en ON documents "
        f"USING hnsw {HALFVEC_INDEX_ELEMENT} "
        f"WHERE language = 'en'"
    )

    # GIN, because both columns are arrays tested with the containment operator
    # (`persona_tags @> ARRAY['student']`). A b-tree cannot answer that.
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
