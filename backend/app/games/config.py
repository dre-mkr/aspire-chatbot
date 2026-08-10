"""Configuration for the games layer."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR


class GameSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    games_enabled: bool = True

    # The agent must never offer a game unasked.
    games_proactive_suggest: bool = False

    # A warm-up is a minute's work.
    session_ttl_seconds: float = Field(default=3600.0, ge=60.0)

    # Typo tolerance applies only above this length.
    typo_tolerance_min_length: int = Field(default=6, ge=3)
    typo_max_edits: int = Field(default=1, ge=0, le=2)

    # Hints 1..3 are progressive nudges.
    max_hint_level: int = Field(default=3, ge=1)

    # How long a volatile fact stays servable after someone last confirmed it.
    volatile_review_days: int = Field(default=180, ge=1)

    seed_dir: Path = BASE_DIR / "app" / "games" / "seeds"
    events_path: Path = BASE_DIR / "data" / "events" / "games.jsonl"

    def resolved(self, path: Path) -> Path:
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache(maxsize=1)
def get_game_settings() -> GameSettings:
    return GameSettings()
