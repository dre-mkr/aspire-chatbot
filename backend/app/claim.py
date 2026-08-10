"""Carrying an anonymous session's work into the account that claims it."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ACCOUNT_ANONYMOUS
from app.db.models import Conversation, User

logger = logging.getLogger(__name__)


class ClaimRefused(Exception):
    """The anonymous identity cannot be claimed, and why."""


async def claim_anonymous(
    db: AsyncSession, *, anonymous_id: uuid.UUID, account_id: uuid.UUID
) -> int:
    """Move everything owned by an anonymous identity onto an account."""
    if anonymous_id == account_id:
        raise ClaimRefused("An identity cannot claim itself.")

    # Locked for the duration.
    anonymous = (
        await db.execute(
            select(User).where(User.id == anonymous_id).with_for_update()
        )
    ).scalar_one_or_none()

    if anonymous is None:
        raise ClaimRefused("That session no longer exists.")
    if anonymous.account_type != ACCOUNT_ANONYMOUS:
        # A registered account is not somebody else's to absorb.
        raise ClaimRefused("Only an anonymous session can be claimed.")
    if anonymous.claimed_by_user_id is not None:
        raise ClaimRefused("That session has already been claimed.")

    account = await db.get(User, account_id)
    if account is None:
        raise ClaimRefused("The account to claim into does not exist.")

    moved = (
        await db.execute(
            update(Conversation)
            .where(Conversation.owner_id == anonymous_id)
            .values(owner_id=account_id)
        )
    ).rowcount or 0

    now = datetime.now(timezone.utc)
    anonymous.claimed_by_user_id = account_id
    anonymous.claimed_at = now
    # Every token already minted for the anonymous identity stops working here.
    anonymous.session_epoch = anonymous.session_epoch + 1
    account.last_seen_at = now

    logger.info(
        "claimed anonymous=%s into account=%s conversations=%d",
        anonymous_id,
        account_id,
        moved,
    )
    return moved


async def claimable(db: AsyncSession, anonymous_id: uuid.UUID) -> bool:
    """Whether this identity is an unclaimed anonymous one."""
    row = (
        await db.execute(
            select(User.account_type, User.claimed_by_user_id).where(User.id == anonymous_id)
        )
    ).one_or_none()
    if row is None:
        return False
    account_type, claimed_by = row
    return account_type == ACCOUNT_ANONYMOUS and claimed_by is None


async def anonymous_conversation_count(db: AsyncSession, anonymous_id: uuid.UUID) -> int:
    """How much would be carried over. Shown before asking someone to sign out."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.owner_id == anonymous_id)
        )
    ) or 0
