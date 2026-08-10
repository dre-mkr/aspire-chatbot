"""The account's role: who signed up, as distinct from how old they are

Revision ID: 0017_account_role
Revises: 0016_teachable_concepts
Create Date: 2026-08-08

## Why a date of birth was not enough

`graph/account.py` derived everything from `users.date_of_birth`: the age band,
and through `DEFAULT_PERSONA`, the persona. That works for a participant and
fails for everybody else, because the sign-up form asks for one date of birth in
the second person ("Your date of birth decides which version of ASPIRE you get")
and never asks whose account this is.

So a parent filling it in for a child had two readings of the same field and no
way to tell which was wanted. Entering the child's date produced an account in a
child band, and the parent was then permanently unable to reach `register_agent`
-- which lives on `aurora` alone, and `aurora` is not narrower than a child
band's persona, so the request to switch was refused. Observed:

    WARNING app.api.stream: Refused a request for persona 'aurora'
    on a 16-18 band session.

The remedy is to ask the question rather than infer it. `role` records the
answer; the date of birth goes back to meaning one thing, the age of the person
holding the account.

## This column does not grant anything

Worth stating because it is the obvious thing to fear from a self-declared role.
`access.allowed_agents` is unchanged and does not read this column. Role picks a
*candidate* persona, and the candidate is honoured only when it survives
`account._narrowing` against the band's default -- the same check that already
governs a client's persona request. An `educator` in a 13-15 band still gets
Orion, because Nova's unfiltered `qa_agent` is wider than Orion's
`qa_agent_limited`.

What stops a child claiming `guardian` is therefore not this column. It is that
the claim buys nothing on its own: a guardian account needs an adult date of
birth, which `accounts.register` now requires and refuses at sign-up.

## Backfill

`participant` for every existing row, which is what the product assumed before
this column existed. Nullable would have been the other option and is worse: a
null role would have to mean "unknown", and every reader would need a policy for
it. There is a correct answer for the existing rows and it is written down.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_account_role"
down_revision: str | None = "0016_teachable_concepts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The closed set, duplicated as a literal for the same reason the access
#: matrix duplicates its vocabularies: a migration describes the schema as it
#: was when it ran, and must not change meaning because an enum moved later.
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
    # A check constraint rather than a native enum. Adding a value to a Postgres
    # enum is a migration with a lock; adding one here is an edit to this
    # constraint, and the set is small and product-shaped enough that it will
    # move again.
    op.create_check_constraint(
        "ck_users_role",
        "users",
        f"role in {_ROLES}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
