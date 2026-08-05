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


#: How much of a conversation is sent when it is reopened.
#:
#: 400 messages is 200 turns, which is far past any real conversation in the
#: measured data and still a bounded query. It exists so the endpoint has a
#: ceiling at all, not to trim anything anybody has.
TRANSCRIPT_LIMIT = 400

#: How many times `append_turn` will re-read MAX(seq) after losing a race.
#:
#: Two contenders need one retry. Three is room for a pathological burst and
#: still a hard stop, because a loop that retries forever under contention is a
#: worse failure than the one it replaced.
_APPEND_ATTEMPTS = 3


async def load_transcript(
    db: AsyncSession,
    conversation_id: str,
    owner_id: uuid.UUID,
    *,
    limit: int = TRANSCRIPT_LIMIT,
) -> list[Message] | None:
    """The last `limit` turns of one conversation, oldest first, or None.

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

    # Bounded, newest-first, then reversed for display.
    #
    # This had no LIMIT at all: an unbounded query feeding a render that was
    # also unbounded (P5-001/P5-003). It is only fast today because
    # conversations are short, and it backs `GET /api/conversations/{id}`, which
    # the client calls on every restore.
    #
    # The newest end is the right end to keep. A reader reopening a
    # conversation is continuing it, not reading it from the beginning, and the
    # client's transcript now windows anyway, so the oldest turns of a very long
    # thread were never going to be on screen.
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
    """Append one message at the next sequence number, and return it.

    `seq` comes from a MAX() inside this transaction rather than a counter in
    the application, so two workers appending to one thread cannot both believe
    they are turn 7. The unique index on (conversation_id, seq) is the backstop
    if they somehow do.

    That backstop used to be the end of the story, and it was not enough. The
    IntegrityError it raises was swallowed by `_persist_turn`'s try/except, so a
    collision did not retry -- it dropped the turn, silently. Low probability,
    because the client blocks sending during a turn, but silent data loss is the
    wrong failure mode at any probability.

    So: retry on collision, with a savepoint so the failed INSERT does not take
    the surrounding transaction down with it. Re-reading MAX() is the whole
    point of the retry -- by the time we are here, the winner's row exists, so
    the second attempt reads past it.
    """
    for attempt in range(_APPEND_ATTEMPTS):
        next_seq = (
            await db.scalar(
                select(func.coalesce(func.max(Message.seq), 0) + 1).where(
                    Message.conversation_id == conversation_id
                )
            )
        ) or 1

        try:
            # A nested transaction is a SAVEPOINT. Without it a unique violation
            # poisons the outer transaction and everything after it fails too.
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


# `turns_awaiting_summary` and `save_summary` stood here. They were the read and
# the write of the arq summary job, which is gone (see `app/jobs.py`): the
# rolling summary lives in the checkpoint now, written by
# `turn.summarise_thread`, and `conversations.summary` has neither a writer nor a
# reader. Measured before removing them -- 0 of 2,774 conversations carried a
# summary, because the job's last caller went with `POST /chat`.
#
# The `summary` and `summarized_through_seq` COLUMNS are deliberately left in
# place. They hold no data, and every migration on this branch is additive.


async def set_title(db: AsyncSession, conversation_id: str, title: str) -> None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.title = title
