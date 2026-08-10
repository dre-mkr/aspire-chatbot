"""Learning games inside the chat."""

from app.games.config import GameSettings, get_game_settings
from app.games.models import PLAYING_PERSONAS, Language, Persona
from app.games.router import router as games_router
from app.games.tools import GAME_TOOLS

__all__ = [
    "GAME_TOOLS",
    "PLAYING_PERSONAS",
    "GameSettings",
    "Language",
    "Persona",
    "games_enabled",
    "games_proactive_suggest",
    "games_router",
    "get_game_settings",
]


def games_enabled() -> bool:
    return get_game_settings().games_enabled


def games_proactive_suggest() -> bool:
    """Whether the agent may offer a game unasked. False, deliberately."""
    return get_game_settings().games_proactive_suggest
