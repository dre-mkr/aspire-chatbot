"""The account's role: who signed up, as distinct from how old they are Revision ID: 0017_account_role Revises:…"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_account_role"
down_revision: str | None = "0016_teachable_concepts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The closed set, duplicated as a literal for the same reason the access matrix duplicates its vocabularies: a…
_ROLES = "('participant','guardian','educator')"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            server_default="participant",
        ),
    )
    # A check constraint rather than a native enum.
    op.create_check_constraint(
        "ck_users_role",
        "users",
        f"role in {_ROLES}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
