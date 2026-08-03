"""Registered accounts, and the tokens that let people back into them

Revision ID: 0007_accounts
Revises: 0006_users
Create Date: 2026-08-03

0006 made identity a row. This fills in what a registered account needs beyond
an id: a name, the details sign-up collects, and somewhere to put the one-time
tokens behind password reset, email verification and the sign-in link.

## About the child columns

`date_of_birth`, `island`, `school` and the guardian contact fields exist
because the sign-up flow asks for them: date of birth decides which version of
ASPIRE somebody gets, and an under-13 account is held by the guardian named
during sign-up rather than by the child.

That is a deliberate reversal of the posture the eligibility flow holds, where a
minor's answers never leave the device. It was asked for explicitly. Two things
follow from it and are enforced here rather than left to the callers:

* The columns are nullable and stay empty for anyone who does not volunteer
  them. Nothing in the product requires them to be filled to hold an account.
* `guardian_*` is contact detail for a named adult, not a second identity.
  Nobody signs in with it.

`is_minor` is stored rather than recomputed from the birth date on every read,
because a birthday must not silently change what somebody is allowed to see
half-way through a session. It is refreshed deliberately, not incidentally.

## Tokens

One table for reset, verification and sign-in links, distinguished by `purpose`.
Only a hash is stored -- a leaked table must not be a set of working links --
and `used_at` makes each one single-use.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_accounts"
down_revision: str | None = "0006_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("is_minor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("island", sa.Text(), nullable=True),
        sa.Column("school", sa.Text(), nullable=True),
        sa.Column("guardian_name", sa.Text(), nullable=True),
        sa.Column("guardian_email", sa.Text(), nullable=True),
        sa.Column("guardian_phone", sa.Text(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("users", column)

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # "reset" | "verify" | "signin_link"
        sa.Column("purpose", sa.String(length=16), nullable=False),
        # The hash, never the token. A leaked table must not be a set of working
        # links, and nothing needs to read one back — only to recognise it.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    # The lookup every redemption does: find this exact token, once.
    op.create_index("ux_auth_tokens_hash", "auth_tokens", ["token_hash"], unique=True)
    op.create_index("ix_auth_tokens_user_purpose", "auth_tokens", ["user_id", "purpose"])


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_user_purpose", table_name="auth_tokens")
    op.drop_index("ux_auth_tokens_hash", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    for name in (
        "email_verified_at",
        "guardian_phone",
        "guardian_email",
        "guardian_name",
        "school",
        "island",
        "is_minor",
        "date_of_birth",
        "last_name",
        "first_name",
    ):
        op.drop_column("users", name)
