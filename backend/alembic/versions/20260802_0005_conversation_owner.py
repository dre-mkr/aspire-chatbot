"""Who a conversation belongs to Revision ID: 0005_conversation_owner Revises: 0004_eligibility_outcomes Create…"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_conversation_owner"
down_revision: str | None = "0004_eligibility_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("owner_key", sa.String(length=160), nullable=True),
    )
    # Where the title came from, and therefore whether generation may replace it.
    op.add_column(
        "conversations",
        sa.Column("title_source", sa.String(length=16), nullable=True),
    )
    # Every read of this table by a person is "my conversations, newest first".
    op.create_index(
        "ix_conversations_owner_updated",
        "conversations",
        ["owner_key", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_column("conversations", "title_source")
    op.drop_column("conversations", "owner_key")
