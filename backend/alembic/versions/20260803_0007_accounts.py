"""Registered accounts, and the tokens that let people back into them Revision ID: 0007_accounts Revises: 0006_u…"""

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
        # The hash, never the token.
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
