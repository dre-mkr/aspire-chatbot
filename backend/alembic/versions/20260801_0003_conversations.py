"""Conversations and messages, with the running summary column

Revision ID: 0003_conversations
Revises: 0002_indexes
Create Date: 2026-08-01

Full-fidelity transcript storage. Nothing writes to these tables yet -- that is
the next step. `summary` and `summarized_through_seq` are created now, unused,
so that the memory change is a code change rather than a second migration
against a table that already has rows in it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_conversations"
down_revision: str | None = "0002_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        # The client's own thread id: already the URL, the localStorage key and
        # the games session key. A surrogate key would only add a lookup.
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("persona", sa.String(length=32), nullable=True),
        sa.Column("account_status", sa.String(length=32), nullable=True),
        # For the memory step. `summarized_through_seq` is how the background
        # job knows what it has already folded in; without it the job would
        # either redo everything or lose the turns in the gap.
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "summarized_through_seq", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conversations_updated_at", "conversations", [sa.text("updated_at DESC")]
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(length=128),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Monotonic within a conversation. Ordering on a timestamp would be a
        # bug waiting for two rows written in the same millisecond.
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Unique, so `seq` is a real sequence rather than a hint, and covering the
    # only read shape there is: this conversation, in order.
    op.create_index(
        "ix_messages_conversation_seq",
        "messages",
        ["conversation_id", "seq"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_seq", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_table("conversations")
