"""The persisted shape of the knowledge base and of every conversation."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# What each embedding model actually produces.
EMBEDDING_MODEL_DIMENSIONS = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
    # fastembed's default, for the offline provider.
    "BAAI/bge-small-en-v1.5": 384,
}

# The width of the `documents.embedding` column.
EMBEDDING_DIMENSIONS = 3072

# pgvector indexes the `vector` type up to 2000 dimensions only.
MAX_INDEXABLE_VECTOR_DIMENSIONS = 2000


def dimensions_for(model: str) -> int | None:
    """Vector width for a configured embedding model, or None if unrecognised."""
    return EMBEDDING_MODEL_DIMENSIONS.get(model)


class Base(DeclarativeBase):
    pass


class Document(Base):
    """One chunk of the knowledge base, with the vector retrieval searches."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=False
    )

    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    persona_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    account_status_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The knowledge-base row this chunk came from ("ASP-042").
    kb_id: Mapped[str | None] = mapped_column(Text)

    # `metadata` is taken by SQLAlchemy's Declarative API, so the attribute is renamed and the column keeps the nam…
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base):
    """One person, anonymous or registered."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)

    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)

    # The seed an anonymous identity was created from, kept for abuse investigation.
    device_id: Mapped[str | None] = mapped_column(String(64))

    # Bumped to kill every token already issued for this user.
    session_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Set once an anonymous identity has been merged into an account.
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Who this account is for, asked at sign-up rather than inferred.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="participant")

    # What sign-up collects.
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    # The date of birth of the person the account is FOR, which `role` now disambiguates: a guardian's own, not the…
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    # Stored rather than recomputed on every read, so a birthday cannot change what somebody is allowed to see half…
    is_minor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    island: Mapped[str | None] = mapped_column(Text)
    school: Mapped[str | None] = mapped_column(Text)
    # Contact detail for a named adult, not a second identity.
    guardian_name: Mapped[str | None] = mapped_column(Text)
    guardian_email: Mapped[str | None] = mapped_column(Text)
    guardian_phone: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuthToken(Base):
    """A one-time link: password reset, address verification, or sign-in."""

    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Conversation(Base):
    """One chat thread, addressed by the id the browser minted for it."""

    __tablename__ = "conversations"

    # Deliberately the client's own `thread_id` rather than a surrogate key.
    id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Whose conversation this is.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )

    title: Mapped[str | None] = mapped_column(Text)
    # "generated" | "manual" | None.
    title_source: Mapped[str | None] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    persona: Mapped[str | None] = mapped_column(String(32))
    account_status: Mapped[str | None] = mapped_column(String(32))

    # Reserved for the memory step: the compressed older context, and how far it reaches.
    summary: Mapped[str | None] = mapped_column(Text)
    summarized_through_seq: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.seq",
    )


class Message(Base):
    """One turn, stored whole and never trimmed."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Monotonic within a conversation.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Sources, follow-ups, token counts -- whatever the turn carried.
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        # Unique, so `seq` is a real sequence rather than a hint, and covering the only read shape there is: this conve…
        Index("ix_messages_conversation_seq", "conversation_id", "seq", unique=True),
    )


class EligibilityOutcome(Base):
    """One completed eligibility pre-check, anonymised."""

    __tablename__ = "eligibility_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # "likely_eligible", "not_yet", "needs_confirmation".
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    # Which criterion decided it: "citizenship", "age_minimum", "age_cohort", "residence", "school", or "none" for…
    criterion: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # The only read shape: counts over a date range, grouped by verdict.
        Index("ix_eligibility_outcomes_created_verdict", "created_at", "verdict"),
    )
