"""Reading a person's own conversations back.

Transcripts have been written to Postgres since 0003 and never read. The rail
listed chats out of the browser's localStorage instead, which made history a
property of a device rather than of a person, and made "the same conversation"
something the server could store but never show.

This is the read half. Three routes, all scoped by principal:

    GET   /api/conversations            the rail's list
    GET   /api/conversations/{id}       one transcript, whole
    PATCH /api/conversations/{id}       rename

and one write that exists only for the changeover:

    POST  /api/conversations/claim      adopt rows this browser wrote before
                                        ownership was recorded

Every route answers 404 rather than 403 for a conversation that is not yours.
"Not yours" and "does not exist" must be indistinguishable, or the API becomes
an oracle for which conversation ids are real.

Shapes here mirror what the client already stores, deliberately. The point of
the change is that the transcript comes from the server; it is not an
opportunity to renegotiate what a message looks like, and a client that has to
be rewritten to read its own history is a migration nobody finishes.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update

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
    """One turn, in the shape the client already renders.

    `text` carries the assistant's prose unparsed. Turning it into blocks is the
    client's job and already exists there -- sending pre-parsed blocks would put
    a second markdown implementation on the server and let the two drift.
    """

    role: str
    text: str = ""
    sources: list[dict] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    game_type: str | None = None


class ConversationDetail(ConversationSummary):
    messages: list[TranscriptMessage] = Field(default_factory=list)
    #: The language the conversation was held in.
    #:
    #: Stored on the row since the schema was written and never sent, so the
    #: client had no way to reopen a French conversation in French -- it
    #: reopened in whatever the device happened to be set to. Only on the
    #: detail, not the summary: the rail lists titles and does not need it, and
    #: the list is the hot path.
    language: str = "en"
    #: Who it was being answered for, on the same reasoning. Null means the
    #: conversation was held before anybody chose, which is a real state.
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
    """The verified caller's user id, or 401.

    `require_principal` has already checked the signature and expiry; this also
    confirms the session has not been retired — claiming an anonymous identity
    and signing out both bump its epoch, and a token minted before that must
    stop working immediately rather than at expiry.
    """
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

        # A game or eligibility turn is the card and nothing else. The prose
        # stored beside it is a history line for the model, never for the
        # screen, so it is deliberately not sent.
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
        # Ownership in the WHERE clause, so a rename cannot be aimed at somebody
        # else's conversation by guessing its id.
        result = await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.owner_id == owner)
            .values(title=body.title, title_source=body.title_source)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="No such conversation.")


@router.post("/claim", response_model=ClaimResult)
async def claim_conversations(
    body: ClaimRequest, principal: Principal = Depends(require_principal)
) -> ClaimResult:
    """Adopt conversations this browser wrote before ownership was recorded.

    Every transcript written before ownership existed has `owner_id = NULL` and is
    readable by nobody. The browser that created them still has their ids in
    localStorage, and presenting an id it could only have if it made the
    conversation is the strongest claim available in a product with no accounts.

    Narrow on purpose, and the `IS NULL` is the whole of the safety argument:
    an owned conversation can never be re-owned, so a client replaying somebody
    else's ids takes nothing. It is also why this cannot be reused as a
    "transfer" route later -- that would need a real one.
    """
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
