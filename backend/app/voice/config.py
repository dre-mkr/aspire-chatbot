"""Configuration for the voice layer."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR

# MIME types a browser recorder actually produces.
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

# Domain vocabulary passed to the STT model.
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
        # The guest voice ids carry an environment alias for their old name, and
        # an alias would otherwise stop the FIELD name from populating them --
        # which the tests, and any caller constructing settings directly, rely on.
        populate_by_name=True,
    )

    # Switches the whole module off: no routes mounted, no registry validation.
    voice_enabled: bool = False
    elevenlabs_api_key: str | None = None

    # --- Models -----------------------------------------------------------
    stt_model: str = "scribe_v2"
    # Live replies: ~75ms, 32 languages, half the per-character cost.
    tts_model_live: str = "eleven_flash_v2_5"
    # Prewarmed and number-heavy text: higher quality, reads figures better.
    tts_model_quality: str = "eleven_multilingual_v2"

    # --- Voice ids --------------------------------------------------------
    # A persona's base voice covers every language unless a per-language id overrides it.
    voice_stella: str | None = None
    # Kaleb is a persona key of his own, so he needs an id of his own -- without
    # this field `VOICE_KALEB` is read by nothing and SILENTLY IGNORED. Someone
    # casts him a voice, sets the variable, redeploys, and he still speaks as
    # Skye with no error anywhere to say why. He falls back to her through
    # `_VOICE_UNDERSTUDY` until this is set, which is deliberate; being unable to
    # set it was not.
    voice_kaleb: str | None = None
    voice_orion: str | None = None
    voice_aurora: str | None = None
    voice_nova: str | None = None
    # `guest` is the general-purpose voice. Left unset it borrows Orion's id
    # rather than failing startup -- see `_VOICE_UNDERSTUDY` in `registry`. Set
    # VOICE_GUEST to give it one of its own.
    #
    # It was called `everyone` until 20 August 2026. Every id below still accepts
    # the old VOICE_EVERYONE* environment variable, so a deployment that was
    # already configured keeps speaking without anybody editing its secrets. Drop
    # the aliases once the environments have been updated.
    voice_guest: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VOICE_GUEST", "VOICE_EVERYONE"),
    )

    voice_stella_en: str | None = None
    voice_stella_es: str | None = None
    voice_stella_fr: str | None = None
    voice_kaleb_en: str | None = None
    voice_kaleb_es: str | None = None
    voice_kaleb_fr: str | None = None
    voice_orion_en: str | None = None
    voice_orion_es: str | None = None
    voice_orion_fr: str | None = None
    voice_aurora_en: str | None = None
    voice_aurora_es: str | None = None
    voice_aurora_fr: str | None = None
    voice_nova_en: str | None = None
    voice_nova_es: str | None = None
    voice_nova_fr: str | None = None
    voice_guest_en: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VOICE_GUEST_EN", "VOICE_EVERYONE_EN"),
    )
    voice_guest_es: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VOICE_GUEST_ES", "VOICE_EVERYONE_ES"),
    )
    voice_guest_fr: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VOICE_GUEST_FR", "VOICE_EVERYONE_FR"),
    )

    # --- Delivery overrides ----------------------------------------------
    # Optional, and unset by default: the table in `voice/registry.py` stands
    # unless one of these is given. They exist because tuning a voice is done by
    # ear -- someone listens, decides it is a shade fast, and changes it -- and
    # that should not be a code edit, a test update and a deploy.
    #
    # stability 0-1 (LOW = expressive, HIGH = even) - similarity_boost 0-1
    # style 0-1 (exaggeration; the registry caps it) - speed 0.7-1.2
    voice_stella_stability: float | None = None
    voice_stella_similarity_boost: float | None = None
    voice_stella_style: float | None = None
    voice_stella_speed: float | None = None

    # Kaleb's delivery is set in `registry._DELIVERY` like everyone else's, but
    # without these he was the one persona whose pace could not be tuned from the
    # environment -- so a Spanish or French cast that needed him a touch slower
    # would have required a code change and a deploy.
    voice_kaleb_stability: float | None = None
    voice_kaleb_similarity_boost: float | None = None
    voice_kaleb_style: float | None = None
    voice_kaleb_speed: float | None = None

    voice_orion_stability: float | None = None
    voice_orion_similarity_boost: float | None = None
    voice_orion_style: float | None = None
    voice_orion_speed: float | None = None

    voice_aurora_stability: float | None = None
    voice_aurora_similarity_boost: float | None = None
    voice_aurora_style: float | None = None
    voice_aurora_speed: float | None = None

    voice_nova_stability: float | None = None
    voice_nova_similarity_boost: float | None = None
    voice_nova_style: float | None = None
    voice_nova_speed: float | None = None

    voice_everyone_stability: float | None = None
    voice_everyone_similarity_boost: float | None = None
    voice_everyone_style: float | None = None
    voice_everyone_speed: float | None = None

    # --- Upload limits ----------------------------------------------------
    # Two gates, both pre-flight and free.
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

    # Adds 20% to every transcription.
    keyterms_enabled: bool = True

    # Stretch goal, off by default.
    voice_realtime_enabled: bool = False
    realtime_token_ttl_seconds: int = 60

    max_speakable_chars: int = Field(default=1500, ge=200, le=5000)

    def resolved(self, path: Path) -> Path:
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache(maxsize=1)
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()
