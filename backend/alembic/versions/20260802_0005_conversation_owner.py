"""Who a conversation belongs to

Revision ID: 0005_conversation_owner
Revises: 0004_eligibility_outcomes
Create Date: 2026-08-02

Transcripts have been written to `conversations` since 0003, but nothing has
ever been able to read them back, because nothing recorded whose they were. The
rail lists a person's chats out of localStorage for exactly that reason.

`owner_key` is that missing half, and it is one column rather than a `users`
table on purpose. It stores a *namespaced principal*:

    device:9f1c...   an anonymous browser that has never signed in
    user:1042        a signed-in account, once accounts exist

so that adding real accounts later is a new prefix and a backfill, not a second
migration against a table with rows in it. The same read path serves both, and
"list my conversations" is one indexed equality either way.

Nullable, because every row that exists today predates ownership. Those rows
stay unreadable by the list endpoint, which is the correct outcome: nobody can
prove they own them, so nobody is shown them.
"""

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
    # Where the title came from, and therefore whether generation may replace
    # it. The client has tracked this since titles existed; it only ever lived
    # in localStorage because that is where conversations lived. Moving the
    # conversation without it would let a background title call overwrite a name
    # somebody typed by hand.
    op.add_column(
        "conversations",
        sa.Column("title_source", sa.String(length=16), nullable=True),
    )
    # Every read of this table by a person is "my conversations, newest first".
    # Ordering in the index means the rail's query never sorts.
    op.create_index(
        "ix_conversations_owner_updated",
        "conversations",
        ["owner_key", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_column("conversations", "title_source")
    op.drop_column("conversations", "owner_key")
