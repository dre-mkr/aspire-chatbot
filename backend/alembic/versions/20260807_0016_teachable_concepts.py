"""Teachable concepts: make the knowledge base something a tutor can teach from Revision ID: 0016_teachable_conc…"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0016_teachable_concepts"
down_revision: str | None = "0015_staff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Matches `app/db/models.EMBEDDING_DIMENSIONS`.
_EMBEDDING_DIMENSIONS = 3072

_STATUSES = "('draft','needs_review','approved')"


def upgrade() -> None:
    # ── the existing five rows keep their ids and gain a slug ────────────────
    op.add_column("concepts", sa.Column("slug", sa.Text(), nullable=True))
    op.execute("UPDATE concepts SET slug = id WHERE slug IS NULL")
    op.alter_column("concepts", "slug", nullable=False)

    op.add_column(
        "concepts",
        sa.Column("locale", sa.Text(), nullable=False, server_default="en"),
    )
    op.add_column("concepts", sa.Column("title", sa.Text(), nullable=True))
    op.execute("UPDATE concepts SET title = name WHERE title IS NULL")
    op.alter_column("concepts", "title", nullable=False)

    op.add_column(
        "concepts",
        sa.Column(
            "aliases",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "concepts",
        sa.Column("domain", sa.Text(), nullable=False, server_default="saving"),
    )

    # One body per band.
    for column in (
        "body_5_8",
        "body_9_12",
        "body_13_15",
        "body_16_18",
        "body_adult",
    ):
        op.add_column("concepts", sa.Column(column, sa.Text(), nullable=True))

    op.add_column("concepts", sa.Column("local_example", sa.Text(), nullable=True))
    op.add_column(
        "concepts",
        sa.Column(
            "misconceptions",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "concepts",
        sa.Column(
            "check_bank",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "concepts",
        sa.Column(
            "numeric_anchors",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "concepts",
        sa.Column(
            "widget_hints",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    # The rows this concept was built from.
    op.add_column(
        "concepts",
        sa.Column(
            "source_kb_ids",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "concepts",
        sa.Column("embedding", Vector(_EMBEDDING_DIMENSIONS), nullable=True),
    )
    op.add_column(
        "concepts",
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
    )
    op.add_column(
        "concepts",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # A synthesised concept belongs to no authored module.
    op.alter_column("concepts", "module_id", nullable=True)

    op.create_check_constraint("ck_concepts_status", "concepts", f"status in {_STATUSES}")
    op.create_unique_constraint("uq_concepts_slug_locale", "concepts", ["slug", "locale"])
    op.create_index("ix_concepts_status", "concepts", ["status"])
    op.create_index("ix_concepts_domain", "concepts", ["domain"])

    # NO vector index, deliberately, and the same decision `documents` made in migration 0009 for a different reaso…

    # ── the gap list ────────────────────────────────────────────────────────
    op.create_table(
        "concept_candidates",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("utterance", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False, server_default="en"),
        sa.Column("age_band", sa.Text(), nullable=False),
        # What retrieval found, so an author can see whether the KB already supports the concept or whether it is a con…
        sa.Column(
            "kb_ids",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("best_similarity", sa.Float(), nullable=True),
        # How many times this gap has been hit.
        sa.Column("hits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_concept_id", sa.Text(), nullable=True),
        sa.UniqueConstraint("utterance", "locale", name="uq_candidate_utterance"),
    )
    op.create_index("ix_candidates_hits", "concept_candidates", ["hits"])


def downgrade() -> None:
    op.drop_index("ix_candidates_hits", table_name="concept_candidates")
    op.drop_table("concept_candidates")

    op.drop_index("ix_concepts_domain", table_name="concepts")
    op.drop_index("ix_concepts_status", table_name="concepts")
    op.drop_constraint("uq_concepts_slug_locale", "concepts", type_="unique")
    op.drop_constraint("ck_concepts_status", "concepts", type_="check")

    # Back to NOT NULL.
    op.execute("DELETE FROM concepts WHERE module_id IS NULL")
    op.alter_column("concepts", "module_id", nullable=False)

    for column in (
        "created_at",
        "status",
        "embedding",
        "source_kb_ids",
        "widget_hints",
        "numeric_anchors",
        "check_bank",
        "misconceptions",
        "local_example",
        "body_adult",
        "body_16_18",
        "body_13_15",
        "body_9_12",
        "body_5_8",
        "domain",
        "aliases",
        "title",
        "locale",
        "slug",
    ):
        op.drop_column("concepts", column)
