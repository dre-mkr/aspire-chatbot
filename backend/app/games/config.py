"""Configuration for the games layer.

A separate settings object from `app.config.Settings`, reading the same .env —
the same split the voice module uses, so games can be reviewed or switched off
without touching the core service.

Unlike voice, this defaults to ON: there is no API key, no external service and
no id mapping that can be missing, so there is nothing here that can fail at
startup and nothing to withhold until a demo.
"""

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

    # The agent must never offer a game unasked. Flagged rather than hardcoded so
    # it can be turned on later without touching the prompt or the tools.
    games_proactive_suggest: bool = False

    # A warm-up is a minute's work. An hour is long enough that a child who
    # wanders off and comes back still finds it, short enough that abandoned
    # sessions do not accumulate.
    session_ttl_seconds: float = Field(default=3600.0, ge=60.0)

    # Typo tolerance applies only above this length. SAVE (4) and MONEY (5) stay
    # exact: at four letters an edit-distance of one is a different word as often
    # as it is a slip.
    typo_tolerance_min_length: int = Field(default=6, ge=3)
    typo_max_edits: int = Field(default=1, ge=0, le=2)

    # Hints 1..3 are progressive nudges. The next request reveals. Only applies
    # to games that offer hints at all — true/false declines, because a hint on
    # a binary choice is the answer.
    max_hint_level: int = Field(default=3, ge=1)

    # How long a volatile fact stays servable after someone last confirmed it.
    # A statutory rate nobody has checked in six months is not a fact we should
    # be teaching a child; the item drops out of play rather than going stale in
    # front of them. Stable content — what a budget is, what interest does —
    # ignores this entirely.
    volatile_review_days: int = Field(default=180, ge=1)

    seed_dir: Path = BASE_DIR / "app" / "games" / "seeds"
    events_path: Path = BASE_DIR / "data" / "events" / "games.jsonl"

    def resolved(self, path: Path) -> Path:
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache(maxsize=1)
def get_game_settings() -> GameSettings:
    return GameSettings()
