"""Configuration for the eligibility pre-check.

Its own settings object reading the same .env, matching how voice and games are
split — the flow can be switched off for review without touching the core
service, and switching it off takes its tool and its prompt section with it.

Defaults on, like games: there is no API key and no external service here, so
nothing can be missing at startup.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR


class EligibilitySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    eligibility_enabled: bool = True

    # Six questions is a few minutes at most, and someone who wanders off should
    # find the flow where they left it. Matched to the games TTL because it is
    # the same judgement about the same conversation.
    session_ttl_seconds: float = Field(default=3600.0, ge=60.0)

    # Whether the anonymised outcome row is written at all. Separate from
    # `eligibility_enabled` so the flow can run with no analytics whatsoever --
    # the safest configuration, and the one to reach for if the privacy position
    # ever changes.
    record_outcomes: bool = True


@lru_cache(maxsize=1)
def get_eligibility_settings() -> EligibilitySettings:
    return EligibilitySettings()
