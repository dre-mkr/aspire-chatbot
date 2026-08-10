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

# The width of the `documents.embedding` column.
#
# Live again as of migration 0009 (P13-002): pgvector is now the retrieval
# corpus and the source of truth, and Chroma is gone. This number has to agree
# with what `EMBEDDINGS_MODEL` produces or every INSERT fails, one row at a
# time, forever -- `ingest` checks it against `dimensions_for()` before writing
# anything so that failure happens once, up front, with a message naming both
# numbers.
#
# History worth keeping: 0001/0002 built this column and its indexes, nothing
# ever wrote to it, 0008 dropped it as dead weight, and 0009 recreated it for
# real use. See 0009 for why it has no vector index this time.
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
    """One chunk of the knowledge base, with the vector retrieval searches.

    The filter columns are real columns rather than JSONB keys because each one
    belongs in the WHERE clause of a search, and Postgres can only shrink the
    candidate set before the similarity math with a real column to index.

    `metadata_` carries the original CSV row verbatim. That is not redundancy:
    the retriever hands it straight back as `langchain_core.documents.Document`
    metadata, and `main._extract_sources` puts it on the wire, so the shape the
    client already receives is preserved exactly by preserving this.
    """

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
    # The knowledge-base row this chunk came from ("ASP-042"). Not unique: a long
    # row splits into several chunks that share it.
    kb_id: Mapped[str | None] = mapped_column(Text)

    # `metadata` is taken by SQLAlchemy's Declarative API, so the attribute is
    # renamed and the column keeps the name the migration created.
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base):
    """One person, anonymous or registered.

    Deliberately one table for both. An anonymous visitor and an account holder
    differ by `account_type` and nothing structural, so conversations — and
    anything else that belongs to a person — attach the same way for each and
    there is no second storage path to keep in step. Registering does not move
    a row; it fills in the empty columns.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)

    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)

    # The seed an anonymous identity was created from, kept for abuse
    # investigation. NOT unique and NOT a lookup key: nothing may exchange a
    # device id for a session, which is the whole point of `auth.py`.
    device_id: Mapped[str | None] = mapped_column(String(64))

    # Bumped to kill every token already issued for this user. Claiming an
    # anonymous identity does it, and so does signing out.
    session_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Set once an anonymous identity has been merged into an account. Its
    # presence is what makes a second claim impossible.
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Who this account is for, asked at sign-up rather than inferred.
    #
    # `date_of_birth` alone could not answer it. The form asks for one date in
    # the second person, so a parent filling it in for a child had two readings
    # of the same field -- and entering the child's date created an account in a
    # child band that could never reach registration, because `register_agent`
    # lives on `aurora` alone and `aurora` is not narrower than a child band's
    # persona. Asking is the fix; see migration 0017.
    #
    # Grants nothing by itself. `access.allowed_agents` does not read this
    # column. It picks a candidate persona which must still survive
    # `account._narrowing` -- and a `guardian` account requires an adult date of
    # birth at sign-up, which is what makes the claim cost something.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="participant")

    # What sign-up collects. All nullable: nothing in the product requires them
    # to be filled in order to hold an account.
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    # The date of birth of the person the account is FOR, which `role` now
    # disambiguates: a guardian's own, not the child they are applying for. The
    # child's dates belong to the application, in `application_pii`.
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    # Stored rather than recomputed on every read, so a birthday cannot change
    # what somebody is allowed to see half-way through a session.
    is_minor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    island: Mapped[str | None] = mapped_column(Text)
    school: Mapped[str | None] = mapped_column(Text)
    # Contact detail for a named adult, not a second identity. Nobody signs in
    # with these.
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
    """A one-time link: password reset, address verification, or sign-in.

    Only the hash is stored. A leaked table must not be a set of working links,
    and nothing here needs to read a token back — only to recognise one when it
    is presented.
    """

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
    # That id is already the URL, the localStorage key, the games session key
    # and the agent's thread id; a different identity here would buy a lookup
    # table and nothing else.
    id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Whose conversation this is.
    #
    # A real foreign key to a real person, anonymous or registered alike. It
    # replaced a string principal read off a request header, which meant anyone
    # holding somebody else's device id could read their chats. Ownership is now
    # only ever established by a signed token — see `auth.py`.
    #
    # Nullable because a turn is answered whether or not the caller has an
    # identity at all. An unowned conversation is readable by nobody, which is
    # the correct outcome rather than a gap.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )

    title: Mapped[str | None] = mapped_column(Text)
    # "generated" | "manual" | None. None means the title is still the truncated
    # first question and generation is welcome to improve it; "manual" means a
    # person typed it and generation must never touch it again.
    title_source: Mapped[str | None] = mapped_column(String(16))
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
