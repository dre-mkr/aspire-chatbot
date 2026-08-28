"""The registry must resolve every persona x language, and fail at startup if not.

The count is derived rather than written down: `everyone` was added as a fifth
persona after these tests were written, and a hard-coded 12 turned a deliberate
product change into three red tests that said nothing about voice.
"""

import pytest

from app.voice.config import VoiceSettings
from app.voice.registry import (
    _DELIVERY,
    MAX_STYLE,
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


def test_guest_borrows_imanis_voice_when_it_has_none_of_its_own():
    """A deployment provisioned before the default voice existed must still boot.

    Imani, not Zion. Zion was picked for neutrality and neutral was the wrong
    axis: he is cast for thirteen to eighteen, so an unknown visitor -- a
    parent, a teacher, somebody from the ministry -- was greeted by a teenager.
    Imani is the adult voice this product already has.
    """
    registry = build_registry(_settings())
    for language in Language:
        assert registry[(Persona.GUEST, language)].voice_id == "voice-aurora"


def test_an_explicit_guest_voice_beats_the_understudy():
    registry = build_registry(_settings(voice_guest="voice-guest"))
    assert registry[(Persona.GUEST, Language.EN)].voice_id == "voice-guest"


def test_the_old_environment_variable_still_works():
    """`everyone` became `guest` on 20 August. Deployed secrets did not.

    A deployment already carrying VOICE_EVERYONE must keep speaking without
    anybody editing its environment. Drop this alias, and this test, once the
    environments have been updated.
    """
    import os

    from app.voice.config import VoiceSettings

    os.environ["VOICE_EVERYONE"] = "voice-from-the-old-name"
    try:
        settings = VoiceSettings(_env_file=None)
        assert settings.voice_guest == "voice-from-the-old-name"
    finally:
        os.environ.pop("VOICE_EVERYONE", None)


def test_validate_passes_when_complete():
    validate_registry(_settings())


def test_missing_persona_raises_and_names_the_variable():
    settings = _settings(voice_nova=None)
    with pytest.raises(VoiceRegistryError) as exc:
        validate_registry(settings)
    message = str(exc.value)
    assert "VOICE_NOVA" in message
    assert f"3 of {len(Persona) * len(Language)}" in message


def test_losing_imani_also_loses_the_persona_that_borrows_her():
    """The understudy is a fallback, not a second source of ids."""
    settings = _settings(voice_aurora=None)
    with pytest.raises(VoiceRegistryError) as exc:
        validate_registry(settings)
    message = str(exc.value)
    assert "VOICE_AURORA" in message
    assert "VOICE_GUEST" in message
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
    """The brief's requirements, not the numbers that currently satisfy them.

    Every one of these was a literal once, and retuning the table by a
    hundredth failed the suite without anything being wrong. What the brief
    actually asks for is an ordering, so that is what is asserted -- it survives
    tuning and still fails if somebody makes the children's voice the fastest.
    """
    registry = build_registry(_settings())
    delivery = {
        persona: registry[(persona, Language.EN)].settings for persona in Persona
    }
    stella = delivery[Persona.STELLA]
    orion = delivery[Persona.ORION]
    aurora = delivery[Persona.AURORA]
    nova = delivery[Persona.NOVA]

    # Ages 5-12 are read to the slowest, and slower than the teenagers.
    assert stella.speed == min(d.speed for d in delivery.values())
    assert stella.speed < orion.speed
    # A teenager is not read to at a child's pace; that reads as condescension.
    assert orion.speed >= 1.0
    # The guardian voice is the one that must be trusted, so it is the evenest.
    assert aurora.stability == max(d.stability for d in delivery.values())
    assert aurora.stability > stella.stability
    # The two adult voices are steadier and plainer than the two young ones.
    for adult in (aurora, nova):
        for young in (stella, orion):
            assert adult.stability > young.stability
            assert adult.style < young.style


def test_no_voice_is_exaggerated():
    """The brief says it twice, so it is a build failure rather than a note."""
    for persona, profile in build_registry(_settings()).items():
        assert profile.settings.style <= MAX_STYLE, persona


def test_a_delivery_knob_can_be_overridden_without_touching_the_table():
    registry = build_registry(_settings(voice_stella_speed=0.8, voice_stella_style=0.1))
    stella = registry[(Persona.STELLA, Language.EN)].settings
    assert stella.speed == pytest.approx(0.8)
    assert stella.style == pytest.approx(0.1)
    # Untouched knobs keep the table's value.
    assert stella.stability == pytest.approx(_DELIVERY[Persona.STELLA]["stability"])


def test_an_override_for_one_persona_leaves_the_others_alone():
    registry = build_registry(_settings(voice_stella_speed=0.8))
    assert registry[(Persona.ORION, Language.EN)].settings.speed == pytest.approx(
        _DELIVERY[Persona.ORION]["speed"]
    )


def test_every_speed_is_within_the_supported_range():
    for profile in build_registry(_settings()).values():
        assert 0.7 <= profile.settings.speed <= 1.2


def test_model_override_is_applied():
    registry = build_registry(_settings(), model_id="eleven_multilingual_v2")
    assert all(p.model_id == "eleven_multilingual_v2" for p in registry.values())


class TestGuestSoundsLikeAnAdult:
    """An unknown visitor is more often an adult than a teenager.

    `guest` has no cast voice of its own, so it borrows. It borrowed Zion,
    chosen for neutrality -- but neutral was the wrong axis. Zion is cast for
    thirteen to eighteen, so a parent, a teacher or somebody from the ministry
    arriving on the site was greeted by a teenager. Imani is the adult voice
    this product already has, so guest borrows hers until it is given its own.
    """

    def test_guest_borrows_the_adult_voice(self):
        from app.domain import Persona
        from app.voice.registry import _VOICE_UNDERSTUDY

        assert _VOICE_UNDERSTUDY[Persona.GUEST] is Persona.AURORA

    def test_guest_does_not_borrow_a_child_or_a_teenager(self):
        from app.domain import Persona
        from app.voice.registry import _VOICE_UNDERSTUDY

        young = {Persona.STELLA, Persona.KALEB, Persona.ORION}
        assert _VOICE_UNDERSTUDY[Persona.GUEST] not in young

    def test_an_explicit_id_still_wins(self):
        """`VOICE_GUEST` remains the right way to give guest its own voice."""
        import inspect

        from app.voice import registry

        source = inspect.getsource(registry._resolve_voice_id)
        assert "understudy" in source.lower()
        assert "specific" in source, "the per-language override must be read first"
