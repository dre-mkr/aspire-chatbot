"""The website watcher's two tables: last-seen pages, and rows awaiting review.

Revision ID: 0018_website_watcher
Revises: 0017_account_role
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_website_watcher"
down_revision: str | None = "0017_account_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_snapshots",
        sa.Column("url", sa.Text(), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "pending_kb_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kb_id", sa.String(32), nullable=False, unique=True),
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
        sa.Column("subcategory", sa.Text(), nullable=False, server_default=""),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=False, server_default=""),
        sa.Column("audience", sa.String(16), nullable=False, server_default="general"),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("as_of", sa.String(10), nullable=False),
        sa.Column("why", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("pending_kb_rows")
    op.drop_table("site_snapshots")
