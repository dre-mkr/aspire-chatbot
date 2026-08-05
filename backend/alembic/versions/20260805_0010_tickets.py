"""Escalation tickets

Revision ID: 0010_tickets
Revises: 0009_documents_live
Create Date: 2026-08-05

Where a conversation goes when a person has to take it.

## Why `summary` is text and not a foreign key to the transcript

A ticket is a working record for staff: it is read in a queue, exported to a
case system, and joined to whatever the reviewer is already looking at. Pointing
it at the conversation would mean every one of those readers has access to the
full transcript of a child's session, including the parts that have nothing to
do with why the ticket exists.

So the ticket carries its own summary, redacted at the point of writing (see
`app/agents/escalate/graph.py`), and the transcript stays where it is.

## `notify_guardian`

Set when a minor's escalation needs a named adult told as well as the staff
queue. It is a column rather than a derived value because who was notified, and
when, is the sort of thing that gets asked about months later -- and re-deriving
it from an age band that has since changed would give the wrong answer.

## No `assigned_to` foreign key

Staff identity lives in the admin realm, which has its own auth and its own
tables. A nullable text column here keeps this table usable before that exists
and avoids a cross-realm constraint that would have to be dropped later.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_tickets"
down_revision: str | None = "0009_documents_live"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        # Human-readable and human-quotable: this string is read out on the
        # phone. A UUID would be correct and unusable.
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("category", sa.Text(), nullable=False, server_default="general"),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column(
            "notify_guardian", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        # Kept so a queue can be filtered to minors without joining anything.
        # It is the band AT ESCALATION, which is the one that mattered.
        sa.Column("age_band", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column("assigned_to", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "priority in ('low','normal','high')", name="ck_tickets_priority"
        ),
        sa.CheckConstraint(
            "status in ('open','in_progress','resolved','closed')",
            name="ck_tickets_status",
        ),
    )

    # The queue's own query: open tickets, most urgent first, oldest first
    # within a priority. Indexed as it is read rather than column by column.
    op.create_index(
        "ix_tickets_queue",
        "tickets",
        ["status", "priority", "created_at"],
    )
    op.create_index("ix_tickets_session", "tickets", ["session_id"])
    # Partial: the safeguarding view is a small slice of a large table and is
    # opened under time pressure.
    op.create_index(
        "ix_tickets_guardian_alerts",
        "tickets",
        ["created_at"],
        postgresql_where=sa.text("notify_guardian"),
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_guardian_alerts", table_name="tickets")
    op.drop_index("ix_tickets_session", table_name="tickets")
    op.drop_index("ix_tickets_queue", table_name="tickets")
    op.drop_table("tickets")
