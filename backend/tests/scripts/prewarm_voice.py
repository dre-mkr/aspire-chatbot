"""Fill the voice cache before a demo."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.voice.cache import cache_key, get_cache  # noqa: E402
from app.voice.client import VoiceUnavailable, get_client  # noqa: E402
from app.voice.config import get_voice_settings  # noqa: E402
from app.voice.registry import Language, Persona, build_registry  # noqa: E402
from app.prompting.personas.names import PLACEHOLDER, display_name  # noqa: E402
from app.voice.speakable import speakable  # noqa: E402

# Fixed lines the product says over and over. Keep in step with the frontend.
#
# `{name}` rather than the label, for the same reason the persona cards use it:
# these strings outlived two renames and warmed a cache full of audio speaking
# names no reader is shown any more. The substitution happens in `prewarm`.
#
# `everyone` has no label (`display_name` returns ""), so its lines never
# introduce themselves -- which is also how its card is written.
STATIC_LINES: dict[Persona, dict[Language, list[str]]] = {
    Persona.STELLA: {
        Language.EN: [
            "Hi! I'm {name}. Do you want to learn about saving money?",
            "That's right! Well done!",
            "Good try! Let's look at it together.",
            "Tap the big button and tell me your question.",
            "Oops, I didn't hear that. Can you say it again?",
        ],
        Language.ES: [
            "¡Hola! Soy {name}. ¿Quieres aprender a ahorrar dinero?",
            "¡Correcto! ¡Muy bien!",
            "¡Buen intento! Vamos a verlo juntos.",
            "Toca el botón grande y dime tu pregunta.",
            "Ups, no te escuché. ¿Puedes repetirlo?",
        ],
        Language.FR: [
            "Salut ! Je suis {name}. Tu veux apprendre à économiser ?",
            "C'est exact ! Bravo !",
            "Bon essai ! Regardons ensemble.",
            "Appuie sur le grand bouton et pose ta question.",
            "Oups, je n'ai pas entendu. Tu peux répéter ?",
        ],
    },
    Persona.ORION: {
        Language.EN: [
            "Hey, I'm {name}. Ask me anything about ASPIRE or your money.",
            "Good question. Here's how that works.",
            "Close, but not quite. Here's the part that trips people up.",
            "I didn't catch that. Try again?",
        ],
        Language.ES: [
            "Hola, soy {name}. Pregúntame lo que quieras sobre ASPIRE o tu dinero.",
            "Buena pregunta. Así funciona.",
            "Casi, pero no del todo. Esta es la parte que confunde a la gente.",
            "No te escuché bien. ¿Lo intentas de nuevo?",
        ],
        Language.FR: [
            "Salut, je suis {name}. Pose-moi tes questions sur ASPIRE ou ton argent.",
            "Bonne question. Voici comment ça marche.",
            "Presque, mais pas tout à fait. Voici ce qui piège souvent.",
            "Je n'ai pas bien entendu. Tu réessaies ?",
        ],
    },
    Persona.AURORA: {
        Language.EN: [
            "Hello, I'm {name}. I can help with registration, eligibility and statements.",
            "I don't have that information. Please contact the ASPIRE team directly.",
            "Let me confirm what the programme documentation says.",
            "I couldn't hear the recording clearly. Please try again.",
        ],
        Language.ES: [
            "Hola, soy {name}. Puedo ayudarle con el registro, la elegibilidad y los estados de cuenta.",
            "No tengo esa información. Por favor, contacte directamente con el equipo de ASPIRE.",
            "Permítame confirmar lo que dice la documentación del programa.",
            "No pude escuchar la grabación con claridad. Inténtelo de nuevo.",
        ],
        Language.FR: [
            "Bonjour, je suis {name}. Je peux vous aider pour l'inscription, l'éligibilité et les relevés.",
            "Je n'ai pas cette information. Veuillez contacter directement l'équipe ASPIRE.",
            "Laissez-moi vérifier ce que dit la documentation du programme.",
            "Je n'ai pas bien entendu l'enregistrement. Veuillez réessayer.",
        ],
    },
    Persona.NOVA: {
        Language.EN: [
            "Welcome! I'm {name}. I can explain what ASPIRE is and who can join.",
            "ASPIRE is free to join. There is no cost to families.",
            "I don't have that one, but here's who can help.",
            "Sorry, I missed that. Could you say it once more?",
        ],
        Language.ES: [
            "¡Bienvenido! Soy {name}. Puedo explicarte qué es ASPIRE y quién puede unirse.",
            "Unirse a ASPIRE es gratis. No hay ningún costo para las familias.",
            "No tengo esa información, pero aquí está quién puede ayudarte.",
            "Lo siento, no escuché eso. ¿Puedes repetirlo?",
        ],
        Language.FR: [
            "Bienvenue ! Je suis {name}. Je peux expliquer ce qu'est ASPIRE et qui peut y participer.",
            "L'adhésion à ASPIRE est gratuite. Il n'y a aucun coût pour les familles.",
            "Je n'ai pas cette information, mais voici qui peut vous aider.",
            "Désolée, je n'ai pas entendu. Pouvez-vous répéter ?",
        ],
    },
    Persona.EVERYONE: {
        Language.EN: [
            "Welcome to ASPIRE AI. Ask me about the programme, money or your modules.",
            "Here's the short answer, and then the detail.",
            "I don't have that in the ASPIRE material. Here's who can help.",
            "I didn't catch that. Could you say it again?",
        ],
        Language.ES: [
            "Bienvenido a ASPIRE AI. Pregúnteme sobre el programa, el dinero o sus módulos.",
            "Esta es la respuesta corta, y luego el detalle.",
            "No tengo eso en el material de ASPIRE. Aquí está quién puede ayudar.",
            "No escuché eso. ¿Puede repetirlo?",
        ],
        Language.FR: [
            "Bienvenue sur ASPIRE AI. Posez-moi vos questions sur le programme, l'argent ou vos modules.",
            "Voici la réponse courte, puis le détail.",
            "Je n'ai pas cela dans les documents ASPIRE. Voici qui peut vous aider.",
            "Je n'ai pas entendu. Pouvez-vous répéter ?",
        ],
    },
}


async def prewarm(personas: list[Persona], languages: list[Language], dry_run: bool) -> int:
    settings = get_voice_settings()
    # The quality model, on purpose: generated once, played many times.
    registry = build_registry(settings, model_id=settings.tts_model_quality)
    cache = get_cache()

    planned = 0
    characters = 0
    warmed = 0
    skipped = 0
    failed = 0

    for persona in personas:
        for language in languages:
            profile = registry.get((persona, language))
            if profile is None:
                print(f"  skip {persona.value}/{language.value}: no voice configured")
                continue

            label = display_name(persona.value)
            for line in STATIC_LINES.get(persona, {}).get(language, []):
                spoken = speakable(
                    line.replace(PLACEHOLDER, label),
                    language,
                    max_chars=settings.max_speakable_chars,
                )
                if not spoken:
                    continue
                planned += 1
                characters += len(spoken)

                key = cache_key(spoken, profile.voice_id, profile.model_id, profile.settings)
                if cache.get(key) is not None:
                    skipped += 1
                    continue
                if dry_run:
                    continue

                try:
                    audio = await get_client().synthesise(
                        spoken, profile.voice_id, profile.model_id, profile.settings
                    )
                except VoiceUnavailable as exc:
                    failed += 1
                    print(f"  FAILED {persona.value}/{language.value}: {exc}")
                    continue
                cache.put(key, audio)
                warmed += 1
                print(f"  warmed {persona.value}/{language.value}: {spoken[:56]}...")

    stats = cache.stats()
    print()
    print(f"lines considered : {planned}  ({characters} characters)")
    print(f"already cached   : {skipped}")
    if dry_run:
        # multilingual_v2 bills 1 credit per character.
        print(f"would synthesise : {planned - skipped} (~{characters} credits)")
    else:
        print(f"newly synthesised: {warmed}")
        print(f"failed           : {failed}")
    print(f"cache now        : {stats['entries']} files, {stats['bytes'] / 1_048_576:.1f} MB")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prewarm the ASPIRE voice cache.")
    parser.add_argument("--persona", choices=[p.value for p in Persona])
    parser.add_argument("--language", choices=[l.value for l in Language])
    parser.add_argument("--dry-run", action="store_true", help="Estimate cost, synthesise nothing.")
    args = parser.parse_args()

    personas = [Persona(args.persona)] if args.persona else list(Persona)
    languages = [Language(args.language)] if args.language else list(Language)

    if not get_voice_settings().voice_enabled:
        print("VOICE_ENABLED is false; nothing to prewarm.", file=sys.stderr)
        return 1

    return asyncio.run(prewarm(personas, languages, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
