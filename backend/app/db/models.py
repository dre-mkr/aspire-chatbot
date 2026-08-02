"""The persisted shape of the knowledge base and of every conversation.

Two concerns live here and they are deliberately not the same thing:

* `documents` is the retrieval corpus -- what pgvector searches.
* `conversations` / `messages` are the transcript, kept at full fidelity
  whether or not the model ever sees it again. Streaks, analytics and
  account-status routing read the whole record; a later step will give the model
  a window of it plus a summary.

`EMBEDDING_DIMENSIONS` is the one number here that cannot be got wrong quietly
-- see the note on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
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

# What each embedding model actually produces. The single most expensive thing
# to get wrong here: the column width is fixed at migration time, and a model
# whose vectors are a different length does not fail at startup or at ingest
# configuration -- it fails on the INSERT, per row, forever.
EMBEDDING_MODEL_DIMENSIONS = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
    # fastembed's default, for the offline provider.
    "BAAI/bge-small-en-v1.5": 384,
}

# The width the `documents.embedding` column was created with, and therefore the
# only width that can be stored in it. Pinned rather than derived: a migration
# has to produce the same DDL every time it runs, so it cannot read a setting
# that someone may have changed since.
#
# This must agree with `Settings.embeddings_model`. It is checked at startup
# (`db.engine.check_embedding_dimensions`) rather than left to be discovered,
# because the two live in different files and nothing else connects them.
#
# Changing the embedding model means a new migration AND a full re-embed. There
# is no in-place conversion: the vectors themselves are different numbers.
EMBEDDING_DIMENSIONS = 3072

# pgvector indexes the `vector` type up to 2000 dimensions only. At 3072 the
# column stores fine but neither HNSW nor IVFFlat can be built on it directly;
# the supported route is a `halfvec` expression index. Migration 0002 explains
# the consequences. At 1536 or below the cast is unnecessary and a plain
# `vector_cosine_ops` index works -- which is worth knowing if the dimension
# ever drops.
MAX_INDEXABLE_VECTOR_DIMENSIONS = 2000


def dimensions_for(model: str) -> int | None:
    """Vector width for a configured embedding model, or None if unrecognised."""
    return EMBEDDING_MODEL_DIMENSIONS.get(model)


class Base(DeclarativeBase):
    pass


class Document(Base):
    """One retrievable chunk of the knowledge base."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=False
    )

    # The filters that run *before* the similarity math. Real columns rather
    # than JSONB keys because each one belongs in the WHERE clause of every
    # search, and shrinking the candidate set first is both cheaper and more
    # honest than fetching a wide top-N and discarding most of it afterwards.
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    persona_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    account_status_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    source_url: Mapped[str | None] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Whatever the source row carried that is worth keeping but not a column.
    doc_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    """One chat thread, addressed by the id the browser minted for it."""

    __tablename__ = "conversations"

    # Deliberately the client's own `thread_id` rather than a surrogate key.
    # That id is already the URL, the localStorage key, the games session key
    # and the agent's thread id; a different identity here would buy a lookup
    # table and nothing else.
    id: Mapped[str] = mapped_column(String(128), primary_key=True)

    title: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    persona: Mapped[str | None] = mapped_column(String(32))
    account_status: Mapped[str | None] = mapped_column(String(32))

    # Reserved for the memory step: the compressed older context, and how far it
    # reaches. Created now so that step is a code change rather than a second
    # migration against a live table.
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
    # Monotonic within a conversation. Ordering by timestamp would be a bug
    # waiting for two messages written in the same millisecond.
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
        # Unique, so `seq` is a real sequence rather than a hint, and covering
        # the only read shape there is: this conversation, in order.
        Index("ix_messages_conversation_seq", "conversation_id", "seq", unique=True),
    )


class EligibilityOutcome(Base):
    """One completed eligibility pre-check, anonymised.

    The narrowest table in the schema, and every absence in it is deliberate.
    The flow that writes this collects a minor's age band, island, citizenship
    status and school status; **none of those reach this row**, and there is no
    thread id here either, so nothing joins it back to the transcript that
    produced it.

    What is left is a histogram: how many checks reached each verdict, which
    criterion each turned on, in which language, on which day. That answers the
    questions the insight view exists to ask -- are we turning people away on
    age, are French speakers dropping out -- and answers nothing about anyone.

    Adding a column here is a privacy decision, not a schema decision. See
    `app.eligibility.outcomes` for what specifically must not be added.
    """

    __tablename__ = "eligibility_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # "likely_eligible", "not_yet", "needs_confirmation".
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    # Which criterion decided it: "citizenship", "age_minimum", "age_cohort",
    # "residence", "school", or "none" for a clean pass.
    criterion: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # The only read shape: counts over a date range, grouped by verdict.
        Index("ix_eligibility_outcomes_created_verdict", "created_at", "verdict"),
    )
