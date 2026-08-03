"""Carrying an anonymous session's work into the account that claims it.

Somebody arrives, asks four questions, plays a word scramble, and then decides
to sign up. Everything they just did belongs to an anonymous identity. If
registering loses it, registering is a punishment.

So this runs on the way into an account, and it is the part of the feature most
worth getting exactly right.

## What it guarantees

**All or nothing.** The reassignment happens in one transaction. A partial merge
that moves half the conversations is worse than no merge at all: it looks like
success and quietly loses work, and nobody discovers it until they go looking
for a chat that is gone.

**Once, ever.** An anonymous identity records who claimed it. A second attempt
is refused rather than repeated — otherwise replaying a captured anonymous token
would let somebody move records into an account of their choosing, which is the
same shape of hole as the one 0006 closed.

**The old token dies.** Claiming bumps the anonymous identity's `session_epoch`,
so every token minted for it stops working immediately. A browser holding the
old one cannot keep writing to an identity that no longer owns anything.

## Signing into an account that already exists

Merge, not discard. Somebody with an account who asks a few questions before
signing in has done real work in that session, and their existing history is not
a reason to throw it away — the two sets of conversations are both theirs. The
alternative is a warning nobody reads followed by silent loss.

The cost is that a shared device can move one person's anonymous chats into
another person's account: whoever signs in gets what that browser did while
signed out. That is the same trade the anonymous session itself makes, and it is
the reason sign-out issues a brand-new anonymous identity rather than resurrect
the previous one.
"""

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
    """Move everything owned by an anonymous identity onto an account.

    Returns how many conversations moved. Runs inside the caller's transaction
    so that it commits with the sign-up or sign-in that triggered it: an account
    created but not given its history, or history moved to an account that then
    failed to be created, are both worse than the operation not happening.

    Raises `ClaimRefused` rather than returning quietly, because every refusal
    here is something the caller has to decide about rather than ignore.
    """
    if anonymous_id == account_id:
        raise ClaimRefused("An identity cannot claim itself.")

    # Locked for the duration. Two tabs finishing sign-up at the same moment
    # would otherwise both read "unclaimed" and both try to move the rows.
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
    # Without this, the browser that just signed up could keep writing to an
    # identity that owns nothing.
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
    """Whether this identity is an unclaimed anonymous one.

    Used to decide whether to attempt a claim at all, so that a stale token in a
    browser does not turn an otherwise fine sign-in into an error.
    """
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
