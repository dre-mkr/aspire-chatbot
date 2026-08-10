"""Users, and conversations owned by them Revision ID: 0006_users Revises: 0005_conversation_owner Create Date:…"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_users"
down_revision: str | None = "0005_conversation_owner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # "anonymous" | "registered". One table, one set of relationships.
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        # The seed an anonymous identity was created from. Never a credential.
        sa.Column("device_id", sa.String(length=64), nullable=True),
        # Bumped to invalidate every token already issued for this user: on claim, and on sign-out.
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="1"),
        # Set when an anonymous identity has been merged into an account.
        sa.Column("claimed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        # Salted hash, not the address.
        sa.Column("created_ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["claimed_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )

    # One account per address, case-insensitively — "A@b.com" and "a@b.com" are the same person trying to sign in t…
    op.create_index(
        "ux_users_email",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    # For abuse investigation only.
    op.create_index("ix_users_device_id", "users", ["device_id"])
    op.create_index("ix_users_created_at", "users", ["created_at"])

    op.add_column("conversations", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_conversations_owner", "conversations", "users", ["owner_id"], ["id"], ondelete="CASCADE"
    )

    # Every conversation written under 0005 keeps its owner: one anonymous user per distinct device principal, then…
    op.execute(
        """
        INSERT INTO users (id, account_type, device_id, session_epoch, created_at, last_seen_at)
        SELECT gen_random_uuid(),
               'anonymous',
               substring(owner_key from 8),
               1,
               now(),
               now()
        FROM (SELECT DISTINCT owner_key FROM conversations
              WHERE owner_key LIKE 'device:%') AS seeds
        """
    )
    op.execute(
        """
        UPDATE conversations c
        SET owner_id = u.id
        FROM users u
        WHERE c.owner_key = 'device:' || u.device_id
        """
    )

    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_column("conversations", "owner_key")
    op.create_index(
        "ix_conversations_owner_updated",
        "conversations",
        ["owner_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.add_column("conversations", sa.Column("owner_key", sa.String(length=160), nullable=True))
    op.execute(
        """
        UPDATE conversations c
        SET owner_key = 'device:' || u.device_id
        FROM users u
        WHERE c.owner_id = u.id AND u.device_id IS NOT NULL
        """
    )
    op.create_index(
        "ix_conversations_owner_updated",
        "conversations",
        ["owner_key", sa.text("updated_at DESC")],
    )
    op.drop_constraint("fk_conversations_owner", "conversations", type_="foreignkey")
    op.drop_column("conversations", "owner_id")
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_device_id", table_name="users")
    op.drop_index("ux_users_email", table_name="users")
    op.drop_table("users")
