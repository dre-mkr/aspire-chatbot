"""Users, and conversations owned by them

Revision ID: 0006_users
Revises: 0005_conversation_owner
Create Date: 2026-08-03

0005 recorded ownership as a string principal read straight off an
`X-Aspire-Device` header. That was an IDOR: the header is not a secret, it is
sent on every request and sits in the browser's own storage, so anyone holding
another person's device id could read their conversations. This replaces it.

Identity is now a row. An anonymous visitor and a registered account are the
same kind of thing in the same table, differing by `account_type` -- so
conversations, and everything else that hangs off a person, attach the same way
for both and there is no second storage path to keep in step.

`device_id` is recorded but is deliberately **not unique and not a lookup key
for authentication**. It seeds the creation of an anonymous user and is kept for
abuse investigation. Nothing may exchange it for a session; see `auth.py`.

The backfill turns each distinct `device:*` principal into an anonymous user, so
conversations written yesterday keep their owner. `owner_key` is dropped rather
than left alongside: it is one day old, and a column that still authorises
anything is the bug this migration exists to remove.
"""

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
        # Bumped to invalidate every token already issued for this user: on
        # claim, and on sign-out. A token carries the epoch it was minted under
        # and is refused once they disagree, so revocation needs no denylist and
        # no shared cache.
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="1"),
        # Set when an anonymous identity has been merged into an account. Its
        # presence is what makes a second claim impossible.
        sa.Column("claimed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        # Salted hash, not the address. Enough to spot one source creating a
        # thousand sessions; not a record of where a child lives.
        sa.Column("created_ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["claimed_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )

    # One account per address, case-insensitively — "A@b.com" and "a@b.com" are
    # the same person trying to sign in twice. Partial, because anonymous rows
    # have no email and there are many of them.
    op.create_index(
        "ux_users_email",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    # For abuse investigation only. Deliberately not unique: two sessions from
    # one browser are two identities, and making this unique would recreate the
    # "hand me a device id and I will hand you its account" hole.
    op.create_index("ix_users_device_id", "users", ["device_id"])
    op.create_index("ix_users_created_at", "users", ["created_at"])

    op.add_column("conversations", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_conversations_owner", "conversations", "users", ["owner_id"], ["id"], ondelete="CASCADE"
    )

    # Every conversation written under 0005 keeps its owner: one anonymous user
    # per distinct device principal, then the rows point at it.
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
