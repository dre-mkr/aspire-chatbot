"""Session persistence: survives a reload, expires on its own.

The requirement is that a child who refreshes the page finds the game where they
left it. That works because the browser never held the game in the first place —
state is server-side, keyed by the conversation's thread id.
"""

from __future__ import annotations

import pytest

from app.games.engine import GameEngine, GameNotRunning
from app.games.events import MemoryEventSink
from app.games.store import InMemorySessionStore

# Matches the value in conftest; kept local because tests/ is not a package.
SESSION = "thread-under-test"


def test_a_reload_finds_the_game_where_it_was_left(game, store, settings):
    """A new request object, the same server-side store.

    This is exactly what a page refresh looks like from the backend: nothing
    about the game came from the client, so nothing about it was lost.
    """
    first = GameEngine(games=[game], store=store, sink=MemoryEventSink(), settings=settings)
    first.start(SESSION)
    first.submit(SESSION, "money")
    first.hint(SESSION)

    reconnected = GameEngine(
        games=[game], store=store, sink=MemoryEventSink(), settings=settings
    )
    # Resumes on word two, with the hint already spent.
    assert reconnected.hint(SESSION).level == 2
    assert reconnected.submit(SESSION, "interest").correct is True


def test_state_is_isolated_per_conversation(engine):
    engine.start("child-a")
    engine.start("child-b")

    engine.submit("child-a", "money")
    # b is untouched, still on word one.
    assert engine.submit("child-b", "interest").correct is False
    assert engine.submit("child-b", "money").correct is True


def test_a_session_expires_after_its_ttl(game, settings):
    store = InMemorySessionStore(ttl_seconds=3600.0)
    engine = GameEngine(
        games=[game], store=store, sink=MemoryEventSink(), settings=settings
    )
    engine.start(SESSION)
    assert engine.is_running(SESSION)

    # Age past the TTL rather than sleeping through an hour.
    store._age(SESSION, seconds=3601.0)

    assert not engine.is_running(SESSION)
    with pytest.raises(GameNotRunning):
        engine.submit(SESSION, "money")


def test_activity_keeps_a_session_alive(game, settings):
    store = InMemorySessionStore(ttl_seconds=100.0)
    engine = GameEngine(
        games=[game], store=store, sink=MemoryEventSink(), settings=settings
    )
    engine.start(SESSION)

    store._age(SESSION, seconds=99.0)
    engine.hint(SESSION)  # a move: refreshes updated_at
    store._age(SESSION, seconds=99.0)

    assert engine.is_running(SESSION), "a game in active use must not expire"


def test_expired_sessions_are_swept_by_later_writers(game, settings):
    store = InMemorySessionStore(ttl_seconds=100.0)
    engine = GameEngine(
        games=[game], store=store, sink=MemoryEventSink(), settings=settings
    )
    engine.start("abandoned")
    store._age("abandoned", seconds=200.0)

    engine.start("active")
    engine.hint("active")  # a write, which sweeps

    assert "abandoned" not in store._sessions
    assert "active" in store._sessions


def test_quitting_frees_the_session(engine, store):
    engine.start(SESSION)
    assert SESSION in store._sessions
    engine.quit(SESSION)
    assert SESSION not in store._sessions


def test_finishing_frees_the_session(engine, store):
    engine.start(SESSION)
    for _ in range(4):
        engine.skip(SESSION)
    assert SESSION not in store._sessions
