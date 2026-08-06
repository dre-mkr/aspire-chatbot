"""Curriculum: modules, lessons, concepts and their prerequisites

Revision ID: 0011_curriculum
Revises: 0010_tickets
Create Date: 2026-08-05

## Why the curriculum is in the database at all when the YAML is the source

It is not a second copy of the content. These tables hold the SPINE -- ids,
ordering, band ranges, prerequisite edges -- and nothing that a person authors
in prose. Teach points, examples and hints stay in YAML, in git, where they are
reviewed.

The spine is here because three things need to join against it and cannot join
against a file: mastery rows point at `concepts.id`, the learning session log
points at `lessons.id`, and the admin portal's progress views group by module.
Foreign keys are the point -- a mastery row for a concept that no longer exists
should fail on insert, not surface as a blank name in a report.

`app/curriculum/loader` upserts this from the YAML at startup. The YAML wins on
every field it owns; nothing writes prose here.

## `concept_prerequisites` is a table, not an array column

A prerequisite is an edge, and edges get queried in both directions: "what does
this concept need?" and "what unlocks once this is mastered?". An array answers
the first cheaply and the second not at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_curriculum"
down_revision: str | None = "0010_tickets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Bands, as a check constraint rather than a Postgres ENUM.
#:
#: An ENUM would be tidier and would need a migration to add a value. A check
#: constraint needs one too -- but it is a constraint swap rather than an
#: `ALTER TYPE`, which cannot run inside a transaction on older Postgres and so
#: cannot be rolled back with the rest of a deploy.
_BANDS = "('5-8','9-12','13-15','16-18','adult')"


def upgrade() -> None:
    op.create_table(
        "modules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("band_min", sa.Text(), nullable=False),
        sa.Column("band_max", sa.Text(), nullable=False, server_default="adult"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(f"band_min in {_BANDS}", name="ck_modules_band_min"),
        sa.CheckConstraint(f"band_max in {_BANDS}", name="ck_modules_band_max"),
        sa.UniqueConstraint("order_index", name="uq_modules_order"),
    )

    op.create_table(
        "concepts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("band_min", sa.Text(), nullable=False),
        sa.Column("band_max", sa.Text(), nullable=False, server_default="adult"),
        sa.Column(
            "module_id",
            sa.Text(),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The words this concept introduces. An array is right here and not for
        # prerequisites: nothing ever asks "which concepts introduce the word
        # 'budget'?", it only ever reads the list for one concept.
        sa.Column(
            "vocabulary",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.CheckConstraint(f"band_min in {_BANDS}", name="ck_concepts_band_min"),
        sa.CheckConstraint(f"band_max in {_BANDS}", name="ck_concepts_band_max"),
    )
    op.create_index("ix_concepts_module", "concepts", ["module_id"])
    op.create_index("ix_concepts_band", "concepts", ["band_min", "band_max"])

    op.create_table(
        "concept_prerequisites",
        sa.Column(
            "concept_id",
            sa.Text(),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "requires_id",
            sa.Text(),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # A concept requiring itself is an infinite loop in the placement step
        # and is trivially preventable here.
        sa.CheckConstraint("concept_id <> requires_id", name="ck_prereq_not_self"),
    )
    # The reverse direction: "what unlocks once this is mastered?" It is the
    # query the placement step actually runs, and without this index it is a
    # sequential scan on every lesson turn.
    op.create_index(
        "ix_prereq_reverse", "concept_prerequisites", ["requires_id"]
    )

    op.create_table(
        "lessons",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "module_id",
            sa.Text(),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "concept_id",
            sa.Text(),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_widget_kind", sa.Text(), nullable=True),
        sa.UniqueConstraint("module_id", "order_index", name="uq_lessons_order"),
    )
    op.create_index("ix_lessons_concept", "lessons", ["concept_id"])


def downgrade() -> None:
    op.drop_index("ix_lessons_concept", table_name="lessons")
    op.drop_table("lessons")
    op.drop_index("ix_prereq_reverse", table_name="concept_prerequisites")
    op.drop_table("concept_prerequisites")
    op.drop_index("ix_concepts_band", table_name="concepts")
    op.drop_index("ix_concepts_module", table_name="concepts")
    op.drop_table("concepts")
    op.drop_table("modules")
