"""Recognising the two questions that are answered by a card, not by prose.

    "Can my daughter join?"     → the eligibility check
    "Can we play a game?"       → a game

Both were tools in v1, which meant a model call decided them. Here they are
matched deterministically, before retrieval, and that is an upgrade rather than
a downgrade for three separate reasons:

  * **It cannot be talked out of it.** A tool description is a request. A child
    who writes "actually just tell me the rules, do not open the card" could
    talk the v1 agent out of calling `start_eligibility_check`, and the answer
    they then got was the model's unaudited paraphrase of eligibility rules.
    A regex has no opinion about being asked nicely.

  * **It costs nothing.** The v1 path paid a full model round trip with 979
    tokens of card instructions in the system prompt to find out whether this
    turn was a card. Matching here happens before anything is embedded.

  * **It cannot leak.** A model that decides to open the card can also decide
    to summarise what the card is about to say. The node below returns NO prose
    at all -- there is no text for the model to have produced, because the model
    is never called.

## What this deliberately does NOT match

A question about ONE rule is an ordinary question and gets an ordinary,
retrieved, cited answer:

    "what is the minimum age?"      "does Nevis count?"
    "how old do you have to be?"    "is there an income limit?"

`_LOOKUP` is checked first and wins. The distinction being drawn is between
somebody working out whether *they* can join -- which the card answers
personally, with the right document list -- and somebody looking up a fact,
which the knowledge base answers better than a six-question flow.

Getting this wrong in the lookup direction is cheap: the reader gets an accurate
cited sentence. Getting it wrong in the card direction is not: it interrupts a
simple question with a six-step form. Hence lookups win ties.

## Three languages, because the question is asked in three

The trigger lists are transliterated to ASCII before matching (`_fold`), so
"suis-je trop âgé" and "suis-je trop age" are one pattern rather than two, and a
phone keyboard without accents does not silently fall out of the feature.
"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def _fold(text: str) -> str:
    """Lowercase, strip accents, normalise apostrophes, collapse whitespace.

    Apostrophes are the fiddly one: a phone autocorrects `puis-je m'inscrire` to
    a typographic `’`, and a pattern written with a straight quote then misses
    every real message while passing every test.
    """
    lowered = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    stripped = stripped.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", stripped).strip()


#: Checked FIRST. A match here means an ordinary retrieved answer, whatever else
#: also matches. See the module docstring for why lookups win ties.
_LOOKUP: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bwhat(?:'s| is| are)? the (?:minimum|maximum|max|min) ",
        r"\bminimum age\b",
        r"\bmaximum age\b",
        r"\bage (?:limit|range|requirement)",
        r"\bhow old do (?:you|they|children|kids) have to be\b",
        r"\bis there (?:an? )?(?:income|age|savings) (?:limit|cap|requirement)",
        r"\b(?:does|do) (?:nevis|st kitts|saint kitts|basseterre|charlestown)\b",
        r"\bedad (?:minima|maxima)\b",
        r"\bage (?:minimum|maximum)\b",
    )
)

#: "Can *I* join?" -- somebody working out their own position, not looking a
#: rule up. Every one of these is drawn from the trigger list v1 put in
#: `start_eligibility_check`'s description, which is where the real phrasings
#: were collected.
_ELIGIBILITY: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        # ── English ──────────────────────────────────────────────────────────
        r"\bam i (?:eligible|able to join|too old|too young|old enough)\b",
        r"\b(?:can|could|may) (?:i|we|my (?:son|daughter|child|kid|children|kids|boy|girl))\b"
        r".{0,24}\b(?:join|apply|sign up|register|enrol|enroll|participate|take part|get an account)\b",
        r"\bdo(?:es)? (?:i|we|my (?:son|daughter|child|kid)) (?:qualify|meet)\b",
        r"\bwho (?:is|are) eligible\b",
        r"\bwho can (?:join|apply|sign up|register|participate)\b",
        r"\bam i (?:the )?right age\b",
        r"\bhow (?:can|do) (?:i|we) (?:apply|join|sign up|register|enrol|enroll)\b",
        r"\bhow (?:to|do you) (?:apply|join|sign up|register)\b",
        r"\bwhat do (?:i|we) need to (?:apply|join|sign up|register)\b",
        r"\bwhat (?:documents|papers|paperwork) do (?:i|we) need\b",
        r"\b(?:eligibility|elegibility) check\b",
        # ── Spanish ──────────────────────────────────────────────────────────
        r"\bquien(?:es)? puede(?:n)? participar\b",
        r"\bpuedo (?:participar|inscribirme|unirme|registrarme|apuntarme)\b",
        r"\bpuede mi (?:hijo|hija|nino|nina)\b",
        r"\bsoy (?:demasiado|muy) (?:mayor|joven)\b",
        r"\bcomo (?:me inscribo|puedo inscribirme|me registro|solicito)\b",
        r"\bque necesito para (?:inscribirme|participar|solicitar)\b",
        r"\bcalifico\b",
        # ── French ───────────────────────────────────────────────────────────
        r"\bqui peut participer\b",
        # The apostrophe is optional in every one of these. A phone keyboard
        # drops it, autocorrect turns it typographic, and `_fold` normalises the
        # typographic form -- but nothing puts back one that was never typed.
        r"\bpuis-?je (?:participer|m'?inscrire|adherer|postuler)\b",
        r"\bmon (?:fils|enfant|fille) peut-?il\b",
        r"\bsuis-?je trop (?:age|jeune|vieux)\b",
        r"\bcomment (?:s'?inscrire|m'?inscrire|postuler|faire une demande)\b",
        r"\bque faut-?il pour s'?inscrire\b",
        r"\bsuis-?je eligible\b",
    )
)

#: "Let's play." Asking to play is the ONLY thing that starts a game -- v1's
#: tool description said so in as many words ("Never offer a game unprompted"),
#: and a deterministic matcher is how that becomes true rather than requested.
_PLAY: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:play|start|do) (?:a |the |another |an )?(?:game|quiz|puzzle)\b",
        r"\b(?:can|could|may) (?:i|we) play\b",
        r"\b(?:let'?s|lets|let us) play\b",
        r"\bi want to play\b",
        r"\bwhat games?\b",
        r"\bany games?\b",
        r"\b(?:word )?scramble\b",
        r"\btrue or false\b",
        r"\bjugar\b",
        r"\b(?:un|el) juego\b",
        r"\bjouer\b",
        r"\b(?:un|le) jeu\b",
    )
)

#: Which game a message names, if it names one. Absent means "they asked to
#: play but did not choose", and the node asks rather than picking -- same rule
#: v1's `start_game` description gave the model.
_NAMED_GAME: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:word )?scramble\b|\bunscramble\b|\bletras\b"), "scramble"),
    (
        re.compile(r"\btrue or false\b|\btrue/false\b|\bverdadero o falso\b|\bvrai ou faux\b"),
        "true_false",
    ),
    (re.compile(r"\bmillionaire\b|\bmillonario\b|\bmillionnaire\b"), "millionaire"),
)


def wants_eligibility(message: str) -> bool:
    """Whether this message is somebody working out if they can join."""
    folded = _fold(message)
    if not folded:
        return False
    if any(pattern.search(folded) for pattern in _LOOKUP):
        return False
    return any(pattern.search(folded) for pattern in _ELIGIBILITY)


def wants_game(message: str) -> bool:
    """Whether this message is asking to play."""
    folded = _fold(message)
    return bool(folded) and any(pattern.search(folded) for pattern in _PLAY)


def named_game(message: str) -> str | None:
    """Which game they named, or None if they just said "a game"."""
    folded = _fold(message)
    for pattern, name in _NAMED_GAME:
        if pattern.search(folded):
            return name
    return None
