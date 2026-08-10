"""Anonymised eligibility pre-check outcomes Revision ID: 0004_eligibility_outcomes Revises: 0003_conversations…"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_eligibility_outcomes"
down_revision: str | None = "0003_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eligibility_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # One of: likely_eligible, not_yet, needs_confirmation.
        sa.Column("verdict", sa.String(length=32), nullable=False),
        # What it turned on: citizenship, age_minimum, age_cohort, residence, school, or "none" for a clean pass.
        sa.Column("criterion", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # The only read shape the insight view has: counts over a date range, grouped by verdict.
    op.create_index(
        "ix_eligibility_outcomes_created_verdict",
        "eligibility_outcomes",
        ["created_at", "verdict"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eligibility_outcomes_created_verdict", table_name="eligibility_outcomes"
    )
    op.drop_table("eligibility_outcomes")
