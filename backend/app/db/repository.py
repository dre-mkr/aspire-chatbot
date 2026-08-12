"""Reading and writing conversations."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConversationContext:
    """Exactly what the model will be shown of a conversation's past."""

    summary: str | None = None
    # Oldest first, ready to append the new question to.
    recent: list = field(default_factory=list)
    # Turns that exist but are represented only by the summary.
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
    """Create the row on the first turn, leave it alone afterwards."""
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
    """This principal's conversations, newest first."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.owner_id == owner_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


#: How much of a conversation is sent when it is reopened.
TRANSCRIPT_LIMIT = 400

#: How many times `append_turn` will re-read MAX(seq) after losing a race.
_APPEND_ATTEMPTS = 3


async def load_transcript(
    db: AsyncSession,
    conversation_id: str,
    owner_id: uuid.UUID,
    *,
    limit: int = TRANSCRIPT_LIMIT,
) -> list[Message] | None:
    """The last `limit` turns of one conversation, oldest first, or None."""
    owns = await db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.owner_id == owner_id,
        )
    )
    if owns is None:
        return None

    # Bounded, newest-first, then reversed for display.
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def append_turn(
    db: AsyncSession,
    conversation_id: str,
    *,
    role: str,
    content: str,
    extra: dict | None = None,
) -> int:
    """Append one message at the next sequence number, and return it."""
    for attempt in range(_APPEND_ATTEMPTS):
        next_seq = (
            await db.scalar(
                select(func.coalesce(func.max(Message.seq), 0) + 1).where(
                    Message.conversation_id == conversation_id
                )
            )
        ) or 1

        try:
            # A nested transaction is a SAVEPOINT.
            async with db.begin_nested():
                db.add(
                    Message(
                        conversation_id=conversation_id,
                        seq=next_seq,
                        role=role,
                        content=content,
                        extra=extra or {},
                    )
                )
                await db.flush()
            return next_seq
        except IntegrityError:
            if attempt == _APPEND_ATTEMPTS - 1:
                logger.warning(
                    "append_turn lost the seq race %d times on %s; giving up",
                    _APPEND_ATTEMPTS,
                    conversation_id,
                )
                raise
            logger.info(
                "append_turn hit a seq collision at %d on %s; retrying",
                next_seq,
                conversation_id,
            )

    # Unreachable: the loop either returns or raises.
    raise RuntimeError("append_turn exhausted its attempts without a verdict")


