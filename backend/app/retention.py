"""Deleting anonymous conversations that nobody can come back for."""

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
    """Delete expired anonymous identities."""
    settings = get_settings()
    days = settings.anonymous_retention_days
    if not database_enabled() or days <= 0:
        return {"users": 0, "conversations": 0, "skipped": 1}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with session() as db:
        if db is None:
            return {"users": 0, "conversations": 0, "skipped": 1}

        # Expired means never claimed, created before the cutoff, and no conversation touched since.
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

        # One statement.
        await db.execute(delete(User).where(User.id.in_(doomed)))

    # Counts only.
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
