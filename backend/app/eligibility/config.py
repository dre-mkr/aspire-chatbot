"""Configuration for the eligibility pre-check."""

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

    # Six questions is a few minutes at most, and someone who wanders off should find the flow where they left it.
    session_ttl_seconds: float = Field(default=3600.0, ge=60.0)

    # Whether the anonymised outcome row is written at all.
    record_outcomes: bool = True


@lru_cache(maxsize=1)
def get_eligibility_settings() -> EligibilitySettings:
    return EligibilitySettings()
