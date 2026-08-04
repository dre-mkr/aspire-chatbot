"""Anonymous conversations expire; nothing else does.

The job deletes children's questions, so the tests that matter most are the
ones about what it must NOT touch. A retention sweep that over-reaches is not a
tidy-up, it is data loss with a schedule.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")

from sqlalchemy import select  # noqa: E402

from app.auth import ACCOUNT_ANONYMOUS, ACCOUNT_REGISTERED  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import database_enabled, dispose, session  # noqa: E402
from app.db.models import Conversation, Message, User  # noqa: E402
from app.retention import sweep_anonymous  # noqa: E402

# Driven on ONE event loop for the whole module, rather than `asyncio.run` per
# test. The async engine's connection pool belongs to the loop that created it,
# so a loop per test left later tests — here and in other files — talking to
# sockets from a loop that had already closed, surfacing as "Event loop is
# closed" somewhere with no connection to the cause.
#
# `pytest.mark.asyncio` would do this for us; this project does not carry
# pytest-asyncio, and `test_schema_guard.py` established the plain-asyncio
# pattern.
_loop = asyncio.new_event_loop()


def run(coro):
    return _loop.run_until_complete(coro)


def teardown_module(_module):
    # Dispose INSIDE the loop before closing it. The engine's asyncpg
    # connections are attached to this loop, and closing it with them still
    # pooled leaves callbacks scheduled on a dead loop — which fails in whatever
    # test runs next, with a traceback naming asyncpg and not this file.
    _loop.run_until_complete(dispose())
    _loop.close()


#: P0-010 -- see the `slow` marker note in pyproject.toml. Both markers apply:
#: this needs a live dependency AND is dominated by wall-clock cost.
pytestmark = [pytest.mark.slow, pytest.mark.skipif(
    not database_enabled(), reason="These are database-backed retention tests."
)]


async def make(
    *,
    account_type: str = ACCOUNT_ANONYMOUS,
    age_days: int,
    claimed: bool = False,
    conversation_age_days: int | None = None,
) -> tuple[uuid.UUID, str]:
    """One identity with one conversation, aged as asked."""
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    touched = datetime.now(timezone.utc) - timedelta(
        days=conversation_age_days if conversation_age_days is not None else age_days
    )
    user_id = uuid.uuid4()
    thread_id = f"t-{uuid.uuid4()}"

    async with session() as db:
        claimer = None
        if claimed:
            claimer = User(
                id=uuid.uuid4(),
                account_type=ACCOUNT_REGISTERED,
                email=f"owner.{uuid.uuid4().hex[:8]}@ecse.kn",
                session_epoch=1,
            )
            db.add(claimer)
            await db.flush()

        db.add(
            User(
                id=user_id,
                account_type=account_type,
                session_epoch=1,
                created_at=created,
                last_seen_at=created,
                claimed_by_user_id=claimer.id if claimer else None,
                claimed_at=created if claimer else None,
                email=None if account_type == ACCOUNT_ANONYMOUS else f"a.{uuid.uuid4().hex[:8]}@x.kn",
            )
        )
        await db.flush()
        db.add(
            Conversation(
                id=thread_id, owner_id=user_id, title="Saving money", created_at=created,
                updated_at=touched,
            )
        )
        await db.flush()
        db.add(Message(conversation_id=thread_id, seq=1, role="user", content="How do I save?"))

    return user_id, thread_id


async def exists(user_id: uuid.UUID) -> bool:
    async with session() as db:
        return (await db.get(User, user_id)) is not None


async def conversation_exists(thread_id: str) -> bool:
    async with session() as db:
        return (await db.get(Conversation, thread_id)) is not None


def test_an_old_unclaimed_anonymous_identity_is_removed():
    async def body():
        days = get_settings().anonymous_retention_days
        user_id, thread_id = await make(age_days=days + 30)

        result = await sweep_anonymous()
        assert result["users"] >= 1

        assert not await exists(user_id)
        # The conversation goes with it, and the messages go with the conversation.
        assert not await conversation_exists(thread_id)
        async with session() as db:
            left = (
                await db.execute(select(Message).where(Message.conversation_id == thread_id))
            ).scalars().all()
            assert left == []


    run(body())


def test_a_recent_anonymous_identity_is_kept():
    async def body():
        user_id, thread_id = await make(age_days=3)
        await sweep_anonymous()
        assert await exists(user_id)
        assert await conversation_exists(thread_id)


    run(body())


def test_an_old_identity_still_being_used_is_kept():
    async def body():
        """The window runs from the conversation, not from when the id was minted.

        Somebody who has used the same browser for a year without signing up must
        not lose the chat they were reading yesterday.
        """
        days = get_settings().anonymous_retention_days
        user_id, thread_id = await make(age_days=days + 60, conversation_age_days=2)
        await sweep_anonymous()
        assert await exists(user_id)
        assert await conversation_exists(thread_id)


    run(body())


def test_a_claimed_identity_is_never_swept():
    async def body():
        """Once merged into an account, the conversations belong to a person."""
        days = get_settings().anonymous_retention_days
        user_id, thread_id = await make(age_days=days + 90, claimed=True)
        await sweep_anonymous()
        assert await exists(user_id)
        assert await conversation_exists(thread_id)


    run(body())


def test_registered_accounts_are_never_swept():
    async def body():
        days = get_settings().anonymous_retention_days
        user_id, thread_id = await make(account_type=ACCOUNT_REGISTERED, age_days=days + 365)
        await sweep_anonymous()
        assert await exists(user_id)
        assert await conversation_exists(thread_id)


    run(body())


def test_a_dry_run_counts_without_deleting():
    async def body():
        days = get_settings().anonymous_retention_days
        user_id, _ = await make(age_days=days + 10)
        result = await sweep_anonymous(dry_run=True)
        assert result["users"] >= 1
        assert await exists(user_id)


    run(body())


def test_running_twice_is_harmless():
    async def body():
        days = get_settings().anonymous_retention_days
        await make(age_days=days + 10)
        first = await sweep_anonymous()
        second = await sweep_anonymous()
        assert first["users"] >= 1
        # Everything expired has already gone; the second pass finds nothing.
        assert second["users"] == 0

    run(body())