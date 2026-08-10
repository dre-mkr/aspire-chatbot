"""Reading a person's own conversations back."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, update

from app.db import database_enabled, session
from app.db.models import Conversation
from app.db.repository import list_conversations, load_transcript
from app.auth import Principal, require_principal
from app.sessions import owner_id_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    """One row in the rail."""

    thread_id: str
    title: str | None = None
    title_source: str | None = None
    #: Epoch milliseconds, which is what the client's grouping already speaks.
    updated_at: int


class ConversationList(BaseModel):
    conversations: list[ConversationSummary] = Field(default_factory=list)


class TranscriptMessage(BaseModel):
    """One turn, in the shape the client already renders."""

    role: str
    text: str = ""
    sources: list[dict] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    game_type: str | None = None


class ConversationDetail(ConversationSummary):
    messages: list[TranscriptMessage] = Field(default_factory=list)
    #: The language the conversation was held in.
    language: str = "en"
    #: Who it was being answered for, on the same reasoning.
    persona: str | None = None


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    #: "manual" when a person typed it, "generated" when the model named it.
    title_source: str | None = None


class ClaimRequest(BaseModel):
    #: Capped: this is a changeover path, not a bulk import surface.
    thread_ids: list[str] = Field(default_factory=list, max_length=500)


class ClaimResult(BaseModel):
    claimed: int


async def _owner(principal: Principal) -> uuid.UUID:
    """The verified caller's user id, or 401."""
    owner = await owner_id_for(principal)
    if owner is None:
        raise HTTPException(status_code=401, detail="This session is no longer valid.")
    return owner


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Conversation history is unavailable.")


@router.get("", response_model=ConversationList)
async def get_conversations(principal: Principal = Depends(require_principal)) -> ConversationList:
    owner = await _owner(principal)
    if not database_enabled():
        raise _unavailable()

    async with session() as db:
        if db is None:
            raise _unavailable()
        rows = await list_conversations(db, owner)

    return ConversationList(
        conversations=[
            ConversationSummary(
                thread_id=row.id,
                title=row.title,
                title_source=row.title_source,
                updated_at=int(row.updated_at.timestamp() * 1000),
            )
            for row in rows
        ]
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str, principal: Principal = Depends(require_principal)
) -> ConversationDetail:
    owner = await _owner(principal)
    if not database_enabled():
        raise _unavailable()

    async with session() as db:
        if db is None:
            raise _unavailable()

        turns = await load_transcript(db, conversation_id, owner)
        if turns is None:
            # Not yours, or not there. The same answer on purpose.
            raise HTTPException(status_code=404, detail="No such conversation.")

        row = await db.get(Conversation, conversation_id)

    messages: list[TranscriptMessage] = []
    for turn in turns:
        extra = turn.extra or {}
        event = extra.get("event")

        if turn.role == "user":
            messages.append(TranscriptMessage(role="user", text=turn.content))
            continue

        # A game or eligibility turn is the card and nothing else.
        if event == "game_started":
            messages.append(
                TranscriptMessage(role="game", game_type=extra.get("game_type") or "")
            )
            continue
        if event == "eligibility_started":
            messages.append(TranscriptMessage(role="eligibility"))
            continue

        messages.append(
            TranscriptMessage(
                role="assistant",
                text=turn.content,
                sources=extra.get("sources") or [],
                follow_ups=extra.get("follow_ups") or [],
            )
        )

    return ConversationDetail(
        thread_id=conversation_id,
        title=row.title if row else None,
        title_source=row.title_source if row else None,
        updated_at=int(row.updated_at.timestamp() * 1000) if row else 0,
        language=row.language if row else "en",
        persona=row.persona if row else None,
        messages=messages,
    )


@router.patch("/{conversation_id}", status_code=204)
async def rename_conversation(
    conversation_id: str,
    body: RenameRequest,
    principal: Principal = Depends(require_principal),
) -> None:
    owner = await _owner(principal)
    if not database_enabled():
        raise _unavailable()

    async with session() as db:
        if db is None:
            raise _unavailable()
        # Ownership in the WHERE clause, so a rename cannot be aimed at somebody else's conversation by guessing its id.
        result = await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.owner_id == owner)
            .values(title=body.title, title_source=body.title_source)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="No such conversation.")


async def _purge_thread_state(conversation_id: str) -> None:
    """Everything else filed under this thread id, once the row itself is gone."""
    from app.eligibility.store import get_store as eligibility_sessions
    from app.games.store import get_store as game_sessions
    from app.graph.checkpointer import delete_thread

    try:
        game_sessions().delete(conversation_id)
        eligibility_sessions().delete(conversation_id)
    except Exception:
        logger.warning(
            "A conversation was deleted but its in-memory session state survived.",
            exc_info=True,
        )

    try:
        await delete_thread(conversation_id)
    except Exception:
        logger.warning(
            "A conversation was deleted but its checkpoint survived, so the "
            "model's copy of the transcript is still in Postgres.",
            exc_info=True,
        )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, principal: Principal = Depends(require_principal)
) -> None:
    """Delete one conversation, permanently."""
    owner = await _owner(principal)
    if not database_enabled():
        raise _unavailable()

    async with session() as db:
        if db is None:
            raise _unavailable()
        result = await db.execute(
            delete(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.owner_id == owner,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="No such conversation.")

    # Outside the transaction: the row is committed gone, and none of these three stores can participate in it anyw…
    await _purge_thread_state(conversation_id)


@router.post("/claim", response_model=ClaimResult)
async def claim_conversations(
    body: ClaimRequest, principal: Principal = Depends(require_principal)
) -> ClaimResult:
    """Adopt conversations this browser wrote before ownership was recorded."""
    owner = await _owner(principal)
    if not database_enabled():
        raise _unavailable()
    if not body.thread_ids:
        return ClaimResult(claimed=0)

    async with session() as db:
        if db is None:
            raise _unavailable()
        result = await db.execute(
            update(Conversation)
            .where(
                Conversation.id.in_(body.thread_ids),
                Conversation.owner_id.is_(None),
            )
            .values(owner_id=owner)
        )
        claimed = result.rowcount or 0

    if claimed:
        logger.info("Claimed %d previously unowned conversation(s).", claimed)
    return ClaimResult(claimed=claimed)


__all__ = ["router"]
