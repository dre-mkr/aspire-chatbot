"""Reading and writing conversations.

The asymmetry here is the point of the whole change:

* `append_turn` writes **everything**, forever.
* `load_context` reads a **window plus a summary**, which is all the model gets.

Streaks, analytics and account-status routing read the first. The prompt is
built from the second.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConversationContext:
    """Exactly what the model will be shown of a conversation's past."""

    summary: str | None = None
    # Oldest first, ready to append the new question to.
    recent: list = field(default_factory=list)
    # Turns that exist but are represented only by the summary. Reported so the
    # before/after token comparison can say what was actually left out.
    older_turn_count: int = 0


async def ensure_conversation(
    db: AsyncSession,
    conversation_id: str,
    *,
    language: str = "en",
    persona: str | None = None,
    account_status: str | None = None,
    owner_id: uuid.UUID | None = None,
    title: str | None = None,
) -> None:
    """Create the row on the first turn, leave it alone afterwards.

    An upsert rather than select-then-insert: two requests for a brand-new
    thread can race, and losing that race must not become an error the user
    sees.

    `owner_id` is written once, on creation, and never updated here. That is
    the point: a conversation's owner is settled by whoever started it, so a
    later request from a different session cannot quietly take one over by
    asking a question in it.
    """
    await db.execute(
        insert(Conversation)
        .values(
            id=conversation_id,
            language=language,
            persona=persona,
            account_status=account_status,
            owner_id=owner_id,
            title=title,
        )
        .on_conflict_do_nothing(index_elements=[Conversation.id])
    )


async def list_conversations(
    db: AsyncSession, owner_id: uuid.UUID, *, limit: int = 200
) -> list[Conversation]:
    """This principal's conversations, newest first.

    Scoped by owner and by nothing else. There is deliberately no "all
    conversations" variant: the only caller is a person asking for their own,
    and an unscoped version of this query is one autocomplete away from being
    the bug that hands somebody else's chats over.
    """
    result = await db.execute(
        select(Conversation)
        .where(Conversation.owner_id == owner_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def load_transcript(
    db: AsyncSession, conversation_id: str, owner_id: uuid.UUID
) -> list[Message] | None:
    """Every turn of one conversation, oldest first, or None.

    Ownership is part of the WHERE clause rather than a check afterwards, so
    "not yours" and "does not exist" are the same answer and the caller cannot
    accidentally reveal which by handling them differently. A conversation id is
    guessable in principle; this makes guessing one worth nothing.
    """
    owns = await db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.owner_id == owner_id,
        )
    )
    if owns is None:
        return None

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq)
    )
    return list(result.scalars().all())


async def append_turn(
    db: AsyncSession,
    conversation_id: str,
    *,
    role: str,
    content: str,
    extra: dict | None = None,
) -> int:
    """Append one message at the next sequence number, and return it.

    `seq` comes from a MAX() inside this transaction rather than a counter in
    the application, so two workers appending to one thread cannot both believe
    they are turn 7. The unique index on (conversation_id, seq) is the backstop
    if they somehow do.
    """
    next_seq = (
        await db.scalar(
            select(func.coalesce(func.max(Message.seq), 0) + 1).where(
                Message.conversation_id == conversation_id
            )
        )
    ) or 1

    db.add(
        Message(
            conversation_id=conversation_id,
            seq=next_seq,
            role=role,
            content=content,
            extra=extra or {},
        )
    )
    return next_seq


async def load_context(
    db: AsyncSession, conversation_id: str, *, window_turns: int
) -> ConversationContext:
    """The summary, plus the last `window_turns` messages, oldest first.

    Bounded by LIMIT rather than fetched-and-sliced: the cost of a long
    conversation should not grow just because we intend to discard most of it.
    """
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        return ConversationContext()

    newest_first = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq.desc())
            .limit(window_turns)
        )
    ).all()

    total = (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
    ) or 0

    return ConversationContext(
        summary=conversation.summary,
        recent=list(reversed(newest_first)),
        older_turn_count=max(0, total - len(newest_first)),
    )


async def turns_awaiting_summary(
    db: AsyncSession, conversation_id: str, *, window_turns: int
) -> list[Message]:
    """Messages that have fallen out of the window and are not yet summarised.

    The gap between `summarized_through_seq` and the start of the window. A
    conversation that has not outgrown its window yet returns nothing and the
    job does nothing.
    """
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        return []

    highest = (
        await db.scalar(
            select(func.coalesce(func.max(Message.seq), 0)).where(
                Message.conversation_id == conversation_id
            )
        )
    ) or 0

    window_starts_at = highest - window_turns
    if window_starts_at <= conversation.summarized_through_seq:
        return []

    return list(
        (
            await db.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.seq > conversation.summarized_through_seq,
                    Message.seq <= window_starts_at,
                )
                .order_by(Message.seq)
            )
        ).all()
    )


async def save_summary(
    db: AsyncSession, conversation_id: str, *, summary: str, through_seq: int
) -> None:
    """Record the compressed older context and how far it reaches.

    Never moves `summarized_through_seq` backwards. The job is fire-and-forget
    and two runs for one thread can overlap; an older result landing last must
    not un-summarise turns a newer one already folded in.
    """
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or through_seq <= conversation.summarized_through_seq:
        return

    conversation.summary = summary
    conversation.summarized_through_seq = through_seq


async def set_title(db: AsyncSession, conversation_id: str, title: str) -> None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.title = title
