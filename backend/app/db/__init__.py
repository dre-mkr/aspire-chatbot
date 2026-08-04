"""Postgres: the engine, the schema, and the conversation repository."""

from app.db.engine import (
    check_schema,
    database_enabled,
    dispose,
    get_engine,
    get_sessionmaker,
    session,
    warm,
)
from app.db.models import (
    EMBEDDING_DIMENSIONS,
    Base,
    Conversation,
    EligibilityOutcome,
    Message,
)

__all__ = [
    "Base",
    "Conversation",
    "EMBEDDING_DIMENSIONS",
    "EligibilityOutcome",
    "Message",
    "check_schema",
    "database_enabled",
    "dispose",
    "get_engine",
    "get_sessionmaker",
    "session",
    "warm",
]
