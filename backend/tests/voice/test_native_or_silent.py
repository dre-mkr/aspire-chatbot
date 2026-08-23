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
        """Kaleb understudies Stella. If her Spanish is cast, his Spanish is a
        Spanish-cast voice -- the wrong character, which is the tradeoff every
        understudy already is, but never the wrong language."""
        registry = build_registry(_settings(voice_stella_es="stella-es"))
        profile = registry[(Persona.KALEB, Language.ES)]
        assert profile.native is True
        assert profile.voice_id == "stella-es"

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
        # Stella ES is cast; Kaleb ES rides it via the understudy. Everything
        # else non-English is silent until somebody casts it.
        assert (Persona.STELLA, Language.ES) not in pairs
        assert (Persona.KALEB, Language.ES) not in pairs
        assert (Persona.STELLA, Language.FR) in pairs
        assert all(language is not Language.EN for _, language in pairs)

    def test_a_fully_cast_deployment_has_no_uncast_pairs(self):
        cast = {
            f"voice_{p.value}_{lang.value}": f"{p.value}-{lang.value}"
            for p in Persona
            for lang in (Language.ES, Language.FR)
        }
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

    def test_english_is_never_refused(self):
        from app.voice.router import _require_native

        registry = build_registry(_settings())
        for persona in Persona:
            _require_native(registry[(persona, Language.EN)])
