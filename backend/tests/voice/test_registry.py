"""The registry must resolve every persona x language, and fail at startup if not.

The count is derived rather than written down: `everyone` was added as a fifth
persona after these tests were written, and a hard-coded 12 turned a deliberate
product change into three red tests that said nothing about voice.
"""

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
    """Voice settings built from nothing but what this test asks for."""
    blank: dict[str, str | None] = {}
    for persona in Persona:
        blank[f"voice_{persona.value}"] = None
        for language in Language:
            blank[f"voice_{persona.value}_{language.value}"] = None
    base = {
        **blank,
        "voice_stella": "voice-stella",
        "voice_orion": "voice-orion",
        "voice_aurora": "voice-aurora",
        "voice_nova": "voice-nova",
    }
    return VoiceSettings(_env_file=None, **{**base, **overrides})


def test_every_persona_and_language_resolves():
    registry = build_registry(_settings())
    assert len(registry) == len(Persona) * len(Language)
    for persona in Persona:
        for language in Language:
            assert (persona, language) in registry


def test_everyone_borrows_orions_voice_when_it_has_none_of_its_own():
    """A deployment provisioned before `everyone` existed must still boot."""
    registry = build_registry(_settings())
    for language in Language:
        assert registry[(Persona.EVERYONE, language)].voice_id == "voice-orion"


def test_an_explicit_everyone_voice_beats_the_understudy():
    registry = build_registry(_settings(voice_everyone="voice-everyone"))
    assert registry[(Persona.EVERYONE, Language.EN)].voice_id == "voice-everyone"


def test_validate_passes_when_complete():
    validate_registry(_settings())


def test_missing_persona_raises_and_names_the_variable():
    settings = _settings(voice_aurora=None)
    with pytest.raises(VoiceRegistryError) as exc:
        validate_registry(settings)
    message = str(exc.value)
    assert "VOICE_AURORA" in message
    assert f"3 of {len(Persona) * len(Language)}" in message


def test_losing_orion_also_loses_the_persona_that_borrows_it():
    """The understudy is a fallback, not a second source of ids."""
    settings = _settings(voice_orion=None)
    with pytest.raises(VoiceRegistryError) as exc:
        validate_registry(settings)
    message = str(exc.value)
    assert "VOICE_ORION" in message
    assert "VOICE_EVERYONE" in message
    assert f"6 of {len(Persona) * len(Language)}" in message


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
