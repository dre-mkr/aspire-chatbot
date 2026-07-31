"""Configuration for the voice layer.

Deliberately a separate settings object from `app.config.Settings`, reading the
same .env. The whole module can then be reviewed, demoed, or switched off
without touching the core service.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR

# MIME types a browser recorder actually produces. Anything else is rejected
# before it can reach a paid API.
ALLOWED_AUDIO_MIME = frozenset(
    {
        "audio/webm",
        "audio/mp4",
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "audio/ogg",
    }
)

# Domain vocabulary passed to the STT model. Short on purpose: the cap is 1000
# terms, but keyterms add a flat 20% to the cost of every transcription, and
# more than 100 of them triggers 20-second minimum billing.
ASPIRE_KEYTERMS = (
    "ASPIRE",
    "ECCB",
    "Eastern Caribbean Central Bank",
    "St. Kitts and Nevis",
    "Nevis",
    "Basseterre",
    "Warner Park",
    "quarterly statement",
    "compound interest",
)


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Switches the whole module off: no routes mounted, no registry validation.
    #
    # Off by default, deliberately. Enabling it makes a missing voice id a hard
    # startup failure (which is what you want before a demo), and this module
    # needs an API key plus voice ids that a fresh checkout does not have. Left
    # on by default, merely adding the module would stop the existing text
    # service from booting. Set VOICE_ENABLED=true once the ids are in .env.
    voice_enabled: bool = False
    elevenlabs_api_key: str | None = None

    # --- Models -----------------------------------------------------------
    # scribe_v1 and eleven_turbo_v2_5 are both deprecated; do not put them back.
    stt_model: str = "scribe_v2"
    # Live replies: ~75ms, 32 languages, half the per-character cost.
    tts_model_live: str = "eleven_flash_v2_5"
    # Prewarmed and number-heavy text: higher quality, reads figures better.
    tts_model_quality: str = "eleven_multilingual_v2"

    # --- Voice ids --------------------------------------------------------
    # A persona's base voice covers every language, since the multilingual
    # models speak all three. Set a per-language variable only to override one.
    voice_stella: str | None = None
    voice_orion: str | None = None
    voice_aurora: str | None = None
    voice_nova: str | None = None

    voice_stella_en: str | None = None
    voice_stella_es: str | None = None
    voice_stella_fr: str | None = None
    voice_orion_en: str | None = None
    voice_orion_es: str | None = None
    voice_orion_fr: str | None = None
    voice_aurora_en: str | None = None
    voice_aurora_es: str | None = None
    voice_aurora_fr: str | None = None
    voice_nova_en: str | None = None
    voice_nova_es: str | None = None
    voice_nova_fr: str | None = None

    # --- Upload limits ----------------------------------------------------
    # Two gates, both pre-flight and free. The 25 MB cap is the absolute ceiling.
    # The duration guard is a byte proxy for the 60s limit: WebM/Opus (what
    # Android Chrome records) usually carries no duration in its header, so the
    # real duration is only known once scribe_v2 returns it. 4 MB comfortably
    # holds 60s of any compressed format; a long uncompressed WAV may trip it.
    max_upload_bytes: int = 25 * 1024 * 1024
    duration_guard_bytes: int = 4 * 1024 * 1024
    max_duration_seconds: float = 60.0

    # --- Timeouts and the breaker ----------------------------------------
    stt_timeout_seconds: float = 5.0
    tts_timeout_seconds: float = 8.0
    breaker_failure_threshold: int = 3
    breaker_reset_seconds: float = 60.0

    # --- Rate limits (per session, sliding window) -----------------------
    rate_window_seconds: float = 600.0
    max_transcriptions_per_window: int = 20
    max_speech_per_window: int = 40

    # --- Cache ------------------------------------------------------------
    voice_cache_dir: Path = BASE_DIR / "data" / "voice_cache"
    voice_cache_max_bytes: int = 256 * 1024 * 1024

    # Adds 20% to every transcription. Left on because local place names are
    # otherwise mis-heard; turn it off to price-test.
    keyterms_enabled: bool = True

    # Stretch goal, off by default. See router.py.
    realtime_enabled: bool = False
    realtime_token_ttl_seconds: int = 60

    max_speakable_chars: int = Field(default=1500, ge=200, le=5000)

    def resolved(self, path: Path) -> Path:
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache(maxsize=1)
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()
