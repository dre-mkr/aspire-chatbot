"""Authored chips and reactions, in the three languages the product ships.

The corpus-derived chips are machine-localised in `safety_out`; these are the
AUTHORED ones -- game reactions, lesson chips, the hint ladder's buttons --
which were English wherever they were written. One table, so a Spanish lesson
never again ends under English buttons.
"""

from __future__ import annotations

_LINES: dict[str, dict[str, str]] = {
    "got_it": {"en": "Got it", "es": "Entendido", "fr": "Compris"},
    "say_again": {"en": "Say that again", "es": "Dímelo otra vez", "fr": "Redis-le-moi"},
    "say_it_again": {"en": "Say it again", "es": "Dilo otra vez", "fr": "Redis-le"},
    "next": {"en": "Next", "es": "Siguiente", "fr": "Suivant"},
    "again": {"en": "Again", "es": "Otra vez", "fr": "Encore"},
    "play_again": {"en": "Play again", "es": "Jugar otra vez", "fr": "Rejouer"},
    "back_to_lesson": {
        "en": "Back to the lesson", "es": "Volver a la lección", "fr": "Retour à la leçon",
    },
    "back_lesson_short": {"en": "Back to lesson", "es": "A la lección", "fr": "À la leçon"},
    "try_again": {"en": "Try again", "es": "Intentar de nuevo", "fr": "Réessayer"},
    "tell_answer": {
        "en": "Tell me the answer", "es": "Dime la respuesta", "fr": "Dis-moi la réponse",
    },
    "let_me_try": {"en": "Let me try one", "es": "Déjame intentar uno", "fr": "Laisse-moi essayer"},
    "let_me_try_again": {
        "en": "Let me try again", "es": "Déjame intentar de nuevo", "fr": "Laisse-moi réessayer",
    },
    "show_answer": {
        "en": "Show me the answer", "es": "Muéstrame la respuesta", "fr": "Montre-moi la réponse",
    },
    "that_helps": {"en": "That helps", "es": "Eso ayuda", "fr": "Ça aide"},
    "still_stuck": {"en": "Still stuck", "es": "Sigo atascado", "fr": "Toujours bloqué"},
    "show_number": {
        "en": "Show me a number", "es": "Muéstrame un número", "fr": "Montre-moi un nombre",
    },
    "okay": {"en": "Okay", "es": "Vale", "fr": "D'accord"},
    "go_back": {
        "en": "Go back to the other one", "es": "Volver a la otra", "fr": "Revenir à l'autre",
    },
    "say_more": {"en": "Say more", "es": "Cuéntame más", "fr": "Dis-m'en plus"},
    "something_else": {"en": "Something else", "es": "Otra cosa", "fr": "Autre chose"},
    "watch_video": {
        "en": "🎬 Watch the video", "es": "🎬 Ver el vídeo", "fr": "🎬 Voir la vidéo",
    },
}

#: Game score reactions. `{score}` and `{total}` are filled in.
_REACTIONS: dict[str, dict[str, str]] = {
    "stopped": {
        "en": "You got {score} before we stopped. Want to pick it up again, or carry on with the lesson?",
        "es": "Llevabas {score} cuando paramos. ¿Quieres retomarlo, o seguimos con la lección?",
        "fr": "Tu avais {score} quand on s'est arrêtés. Tu veux reprendre, ou continuer la leçon ?",
    },
    "high_young": {
        "en": "{score} out of {total}! You knew those.",
        "es": "¡{score} de {total}! Te las sabías.",
        "fr": "{score} sur {total} ! Tu les connaissais.",
    },
    "high": {
        "en": "{score} out of {total}. You have that one.",
        "es": "{score} de {total}. Eso ya lo dominas.",
        "fr": "{score} sur {total}. C'est acquis.",
    },
    "mid_young": {
        "en": "{score} out of {total}. Good going -- let us look at the tricky ones.",
        "es": "{score} de {total}. ¡Bien! Veamos las difíciles.",
        "fr": "{score} sur {total}. Bien joué — regardons les difficiles.",
    },
    "mid": {
        "en": "{score} out of {total}. Solid. The ones you missed are the ones worth going over.",
        "es": "{score} de {total}. Sólido. Las que fallaste son las que vale la pena repasar.",
        "fr": "{score} sur {total}. Solide. Celles que tu as manquées valent la peine d'être revues.",
    },
    "low_young": {
        "en": "You got {score}. That one was tricky! Let us do it together.",
        "es": "Conseguiste {score}. ¡Esa era difícil! Hagámoslo juntos.",
        "fr": "Tu as eu {score}. C'était difficile ! Faisons-le ensemble.",
    },
    "low": {
        "en": "{score} out of {total} -- that set was a hard one. Let us go back over it and try again after.",
        "es": "{score} de {total} — esa serie era dura. Repasémosla y lo intentamos de nuevo después.",
        "fr": "{score} sur {total} — cette série était dure. Revoyons-la et réessayons après.",
    },
}


def line(key: str, locale: str) -> str:
    entry = _LINES[key]
    return entry.get(locale, entry["en"])


def chips(keys: list[str], locale: str) -> list[str]:
    return [line(key, locale) for key in keys]


def reaction(key: str, locale: str, *, score: int, total: int) -> str:
    entry = _REACTIONS[key]
    return entry.get(locale, entry["en"]).format(score=score, total=total)
