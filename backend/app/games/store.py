"""Where a game session lives while it is being played.

Server-side, keyed by the conversation's `thread_id`, never in the client and
never in conversation history. A child who reloads the page finds the game where
they left it, because the browser was never holding it in the first place.

The in-memory backend matches this service as deployed: one uvicorn worker,
because conversation memory is already an in-process `InMemorySaver`. Game state
therefore has exactly the lifetime conversations already have — it survives a
reload, and it does not survive a restart. Everything here is behind
`SessionStore` so swapping in Redis is one class and no caller changes.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

from app.games.config import get_game_settings
from app.games.models import GameSession

logger = logging.getLogger(__name__)


class SessionStore(Protocol):
    def get(self, session_id: str) -> GameSession | None: ...
    def put(self, session: GameSession) -> None: ...
    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore:
    """Dict with a TTL, guarded by a lock.

    The lock is not optional: uvicorn runs request handlers on a threadpool, so
    two turns of the same conversation can overlap if a child double-taps send.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, GameSession] = {}
        self._lock = threading.Lock()

    def _expired(self, session: GameSession, now: float) -> bool:
        return (now - session.updated_at) > self._ttl

    def get(self, session_id: str) -> GameSession | None:
        now = time.time()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._expired(session, now):
                del self._sessions[session_id]
                logger.info("Game session expired: %s", session_id)
                return None
            return session

    def put(self, session: GameSession) -> None:
        now = time.time()
        session.updated_at = now
        with self._lock:
            self._sessions[session.session_id] = session
            # Opportunistic sweep: abandoned sessions are cleared by the next
            # writer rather than by a background task nobody remembers to run.
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
        _store = InMemorySessionStore(get_game_settings().session_ttl_seconds)
    return _store


def set_store(store: SessionStore | None) -> None:
    """Swap the backend. Used by tests, and by whoever adds Redis."""
    global _store
    _store = store
