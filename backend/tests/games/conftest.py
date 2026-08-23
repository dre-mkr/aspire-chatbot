"""Fixtures for the games tests."""

from __future__ import annotations

import pytest

from app.games.config import GameSettings
from app.games.engine import GameEngine
from app.games.events import MemoryEventSink
from app.games.scramble import WordScrambleGame
from app.games.store import InMemorySessionStore

SESSION = "thread-under-test"


@pytest.fixture
def settings() -> GameSettings:
    return GameSettings(
        games_enabled=True,
        games_proactive_suggest=False,
        session_ttl_seconds=3600.0,
        typo_tolerance_min_length=6,
        typo_max_edits=1,
        max_hint_level=3,
    )


@pytest.fixture
def game(settings: GameSettings) -> WordScrambleGame:
    return WordScrambleGame(settings)


@pytest.fixture
def store(settings: GameSettings) -> InMemorySessionStore:
    return InMemorySessionStore(settings.session_ttl_seconds)


@pytest.fixture
def sink() -> MemoryEventSink:
    return MemoryEventSink()


@pytest.fixture
def engine(game, store, sink, settings) -> GameEngine:
    """Word scramble, plus hangman.

    Hangman is here so a test can still ask about a language that has no set.
    `true_false` and `word_scramble` are authored in Spanish and French now, so
    the scramble alone can no longer be asked that question -- and a test that
    cannot fail is worse than one that is missing.
    """
    from app.games.hangman import HangmanGame

    return GameEngine(
        games=[game, HangmanGame(settings)], store=store, sink=sink, settings=settings
    )


@pytest.fixture
def all_words(game: WordScrambleGame) -> list[str]:
    """Every answer in every seeded set — what must never leak."""
    from app.games.models import Language

    return [
        entry.word
        for language in Language
        for game_set in game.sets_for(language)
        for entry in game_set.entries
    ]
