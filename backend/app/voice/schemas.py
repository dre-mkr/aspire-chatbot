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


class VoiceErrorResponse(BaseModel):
    error: str
    fallback: str | None = None
