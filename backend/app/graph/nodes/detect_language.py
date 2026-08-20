"""Whether the reader just changed the language this conversation is in.

The locale is minted into the session token and `hydrate` rewrites it from
those claims on every turn, so nothing downstream -- the eligibility card, the
sign-up chips, the refusal text, `Language(locale)` -- could ever see a reader
switch. The prose switched anyway, because a language model mirrors whatever it
is spoken to, and the furniture around it stayed English. That gap is the whole
bug this node closes.

Deliberately boring:

* No model call. This runs on every turn, and a demo cannot afford latency or a
  failure mode on the one thing it must get right.
* No new dependency. Three languages, decided by function words and accents.
* Fully deterministic, so every case below is a unit test rather than a hope.

Additive by construction: when it is not confident it returns an empty update
and the turn behaves exactly as it did before this node existed.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Final

from app.graph.nodes.safety_in import latest_user_text
from app.graph.state import AspireState, Locale

logger = logging.getLogger(__name__)

#: The locales the product has copy for. Anything else is not a switch we can honour.
LOCALES: Final[tuple[Locale, ...]] = ("en", "es", "fr")

#: Below this many words, prose is not evidence. "ok", "si", "oui", "yes please".
#:
#: `si` is Spanish for yes and an English typo for `is`; `oui` arrives in
#: English sentences from readers who speak both. A two-word message cannot
#: carry enough signal to be worth the cost of being wrong, and being wrong here
#: means the next answer, every card and every chip change language under
#: somebody who did not ask.
MIN_WORDS: Final[int] = 4

#: How far ahead a switch verb may sit from the language it names.
_REQUEST_GAP: Final[int] = 24


# ── what the reader may call each language ───────────────────────────────────
# In any of the three languages, because "speak english please" is as likely to
# arrive from a Spanish session as "hablame en ingles".

_NAMED: Final[dict[Locale, tuple[str, ...]]] = {
    "en": ("english", "ingles", "inglesa", "anglais", "anglaise"),
    "es": ("spanish", "espanol", "espanola", "espagnol", "espagnole", "castellano"),
    "fr": ("french", "francais", "francaise", "frances", "francesa"),
}

#: Verbs and prepositions that turn a language's name into a request for it.
_ASKING: Final[str] = (
    r"(?:in|into|to|en|dans|speak|speaks|speaking|talk|talking|say|write|writing"
    r"|answer|answering|reply|replying|respond|responding|switch|switched|change"
    r"|changed|use|using|prefer|want|habla|hablas|hablame|hablar|hablarme"
    r"|responde|responder|contesta|contestar|escribe|escribir|cambia|cambiar"
    r"|quiero|puedes|podrias|parle|parles|parlez|parler|reponds|repondre"
    r"|repondez|ecris|ecrire|ecrivez|change|voudrais|peux|pouvez)"
)

#: `<verb> ... <language>`, or the bare `in <language>` / `en <language>`.
_REQUESTS: Final[dict[Locale, re.Pattern[str]]] = {
    locale: re.compile(
        rf"\b{_ASKING}\b[^.\n?!]{{0,{_REQUEST_GAP}}}?\b(?:{'|'.join(names)})\b",
        re.IGNORECASE,
    )
    for locale, names in _NAMED.items()
}


# ── the function words each language does not share ──────────────────────────
# Written out per language and then reduced to what only ONE of them claims.
# `un`, `de`, `la`, `que`, `en`, `me` and `no` are each two languages' words, and
# counting them was how "Hola, quiero saber como puedo abrir una cuenta" scored
# as French. Exclusivity is computed below rather than curated by hand, so
# adding a word to one list cannot silently poison another.

_WORDS: Final[dict[Locale, tuple[str, ...]]] = {
    "en": (
        "the", "and", "is", "are", "was", "were", "what", "when", "where", "why",
        "how", "who", "which", "does", "did", "can", "could", "would", "should",
        "will", "my", "your", "our", "their", "this", "that", "these", "those",
        "with", "from", "about", "for", "have", "has", "had", "not", "but",
        "you", "it", "of", "to", "be", "been", "am", "if", "or", "so", "we",
        "they", "she", "there", "here", "please", "thanks", "thank", "want",
        "need", "know", "tell", "help", "make", "get", "more", "than", "then",
        "some", "any", "all", "much", "many", "money", "save", "saving",
        "savings", "account", "child", "daughter", "son", "open", "start",
        "much", "old", "years", "year",
    ),
    "es": (
        "el", "los", "las", "una", "unos", "unas", "del", "qué", "y", "es",
        "son", "está", "están", "estoy", "cómo", "como", "cuándo", "cuando",
        "dónde", "donde", "por", "para", "con", "sin", "pero", "más", "muy",
        "mi", "mis", "tu", "tus", "su", "sus", "yo", "él", "ella", "nosotros",
        "ellos", "se", "lo", "le", "les", "nos", "hay", "tiene", "tengo",
        "tienes", "puedo", "puede", "puedes", "quiero", "quiere", "quieres",
        "saber", "hacer", "dinero", "cuenta", "ahorrar", "ahorro", "ahorros",
        "niña", "niño", "hija", "hijo", "gracias", "hola", "buenos", "buenas",
        "necesito", "ayuda", "favor", "usted", "ustedes", "quién", "quien",
        "cuál", "cual", "abrir", "años", "también", "porque", "esta", "este",
    ),
    "fr": (
        "le", "les", "une", "des", "du", "et", "qui", "quoi", "est", "sont",
        "suis", "êtes", "comment", "quand", "où", "pourquoi", "pour", "par",
        "avec", "sans", "mais", "plus", "très", "mon", "ma", "mes", "ton", "ta",
        "tes", "sa", "ses", "je", "il", "elle", "nous", "vous", "ils", "elles",
        "ce", "cette", "ces", "ne", "pas", "ai", "avez", "avons", "peux",
        "peut", "pouvez", "veux", "veut", "voudrais", "savoir", "faire",
        "argent", "compte", "épargne", "épargner", "fille", "fils", "merci",
        "bonjour", "bonsoir", "besoin", "aide", "plaît", "quel", "quelle",
        "ouvrir", "ans", "aussi", "parce", "combien",
    ),
}


def _fold(text: str) -> str:
    """Lowercased and stripped of accents, so `cómo` and `como` are one word."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


#: `folded word -> the one locale that claims it`, built once at import.
_EXCLUSIVE: Final[dict[str, Locale]] = {}
for _locale, _vocabulary in _WORDS.items():
    for _word in _vocabulary:
        folded = _fold(_word)
        if folded in _EXCLUSIVE and _EXCLUSIVE[folded] != _locale:
            _EXCLUSIVE[folded] = ""  # type: ignore[assignment]
        else:
            _EXCLUSIVE.setdefault(folded, _locale)
_EXCLUSIVE = {word: locale for word, locale in _EXCLUSIVE.items() if locale}

#: Characters only one of the three writes. `é` is shared, so it is not here.
_MARKS: Final[dict[Locale, frozenset[str]]] = {
    "en": frozenset(),
    "es": frozenset("ñ¿¡íóúá"),
    "fr": frozenset("çœèêàùâîôûëï"),
}

#: Letters only -- so `EC$500` has no words in it, and a figure is never prose.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def words(text: str) -> list[str]:
    """The message's words, folded. Digits and currency are not words."""
    return [_fold(word) for word in _WORD.findall(text)]


def asked_for(text: str) -> Locale | None:
    """The language the reader asked for by name, if they asked for one.

    Honoured however short the message: "en francais" is two words and is not
    ambiguous about anything.
    """
    folded = _fold(text)
    matched = [locale for locale, pattern in _REQUESTS.items() if pattern.search(folded)]
    # Two languages named in one message is not a request, it is a sentence
    # about languages.
    return matched[0] if len(matched) == 1 else None


def score(text: str) -> dict[Locale, int]:
    """How much evidence there is for each language, by exclusive word and by mark."""
    tally: dict[Locale, int] = {locale: 0 for locale in LOCALES}
    for word in words(text):
        locale = _EXCLUSIVE.get(word)
        if locale is not None:
            tally[locale] += 1
    lowered = text.lower()
    for locale, marks in _MARKS.items():
        tally[locale] += sum(1 for char in lowered if char in marks)
    return tally


def detect(text: str) -> Locale | None:
    """The language this message is written in, or None when it is not clear.

    None is the common and correct answer. A switch costs the reader every card,
    chip and refusal in a language they did not choose, so the bar is a clear
    winner over enough words to be evidence -- not a best guess.
    """
    if len(words(text)) < MIN_WORDS:
        return None
    tally = score(text)
    ranked = sorted(tally.items(), key=lambda item: item[1], reverse=True)
    (winner, best), (_, runner_up) = ranked[0], ranked[1]
    # A borrowed word is not a switch: "What is the dinero limit for a new
    # account" is an English sentence with one Spanish noun in it, and it must
    # stay English.
    if best < 2 or best - runner_up < 2:
        return None
    return winner


def switched_to(text: str) -> Locale | None:
    """The language the reader moved to this turn, asked for or written."""
    return asked_for(text) or detect(text)


def detect_language(state: AspireState) -> dict[str, Any]:
    """Set `locale` when the reader changes language, and hold it after they do.

    Two jobs, and the second is the one that is easy to miss. `hydrate` rewrites
    `locale` from the token's claims at the top of every turn, so a switch made
    on turn three is gone by turn four unless something puts it back. That is
    what `locale_override` is: it lives in the checkpoint, `identity_from` never
    touches it, and this node re-applies it on every later turn.
    """
    text = latest_user_text(state)
    if not text.strip():
        return {}

    override = state.get("locale_override")
    detected = switched_to(text)
    target = detected or override
    if target is None:
        return {}

    update: dict[str, Any] = {}
    # Against the language this turn was ALREADY going to be answered in --
    # the override if one is held, otherwise the token's claim. An English
    # session writing English prose has not switched to anything, and recording
    # an override there would pin a session that never asked to be pinned.
    effective = override or state.get("locale")
    if detected is not None and detected != effective:
        update["locale_override"] = detected
    if target != state.get("locale"):
        update["locale"] = target
        logger.info(
            "session %s is now in %s (%s)",
            state.get("session_id"),
            target,
            "the reader switched" if detected else "holding an earlier switch",
        )
    return update
