"""Structured events for gamification later.

No points, badges or streaks today — the client asked for a warm-up game, not a
reward system. But every one of those is a query over this stream, so the stream
has to be rich enough now that adding them later is a feature, not a migration.

Deliberately absent: the answer. Events record `entry_id`, never `word`. Logs
get shipped to places the running service never goes, and an answer key sitting
in a log file is the same leak by a slower route.

Writing is best effort. A game must never fail because an append failed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.games.config import get_game_settings

logger = logging.getLogger(__name__)

GAME_STARTED = "game_started"
WORD_SOLVED = "word_solved"
HINT_USED = "hint_used"
WORD_SKIPPED = "word_skipped"
GAME_COMPLETED = "game_completed"


@dataclass(frozen=True, slots=True)
class GameEvent:
    event: str
    session_id: str
    game_type: str
    language: str
    persona: str | None
    # Seconds since the game started, so a duration is available on every event
    # rather than only at the end.
    elapsed_seconds: float
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "session_id": self.session_id,
            "game_type": self.game_type,
            "language": self.language,
            "persona": self.persona,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "timestamp": self.timestamp,
            **self.data,
        }


class EventSink(Protocol):
    def emit(self, event: GameEvent) -> None: ...


class JsonlEventSink:
    """One JSON object per line, appended under `data/`.

    A file rather than a table because this service has no database, and a
    line-delimited file is the format every later consumer — a load into
    Postgres, a pandas read, a `jq` one-liner — already understands.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._warned = False

    def emit(self, event: GameEvent) -> None:
        line = json.dumps(event.as_dict(), ensure_ascii=False, separators=(",", ":"))
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError:
            # Warn once. A read-only or full disk should not turn every
            # subsequent move in the game into a log storm.
            if not self._warned:
                logger.warning(
                    "Could not write game events to %s; continuing without them.",
                    self._path,
                    exc_info=True,
                )
                self._warned = True


class NullEventSink:
    """Drops everything. The default in tests that do not assert on events."""

    def emit(self, event: GameEvent) -> None:  # noqa: D102
        return None


class MemoryEventSink:
    """Keeps events in a list, for the tests that do assert on them."""

    def __init__(self) -> None:
        self.events: list[GameEvent] = []

    def emit(self, event: GameEvent) -> None:
        self.events.append(event)

    def names(self) -> list[str]:
        return [e.event for e in self.events]


_sink: EventSink | None = None


def get_sink() -> EventSink:
    global _sink
    if _sink is None:
        settings = get_game_settings()
        _sink = JsonlEventSink(settings.resolved(settings.events_path))
    return _sink


def set_sink(sink: EventSink | None) -> None:
    """Swap the sink. Used by tests, and by whoever adds a real event pipeline."""
    global _sink
    _sink = sink
