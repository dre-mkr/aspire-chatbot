"""Staff accounts for the admin realm Revision ID: 0015_staff Revises: 0014_applications Create Date: 2026-08-05…"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_staff"
down_revision: str | None = "0014_applications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False, server_default=""),
        # bcrypt.
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="reviewer"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        # Bumped to revoke every token already issued for this person, the same mechanism `users.session_epoch` uses.
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role in ('reviewer','supervisor','admin')", name="ck_staff_role"
        ),
    )
    # Case-insensitive, because a reviewer will type `Rachel@` on Monday and `rachel@` on Tuesday and both must be…
    op.create_index(
        "uq_staff_email", "staff", [sa.text("lower(email)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_staff_email", table_name="staff")
    op.drop_table("staff")
