"""ASPIRE voice layer: ElevenLabs speech-to-text and text-to-speech."""

from app.voice.config import VoiceSettings, get_voice_settings
from app.voice.registry import (
    Language,
    Persona,
    VoiceProfile,
    VoiceRegistryError,
    validate_registry,
)
# Exported as `voice_router`, not `router`: re-exporting the name `router` here would shadow the `app.voice.rou…
from app.voice.router import router as voice_router
from app.voice.speakable import speakable

__all__ = [
    "Language",
    "Persona",
    "VoiceProfile",
    "VoiceRegistryError",
    "VoiceSettings",
    "get_voice_settings",
    "speakable",
    "validate_registry",
    "voice_router",
]
