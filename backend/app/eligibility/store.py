"""Where a half-finished eligibility check lives."""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

from app.eligibility.config import get_eligibility_settings
from app.eligibility.models import Session

logger = logging.getLogger(__name__)


class SessionStore(Protocol):
    def get(self, session_id: str) -> Session | None: ...
    def put(self, session: Session) -> None: ...
    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore:
    """Dict with a TTL, guarded by a lock."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _expired(self, session: Session, now: float) -> bool:
        return (now - session.updated_at) > self._ttl

    def get(self, session_id: str) -> Session | None:
        now = time.time()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._expired(session, now):
                del self._sessions[session_id]
                # No session id: it is the conversation id, and logs must not carry it.
                logger.info("An eligibility session expired and was discarded.")
                return None
            return session

    def put(self, session: Session) -> None:
        now = time.time()
        session.updated_at = now
        with self._lock:
            self._sessions[session.session_id] = session
            # Opportunistic sweep: the next writer clears abandoned answers, no background task.
            if len(self._sessions) > 1:
                for key in [
                    k
                    for k, s in self._sessions.items()
                    if k != session.session_id and self._expired(s, now)
                ]:
                    del self._sessions[key]

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    # Test seam: lets the TTL test age a session without sleeping through it.
    def _age(self, session_id: str, seconds: float) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].updated_at -= seconds


_store: SessionStore | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = InMemorySessionStore(get_eligibility_settings().session_ttl_seconds)
    return _store


def set_store(store: SessionStore | None) -> None:
    """Swap the backend. Used by tests."""
    global _store
    _store = store
