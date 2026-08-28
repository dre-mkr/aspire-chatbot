"""An English-trained voice never speaks Spanish or French to a reader.

That is the client's rule, stated as an absolute, and this file is what makes
it structural rather than aspirational. The registry has always resolved an
ES/FR pair through the persona's base id when no per-language id was set --
which boots cleanly, works in the demo, and hands a French-speaking child an
English accent mangling their language in the one channel built for readers
who cannot yet read well.

The enforcement is NATIVE OR SILENT:

  * resolution still succeeds -- boot is unchanged, `validate_registry` still
    guards the truly-unmapped;
  * every profile now knows whether it was cast FOR its language;
  * the speech endpoints refuse a non-native profile with the same fallback
    the player already handles for an upstream outage. Text is never touched.

There is deliberately NO override flag. The override is casting the voice:
`VOICE_{PERSONA}_{ES|FR}`, and a restart.
"""

from __future__ import annotations

import pytest

from app.voice.config import VoiceSettings
from app.voice.registry import (
    Language,
    Persona,
    build_registry,
    uncast_pairs,
    validate_registry,
)


def _settings(**overrides) -> VoiceSettings:
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


class TestWhatCountsAsNative:
    def test_english_on_a_base_id_is_native(self):
        """The base ids ARE the English casting."""
        registry = build_registry(_settings())
        assert registry[(Persona.STELLA, Language.EN)].native is True

    @pytest.mark.parametrize("language", [Language.ES, Language.FR])
    def test_a_base_id_is_not_native_for_any_other_language(self, language):
        registry = build_registry(_settings())
        assert registry[(Persona.STELLA, language)].native is False

    def test_a_per_language_id_is_native(self):
        registry = build_registry(_settings(voice_stella_es="stella-es"))
        profile = registry[(Persona.STELLA, Language.ES)]
        assert profile.native is True
        assert profile.voice_id == "stella-es"

    def test_an_understudys_per_language_id_carries_nativeness(self):
        """Guest understudies Imani. If Imani's Spanish is cast, Guest's Spanish
        is a Spanish-cast voice -- the wrong character, which is the tradeoff
        every understudy already is, but never the wrong language.

        Kaleb used to be the example here and no longer qualifies: he is in
        `_NEVER_BORROWS_A_VOICE`, so his Spanish is silent whoever else is cast.
        See `TestKalebNeverBorrows` below.
        """
        registry = build_registry(_settings(voice_aurora_es="aurora-es"))
        profile = registry[(Persona.GUEST, Language.ES)]
        assert profile.native is True
        assert profile.voice_id == "aurora-es"

    def test_an_understudys_base_id_does_not(self):
        registry = build_registry(_settings())
        assert registry[(Persona.KALEB, Language.FR)].native is False


class TestBootIsUnchanged:
    def test_validation_still_passes_with_only_base_ids(self):
        """The rule silences a pair; it must never take the whole app down.
        `validate_registry` keeps guarding the truly-unmapped, nothing more."""
        validate_registry(_settings())

    def test_every_pair_still_resolves(self):
        registry = build_registry(_settings())
        assert len(registry) == len(Persona) * len(Language)


class TestTheAudit:
    def test_uncast_pairs_names_exactly_the_silent_ones(self):
        pairs = uncast_pairs(_settings(voice_stella_es="stella-es"))
        # Stella ES is cast. Everything else non-English is silent until
        # somebody casts it -- and Kaleb is silent in every language, English
        # included, because he has no voice of his own to be native in.
        assert (Persona.STELLA, Language.ES) not in pairs
        assert (Persona.KALEB, Language.ES) in pairs
        assert (Persona.STELLA, Language.FR) in pairs
        assert all(
            language is not Language.EN
            for persona, language in pairs
            if persona is not Persona.KALEB
        )

    def test_a_fully_cast_deployment_has_no_uncast_pairs(self):
        """FULLY cast now includes `VOICE_KALEB`.

        The fixture used to call a deployment fully cast while never giving
        Kaleb a voice at all -- he rode Stella's. That is the thing this build
        stopped doing, so a deployment is not complete until he has his own.
        """
        cast = {
            f"voice_{p.value}_{lang.value}": f"{p.value}-{lang.value}"
            for p in Persona
            for lang in (Language.ES, Language.FR)
        }
        cast["voice_kaleb"] = "voice-kaleb"
        assert uncast_pairs(_settings(**cast)) == []


class TestTheEndpointRefuses:
    """The router half: a non-native profile gets the browser fallback."""

    def test_a_non_native_profile_is_refused_with_the_uncast_detail(self):
        from fastapi import HTTPException

        from app.voice.router import _require_native

        registry = build_registry(_settings())
        with pytest.raises(HTTPException) as caught:
            _require_native(registry[(Persona.STELLA, Language.FR)])
        assert caught.value.status_code == 503
        assert caught.value.detail["error"] == "voice_uncast"
        assert caught.value.detail["fallback"] == "browser"

    def test_a_native_profile_passes_untouched(self):
        from app.voice.router import _require_native

        registry = build_registry(_settings(voice_stella_fr="stella-fr"))
        _require_native(registry[(Persona.STELLA, Language.FR)])  # no raise

    def test_english_is_never_refused_for_a_persona_with_its_own_voice(self):
        """The base ids ARE the English casting, so English plays.

        Kaleb is excluded because in this fixture he HAS no base id -- he would
        be speaking in Skye's voice, and the whole point of
        `_NEVER_BORROWS_A_VOICE` is that he does not. Give him one and the rule
        below shows English coming straight back on.
        """
        from app.voice.router import _require_native

        registry = build_registry(_settings())
        for persona in Persona:
            if persona is Persona.KALEB:
                continue
            _require_native(registry[(persona, Language.EN)])

    def test_kalebs_english_comes_back_the_moment_he_is_cast(self):
        from app.voice.router import _require_native

        registry = build_registry(_settings(voice_kaleb="voice-kaleb"))
        _require_native(registry[(Persona.KALEB, Language.EN)])  # no raise


class TestKalebNeverBorrows:
    """He boots on the understudy id and is refused audio in it.

    The trade this makes is real and worth naming: until `VOICE_KALEB` is set,
    the 9-12 band has NO audio at all rather than Skye's. That is the same
    choice already made for an uncast language -- text intact, no sound, rather
    than sound that tells the reader this was not built for them.
    """

    @pytest.mark.parametrize("language", list(Language))
    def test_he_is_silent_in_every_language_until_he_is_cast(self, language):
        registry = build_registry(_settings(voice_stella_es="stella-es",
                                            voice_stella_fr="stella-fr"))
        assert registry[(Persona.KALEB, language)].native is False

    def test_he_still_boots(self):
        """Silencing him must never take the app down."""
        validate_registry(_settings())
        registry = build_registry(_settings())
        assert (Persona.KALEB, Language.EN) in registry

    def test_casting_him_ends_it(self):
        registry = build_registry(_settings(voice_kaleb="voice-kaleb"))
        profile = registry[(Persona.KALEB, Language.EN)]
        assert profile.native is True
        assert profile.voice_id == "voice-kaleb"
