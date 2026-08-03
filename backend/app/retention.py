"""Deleting anonymous conversations that nobody can come back for.

Anonymous access is the point of this product: a child opens it and asks a
question without an account. The cost is that those conversations accumulate
against identities nobody can ever sign in as. Keeping them forever is not
neutral — it is a growing pile of children's questions with no owner to ask for
them back and nobody to delete them.

So they expire. `ANONYMOUS_RETENTION_DAYS` (default 180) after the conversation
was last touched, an unclaimed anonymous identity and everything hanging off it
is deleted, and the deletion cascades to its messages.

## What is deliberately NOT deleted

**Claimed identities.** Once an anonymous session has been merged into an
account, its conversations belong to a person who can sign in — they are that
account's history now and are covered by the account's own lifetime, not this.

**Registered accounts.** Nothing here touches them.

**Recently active sessions.** The window runs from `updated_at` on the
conversation, not from when the identity was created, so somebody who has used
the same browser for a year without signing up does not lose the chat they were
reading yesterday.

## Why a cron rather than a sweep on read

A read-time check would put a delete in the path of somebody waiting for an
answer, and would only ever clean up identities that came back — which is
exactly the set that does not need cleaning. This runs nightly, off the request
path, and reports what it did.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.auth import ACCOUNT_ANONYMOUS
from app.config import get_settings
from app.db import database_enabled, session
from app.db.models import Conversation, User

logger = logging.getLogger(__name__)


async def sweep_anonymous(*, dry_run: bool = False) -> dict[str, int]:
    """Delete expired anonymous identities. Returns what it found.

    Safe to run repeatedly and safe to run concurrently: the criteria are all
    absolute, so a second pass simply finds nothing left to do.
    """
    settings = get_settings()
    days = settings.anonymous_retention_days
    if not database_enabled() or days <= 0:
        return {"users": 0, "conversations": 0, "skipped": 1}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with session() as db:
        if db is None:
            return {"users": 0, "conversations": 0, "skipped": 1}

        # An anonymous identity is expired when it has never been claimed and
        # its newest conversation is older than the window. `NOT EXISTS` rather
        # than a join on MAX(): one recent conversation is enough to keep the
        # whole identity, and this stops at the first it finds.
        recent = (
            select(Conversation.id)
            .where(
                Conversation.owner_id == User.id,
                Conversation.updated_at >= cutoff,
            )
            .exists()
        )
        expired = (
            select(User.id)
            .where(
                User.account_type == ACCOUNT_ANONYMOUS,
                User.claimed_by_user_id.is_(None),
                User.created_at < cutoff,
                ~recent,
            )
            .scalar_subquery()
        )

        doomed = list((await db.execute(select(User.id).where(User.id.in_(expired)))).scalars())
        if not doomed:
            return {"users": 0, "conversations": 0, "skipped": 0}

        conversations = (
            await db.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.owner_id.in_(doomed))
            )
        ) or 0

        if dry_run:
            logger.info(
                "retention dry run: %d anonymous identities, %d conversations would go",
                len(doomed),
                conversations,
            )
            return {"users": len(doomed), "conversations": conversations, "skipped": 0}

        # One statement. Messages go with the conversation and conversations go
        # with the user, both by ON DELETE CASCADE, so there is no order to get
        # wrong and no window where a message outlives its thread.
        await db.execute(delete(User).where(User.id.in_(doomed)))

    # Counts only. Which identities, or anything they asked, is precisely what
    # this job exists to stop keeping.
    logger.info(
        "retention: removed %d anonymous identities and %d conversations older than %d days",
        len(doomed),
        conversations,
        days,
    )
    return {"users": len(doomed), "conversations": conversations, "skipped": 0}


async def retention_job(ctx: dict) -> str:
    """The nightly entry point, for arq."""
    result = await sweep_anonymous()
    return f"users={result['users']} conversations={result['conversations']}"
