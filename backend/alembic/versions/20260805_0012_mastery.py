"""Learners, mastery, learning sessions and badges

Revision ID: 0012_mastery
Revises: 0011_curriculum
Create Date: 2026-08-05

## The scale is 0-3 and it is never shown to a child

    0 unseen | 1 exposed | 2 practised | 3 mastered

It drives scheduling, placement and which concepts resurface inside later
checks. A child sees a streak, a badge and a mascot level; they never see a
number against a concept, because the moment they do, a lesson becomes a grade
and the product becomes something to be anxious about.

## `attempts` and `hinted_attempts` are both counted

The transition rules distinguish "correct with no hints" (+1) from "correct
after hints" (no change), so both have to be recorded. Storing only a total
would make the two indistinguishable a week later, and the whole point of the
distinction is that a child who needed the ladder has been exposed to the idea
rather than shown they hold it.

## `next_due` is a real column, not a computed one

Spaced repetition intervals are 1, 3, 7 and 21 days by score. Computing the due
date on read would mean it moves when the rules are tuned, retroactively, for
every learner -- so a change to the schedule would silently declare thousands
of concepts overdue. Written once, at review time, from the rules in force then.

## No `mastery_history` table

Deliberate. This is a children's learning product, not an assessment system,
and a per-attempt audit trail of a child's wrong answers is a record nobody
should be keeping. The current score and its counters are what scheduling
needs; the wrong answers are not retained.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_mastery"
down_revision: str | None = "0011_curriculum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BANDS = "('5-8','9-12','13-15','16-18','adult')"


def upgrade() -> None:
    op.create_table(
        "learners",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Nullable, and that is a feature: an anonymous visitor trying
        # `learning_sample` is a learner for the length of that session. Their
        # row is cleaned up by the retention job like any other anonymous data.
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("age_band", sa.Text(), nullable=False),
        sa.Column("mascot_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_session_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(f"age_band in {_BANDS}", name="ck_learners_band"),
        sa.CheckConstraint("streak >= 0", name="ck_learners_streak"),
    )
    # One learner per account. A second row for the same user would split their
    # mastery in half and neither half would be right.
    op.create_index(
        "uq_learners_user",
        "learners",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id is not null"),
    )

    op.create_table(
        "mastery",
        sa.Column(
            "learner_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learners.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "concept_id",
            sa.Text(),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("score_0_3", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        # Counted separately: "correct with no hints" and "correct after hints"
        # are different evidence and produce different transitions.
        sa.Column("hinted_attempts", sa.Integer(), nullable=False, server_default="0"),
        # Widget interactions are EXPOSURE, never mastery. Counted so the
        # invariant "a widget-only learner never exceeds 1" can be asserted
        # against real rows rather than only in a unit test.
        sa.Column("widget_touches", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "score_0_3 between 0 and 3", name="ck_mastery_score_range"
        ),
    )
    # The scheduler's query: what is due for this learner, soonest first.
    op.create_index(
        "ix_mastery_due",
        "mastery",
        ["learner_id", "next_due"],
        postgresql_where=sa.text("next_due is not null"),
    )

    op.create_table(
        "sessions_learning",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "learner_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("module_id", sa.Text(), nullable=True),
        sa.Column("lesson_id", sa.Text(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "completed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("duration_s >= 0", name="ck_sessions_duration"),
    )
    op.create_index(
        "ix_sessions_learner", "sessions_learning", ["learner_id", "started_at"]
    )

    op.create_table(
        "badges",
        sa.Column(
            "learner_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learners.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("badge_id", sa.Text(), primary_key=True),
        sa.Column(
            "earned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Which real ASPIRE milestone this corresponds to, where there is one.
        # Badges tied to a first deposit or a first EC$100 saved mean something
        # outside the app; badges tied to app activity mean the child opened the
        # app.
        sa.Column("milestone", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("badges")
    op.drop_index("ix_sessions_learner", table_name="sessions_learning")
    op.drop_table("sessions_learning")
    op.drop_index("ix_mastery_due", table_name="mastery")
    op.drop_table("mastery")
    op.drop_index("uq_learners_user", table_name="learners")
    op.drop_table("learners")
