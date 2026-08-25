"""Request and response models for the voice endpoints."""

from pydantic import BaseModel, Field

from app.voice.registry import Language, Persona


class TranscriptionResponse(BaseModel):
    text: str
    language_code: str
    language_probability: float
    duration_seconds: float


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    persona: Persona
    language: Language
    # Only mp3 for now; the field exists so another format gets a clean 400.
    format: str = "mp3"
    # Optional, used only for rate-limit bucketing.
    thread_id: str | None = None


class PersonaVoice(BaseModel):
    persona: Persona
    languages: list[Language]
    speed: float
    stability: float


class VoiceLimits(BaseModel):
    max_duration_seconds: float
    max_file_size_bytes: int
    allowed_mime_types: list[str]
    max_transcriptions_per_window: int
    max_speech_per_window: int
    rate_window_seconds: float


class VoiceConfigResponse(BaseModel):
    enabled: bool
    personas: list[PersonaVoice]
    languages: list[Language]
    limits: VoiceLimits
    realtime_enabled: bool
    #: Whether the GUIDE voices can actually be synthesised, as distinct from
    #: whether the voice module is switched on.
    #:
    #: `enabled` is a feature flag and nothing more, and on production it was
    #: true while `ELEVENLABS_API_KEY` was unset -- so the config advertised six
    #: guides across three languages, the client showed the Play button, and
    #: every press spent a round trip discovering a 503 before falling back to
    #: the device's own voice. The reader still heard the answer, which is why
    #: it went unnoticed: the fallback was covering for a silent misconfiguration.
    #:
    #: `enabled` deliberately stays as it was. It gates whether the player is
    #: offered at all, so reporting it false here would have removed the
    #: fallback along with the failure -- no Play button, no audio, worse than
    #: the bug. This field says which VOICE the reader is about to hear.
    native_voice: bool = True


class VoiceErrorResponse(BaseModel):
    error: str
    fallback: str | None = None
