"""Learners, mastery, learning sessions and badges Revision ID: 0012_mastery Revises: 0011_curriculum Create Dat…"""

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
        # Nullable, and that is a feature: an anonymous visitor trying `learning_sample` is a learner for the length of…
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
    # One learner per account.
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
        # Counted separately: "correct with no hints" and "correct after hints" are different evidence and produce diff…
        sa.Column("hinted_attempts", sa.Integer(), nullable=False, server_default="0"),
        # Widget interactions are EXPOSURE, never mastery.
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
