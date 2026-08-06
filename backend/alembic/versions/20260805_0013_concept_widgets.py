"""Generated concept widgets and their review state

Revision ID: 0013_concept_widgets
Revises: 0012_mastery
Create Date: 2026-08-05

## The unique index is the whole safety property

    UNIQUE (concept_id, age_band, locale) WHERE status = 'approved'

All three columns, and the partial predicate. Two approved widgets for the same
concept and band in different languages are fine and necessary; two for the same
concept, band AND language is an ambiguity the lookup would resolve by whichever
row the planner happened to return -- which is to say, differently on different
days.

Scoped to `approved` because candidates legitimately accumulate: a concept can
have a rejected row from March and a candidate from August, and forcing those to
be unique would make rejecting anything impossible without deleting the history
of why.

## `payload` is jsonb, not a set of columns

Nine widget kinds with disjoint fields is not a table. The schema lives in
`app/widgets/schemas.py` and is validated on the way IN -- by the time a row
exists it has passed seven gates, so the database's job is storage rather than
validation.

jsonb rather than json so a reviewer's edit can be a targeted update and the
admin queue can filter on `payload->>'kind'` without deserialising every row.

## `source_question` is kept, and it is the most useful column here

It is what a reviewer reads first: not "is this widget correct" in the abstract
but "does this widget answer THAT question". A queue without it is a queue of
context-free JSON.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_concept_widgets"
down_revision: str | None = "0012_mastery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BANDS = "('5-8','9-12','13-15','16-18','adult')"


def upgrade() -> None:
    op.create_table(
        "concept_widgets",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # No foreign key to `concepts`, deliberately. A widget can legitimately
        # be about a concept the curriculum later renames or retires, and a
        # cascade would delete the reviewer's work along with the concept row.
        sa.Column("concept_id", sa.Text(), nullable=False),
        sa.Column("age_band", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload", sa.dialects.postgresql.JSONB(), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="candidate"),
        # What a reviewer reads first. See the module docstring.
        sa.Column("source_question", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        # Bumped on every review, so an edit-then-approve is distinguishable
        # from an approve, and a served payload can be traced to a decision.
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        # How often the triggering concept has been asked about. The review
        # queue sorts by it, so the most-served widgets get reviewed first.
        sa.Column("serve_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status in ('candidate','approved','rejected')",
            name="ck_concept_widgets_status",
        ),
        sa.CheckConstraint(f"age_band in {_BANDS}", name="ck_concept_widgets_band"),
        sa.CheckConstraint(
            "locale in ('en','es','fr')", name="ck_concept_widgets_locale"
        ),
    )

    # THE constraint. All three axes, approved rows only.
    op.create_index(
        "uq_concept_widgets_approved",
        "concept_widgets",
        ["concept_id", "age_band", "locale"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )
    # One live candidate per key, so a regeneration replaces rather than
    # accumulates. The cache's upsert targets this index by name.
    op.create_index(
        "uq_concept_widgets_candidate",
        "concept_widgets",
        ["concept_id", "age_band", "locale"],
        unique=True,
        postgresql_where=sa.text("status = 'candidate'"),
    )
    # The lookup: every status for one key, ordered by the caller.
    op.create_index(
        "ix_concept_widgets_key",
        "concept_widgets",
        ["concept_id", "age_band", "locale", "status"],
    )
    # The review queue: candidates, most-served first.
    op.create_index(
        "ix_concept_widgets_queue",
        "concept_widgets",
        [sa.text("serve_count DESC"), "generated_at"],
        postgresql_where=sa.text("status = 'candidate'"),
    )


def downgrade() -> None:
    op.drop_index("ix_concept_widgets_queue", table_name="concept_widgets")
    op.drop_index("ix_concept_widgets_key", table_name="concept_widgets")
    op.drop_index("uq_concept_widgets_candidate", table_name="concept_widgets")
    op.drop_index("uq_concept_widgets_approved", table_name="concept_widgets")
    op.drop_table("concept_widgets")
