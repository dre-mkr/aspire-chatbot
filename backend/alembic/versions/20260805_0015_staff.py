"""Staff accounts for the admin realm

Revision ID: 0015_staff
Revises: 0014_applications
Create Date: 2026-08-05

A separate table from `users`, and that separation is the point rather than a
consequence.

`users` is the public chat's identity: anonymous rows are created freely, a
device id seeds one, and the whole table is designed around letting a child ask
a question without proving anything. Putting a reviewer in it would mean the
credential that opens a queue of children's identity documents lives in the same
table, under the same code paths, as a row anybody can create by loading a page.

So: its own table, its own token type (`aspire.staff`), its own sign-in
endpoint, its own session lifetime. Nothing here is reachable from the chat's
auth code and nothing there is reachable from here.

## `must_change_password`

Seeded accounts get a temporary password and this flag. A deployment where the
first reviewer's password is whatever was in the seeding command's shell history
is a deployment with one password everybody knows.

## No `last_login`

Deliberately absent. `audit_log` records every action with an actor and a
timestamp, so "when was this person last here?" is already answerable from the
record that matters. A second, less precise copy of it on the account row is a
column that drifts.
"""

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
        # bcrypt. Never nullable: an account with no password is an account that
        # `verify_password` has to have a safe answer for, and "no password
        # column" is a safer answer than "a nullable one somebody forgot".
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="reviewer"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        # Bumped to revoke every token already issued for this person, the same
        # mechanism `users.session_epoch` uses. Stateless JWTs need somewhere
        # for "sign this person out everywhere" to live, and a denylist would
        # put a cache read on the auth path of every admin request.
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
    # Case-insensitive, because a reviewer will type `Rachel@` on Monday and
    # `rachel@` on Tuesday and both must be the same account rather than a
    # second one nobody granted a role to.
    op.create_index(
        "uq_staff_email", "staff", [sa.text("lower(email)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_staff_email", table_name="staff")
    op.drop_table("staff")
