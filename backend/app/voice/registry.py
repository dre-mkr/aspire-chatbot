"""Persona x language -> voice configuration.

The one place voices are defined. Every id is overridable by environment
variable, and all twelve combinations are checked at startup so a missing
mapping surfaces as a boot failure rather than a 500 during a demo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from elevenlabs.types import VoiceSettings as ElevenVoiceSettings

from app.voice.config import VoiceSettings, get_voice_settings


class Persona(str, Enum):
    STELLA = "stella"
    ORION = "orion"
    AURORA = "aurora"
    NOVA = "nova"


class Language(str, Enum):
    EN = "en"
    ES = "es"
    FR = "fr"


@dataclass(frozen=True)
class VoiceProfile:
    persona: Persona
    language: Language
    voice_id: str
    model_id: str
    settings: ElevenVoiceSettings


# Per-persona delivery. Language changes the voice id (optionally) and the
# spoken language, never the character.
#
# speed accepts 0.7-1.2:
#   Stella is slowest -- five-year-olds need room between words.
#   Aurora sits at 1.0 with the highest stability: she is the voice a parent
#   has to trust, so consistency matters more than expressiveness.
_DELIVERY: dict[Persona, dict[str, float]] = {
    Persona.STELLA: {"stability": 0.45, "similarity_boost": 0.75, "style": 0.45, "speed": 0.90},
    Persona.ORION: {"stability": 0.55, "similarity_boost": 0.75, "style": 0.30, "speed": 1.0},
    Persona.AURORA: {"stability": 0.75, "similarity_boost": 0.80, "style": 0.10, "speed": 1.0},
    Persona.NOVA: {"stability": 0.60, "similarity_boost": 0.75, "style": 0.25, "speed": 0.95},
}


class VoiceRegistryError(RuntimeError):
    """Raised at startup when a persona x language pair has no voice."""


def _resolve_voice_id(
    settings: VoiceSettings, persona: Persona, language: Language
) -> str | None:
    """Per-language override first, then the persona's base voice."""
    specific = getattr(settings, f"voice_{persona.value}_{language.value}", None)
    base = getattr(settings, f"voice_{persona.value}", None)
    return (specific or base) or None


def build_registry(
    settings: VoiceSettings | None = None,
    *,
    model_id: str | None = None,
) -> dict[tuple[Persona, Language], VoiceProfile]:
    """Build every persona x language profile. Missing ids are left out.

    `model_id` overrides the live model, which is how the prewarm script builds
    the same registry against the higher-quality model.
    """
    settings = settings or get_voice_settings()
    chosen_model = model_id or settings.tts_model_live

    registry: dict[tuple[Persona, Language], VoiceProfile] = {}
    for persona in Persona:
        for language in Language:
            voice_id = _resolve_voice_id(settings, persona, language)
            if voice_id is None:
                continue
            registry[(persona, language)] = VoiceProfile(
                persona=persona,
                language=language,
                voice_id=voice_id,
                model_id=chosen_model,
                settings=ElevenVoiceSettings(**_DELIVERY[persona]),
            )
    return registry


def validate_registry(settings: VoiceSettings | None = None) -> None:
    """Fail loudly if any of the twelve combinations is unmapped.

    Called from the application lifespan. The message names the exact variables
    to set, because the person hitting this is usually mid-setup.
    """
    settings = settings or get_voice_settings()
    registry = build_registry(settings)

    missing = [
        (persona, language)
        for persona in Persona
        for language in Language
        if (persona, language) not in registry
    ]
    if not missing:
        return

    lines = [
        f"Voice registry incomplete: {len(missing)} of 12 persona/language "
        "combinations have no voice id.",
        "",
        "Set one variable per persona to cover all three languages:",
    ]
    lines += sorted({f"  VOICE_{p.value.upper()}=<elevenlabs_voice_id>" for p, _ in missing})
    lines += [
        "",
        "Or override a single language with e.g. VOICE_STELLA_ES=<voice_id>.",
        "To run without voice at all, set VOICE_ENABLED=false.",
    ]
    raise VoiceRegistryError("\n".join(lines))


@lru_cache(maxsize=1)
def get_registry() -> dict[tuple[Persona, Language], VoiceProfile]:
    return build_registry()


def resolve_profile(persona: Persona, language: Language) -> VoiceProfile:
    """Look up a profile. Raises KeyError only if startup validation was skipped."""
    try:
        return get_registry()[(persona, language)]
    except KeyError as exc:  # pragma: no cover - guarded by validate_registry
        raise VoiceRegistryError(
            f"No voice configured for {persona.value}/{language.value}. "
            f"Set VOICE_{persona.value.upper()} or "
            f"VOICE_{persona.value.upper()}_{language.value.upper()}."
        ) from exc
