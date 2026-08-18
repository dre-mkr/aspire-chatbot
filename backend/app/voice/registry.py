"""Persona x language -> voice configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from elevenlabs.types import VoiceSettings as ElevenVoiceSettings

# Re-exported: callers have always reached for these through this module.
from app.domain import Language, Persona
from app.voice.config import VoiceSettings, get_voice_settings


@dataclass(frozen=True)
class VoiceProfile:
    persona: Persona
    language: Language
    voice_id: str
    model_id: str
    settings: ElevenVoiceSettings


# Per-persona delivery.
_DELIVERY: dict[Persona, dict[str, float]] = {
    Persona.STELLA: {"stability": 0.45, "similarity_boost": 0.75, "style": 0.45, "speed": 0.90},
    Persona.ORION: {"stability": 0.55, "similarity_boost": 0.75, "style": 0.30, "speed": 1.0},
    Persona.AURORA: {"stability": 0.75, "similarity_boost": 0.80, "style": 0.10, "speed": 1.0},
    Persona.NOVA: {"stability": 0.60, "similarity_boost": 0.75, "style": 0.25, "speed": 0.95},
    # Between Orion's evenness and Aurora's steadiness: the reader is unknown, so
    # the delivery commits to nothing.
    Persona.EVERYONE: {
        "stability": 0.65,
        "similarity_boost": 0.75,
        "style": 0.20,
        "speed": 0.97,
    },
}

#: Personas that may borrow another's voice id rather than fail startup.
#:
#: `everyone` arrived after the twelve ids were provisioned, and a deployment
#: that has not been given a thirteenth should keep speaking rather than refuse
#: to boot. Orion is the understudy because it is the most neutral of the four.
#: An explicit VOICE_EVERYONE always wins over this.
_VOICE_UNDERSTUDY: dict[Persona, Persona] = {Persona.EVERYONE: Persona.ORION}


class VoiceRegistryError(RuntimeError):
    """Raised at startup when a persona x language pair has no voice."""


def _resolve_voice_id(
    settings: VoiceSettings, persona: Persona, language: Language
) -> str | None:
    """Per-language override first, then the persona's base voice, then its understudy."""
    specific = getattr(settings, f"voice_{persona.value}_{language.value}", None)
    base = getattr(settings, f"voice_{persona.value}", None)
    resolved = (specific or base) or None
    if resolved is not None:
        return resolved

    understudy = _VOICE_UNDERSTUDY.get(persona)
    if understudy is None:
        return None
    return _resolve_voice_id(settings, understudy, language)


def build_registry(
    settings: VoiceSettings | None = None,
    *,
    model_id: str | None = None,
) -> dict[tuple[Persona, Language], VoiceProfile]:
    """Build every persona x language profile."""
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
    """Fail loudly if any persona x language combination is unmapped."""
    settings = settings or get_voice_settings()
    registry = build_registry(settings)
    total = len(Persona) * len(Language)

    missing = [
        (persona, language)
        for persona in Persona
        for language in Language
        if (persona, language) not in registry
    ]
    if not missing:
        return

    lines = [
        f"Voice registry incomplete: {len(missing)} of {total} persona/language "
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
