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


#: The ceiling on `style`, which ElevenLabs documents as style EXAGGERATION.
#:
#: The brief asks for warmth and energy and then says, twice, that nothing may
#: sound exaggerated or performed. Past this the model starts acting rather than
#: reading, and it costs stability at the same time. Enforced by a test so a
#: later "make Sky more excited" cannot quietly cross it.
MAX_STYLE: Final[float] = 0.55

# Per-persona delivery.
#
# Four knobs, and only two of them do what their names suggest:
#   stability        LOW is expressive and variable, HIGH is even and flat.
#   similarity_boost how hard to hold the original voice's timbre.
#   style            exaggeration. See MAX_STYLE.
#   speed            0.7 to 1.2. The one knob a reader actually notices.
#
# Accent is NOT here, because ElevenLabs has no accent parameter. A Caribbean
# voice is chosen by picking a Caribbean voice id -- see `VOICE_*` in .env and
# the note in README. Nothing in this table can add or remove an accent.
_DELIVERY: dict[Persona, dict[str, float]] = {
    # Ages 5-12. Warm and encouraging, and the slowest of the five because a
    # six-year-old is decoding the words as they arrive. Expressive (low
    # stability) but under the exaggeration ceiling: playful, not cartoonish.
    Persona.STELLA: {"stability": 0.50, "similarity_boost": 0.75, "style": 0.40, "speed": 0.88},
    # Ages 13-18. Livelier than an adult read and deliberately not slowed --
    # a teenager hearing a children's pace hears condescension.
    Persona.ORION: {"stability": 0.50, "similarity_boost": 0.75, "style": 0.35, "speed": 1.0},
    # Parents and guardians. The most even voice of the five: this is the one
    # answering eligibility, registration and money questions, and it has to be
    # trusted rather than liked. Fractionally under pace, which reads as calm.
    Persona.AURORA: {"stability": 0.78, "similarity_boost": 0.80, "style": 0.08, "speed": 0.98},
    # Teachers. Close to Aurora and a step more articulate: near-flat delivery
    # so a definition lands cleanly, and slightly slower for the same reason.
    Persona.NOVA: {"stability": 0.70, "similarity_boost": 0.78, "style": 0.15, "speed": 0.96},
    # Between Orion's evenness and Aurora's steadiness: the reader is unknown, so
    # the delivery commits to nothing.
    Persona.EVERYONE: {
        "stability": 0.65,
        "similarity_boost": 0.75,
        "style": 0.18,
        "speed": 0.98,
    },
}

#: The knobs an env var may override, and the `VoiceSettings` field per persona.
_TUNABLE: Final[tuple[str, ...]] = ("stability", "similarity_boost", "style", "speed")


def _delivery_for(settings: VoiceSettings, persona: Persona) -> dict[str, float]:
    """The table above, with any `VOICE_<PERSONA>_<KNOB>` override applied.

    Tuning a voice is done by ear, by someone listening -- not by reading a
    diff. Leaving the only way to do it as a code change meant every "a little
    slower" was an edit, a test update and a deploy. These are optional: unset,
    the table stands.
    """
    values = dict(_DELIVERY[persona])
    for knob in _TUNABLE:
        override = getattr(settings, f"voice_{persona.value}_{knob}", None)
        if override is not None:
            values[knob] = override
    return values

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
                settings=ElevenVoiceSettings(**_delivery_for(settings, persona)),
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
