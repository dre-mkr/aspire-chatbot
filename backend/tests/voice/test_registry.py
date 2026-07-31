"""The registry must resolve all twelve combinations, and fail at startup if not."""

import pytest

from app.voice.config import VoiceSettings
from app.voice.registry import (
    Language,
    Persona,
    VoiceRegistryError,
    build_registry,
    validate_registry,
)


def _settings(**overrides) -> VoiceSettings:
    # _env_file=None so a developer's real .env cannot influence the result.
    base = {
        "voice_stella": "voice-stella",
        "voice_orion": "voice-orion",
        "voice_aurora": "voice-aurora",
        "voice_nova": "voice-nova",
    }
    return VoiceSettings(_env_file=None, **{**base, **overrides})


def test_all_twelve_combinations_resolve():
    registry = build_registry(_settings())
    assert len(registry) == 12
    for persona in Persona:
        for language in Language:
            assert (persona, language) in registry


def test_validate_passes_when_complete():
    validate_registry(_settings())


def test_missing_persona_raises_and_names_the_variable():
    settings = _settings(voice_aurora=None)
    with pytest.raises(VoiceRegistryError) as exc:
        validate_registry(settings)
    message = str(exc.value)
    assert "VOICE_AURORA" in message
    assert "3 of 12" in message


def test_per_language_override_beats_the_base_voice():
    registry = build_registry(_settings(voice_stella_es="voice-stella-spanish"))
    assert registry[(Persona.STELLA, Language.ES)].voice_id == "voice-stella-spanish"
    assert registry[(Persona.STELLA, Language.EN)].voice_id == "voice-stella"


def test_per_language_override_alone_is_enough():
    """A persona configured only per-language still resolves that language."""
    registry = build_registry(_settings(voice_nova=None, voice_nova_fr="voice-nova-french"))
    assert (Persona.NOVA, Language.FR) in registry
    assert (Persona.NOVA, Language.EN) not in registry


def test_delivery_matches_the_brief():
    registry = build_registry(_settings())
    stella = registry[(Persona.STELLA, Language.EN)].settings
    aurora = registry[(Persona.AURORA, Language.EN)].settings

    # Five-year-olds need it slower.
    assert stella.speed == pytest.approx(0.90)
    # Aurora is the institutional voice: normal pace, highest stability.
    assert aurora.speed == pytest.approx(1.0)
    assert aurora.stability > stella.stability


def test_every_speed_is_within_the_supported_range():
    for profile in build_registry(_settings()).values():
        assert 0.7 <= profile.settings.speed <= 1.2


def test_model_override_is_applied():
    registry = build_registry(_settings(), model_id="eleven_multilingual_v2")
    assert all(p.model_id == "eleven_multilingual_v2" for p in registry.values())
