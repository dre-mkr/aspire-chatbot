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


#: Somebody saying they want to APPLY, in the three shipped locales.
#:
#: An intent, not a question, and that distinction is the whole reason this
#: pattern exists. "Who registers a child?" is a question and the knowledge base
#: answers it well -- measured at 0.759 cosine. "I want to register my child" is
#: a request to DO something, and there is no fact to retrieve for it: the same
#: corpus tops out at 0.519 against a 0.550 grounding floor, so `qa_agent`
#: escalates and a parent gets a support ticket instead of an answer.
#:
#: Tuning the corpus to close that gap was tried and measured first. Rewording
#: the closest row lifted this phrasing to 0.539 -- still under the floor --
#: while pushing "i want to sign my child up" from 0.573 down to 0.550 and
#: "where do i start" from 0.425 to 0.386. A retrieval floor is not the right
#: instrument for recognising an intent.
_REGISTER = (
    re.compile(
        r"\b(?:i|we)\s+(?:want|would like|wish|need)\s+to\s+"
        r"(?:register|sign\s+up|enroll?|apply|join)\b"
    ),
    re.compile(r"\b(?:register|sign\s+up|enroll?|apply)\s+(?:my|our|a|the)\s+"
               r"(?:child|children|son|daughter|kid|kids)\b"),
    re.compile(r"\bhow\s+do\s+(?:i|we)\s+(?:register|sign\s+up|enroll?|apply)\b"),
    re.compile(r"\b(?:start|begin|open)\s+(?:an?\s+)?(?:application|account)\b"),
    re.compile(r"\b(?:quiero|queremos)\s+(?:registrar|inscribir)\b"),
    re.compile(r"\b(?:je\s+veux|nous\s+voulons)\s+(?:inscrire|enregistrer)\b"),
)


#: A question that happens to contain a registration verb.
#:
#: "What documents do I need to register?" matches "i need to register" and is
#: not an intent -- it is a lookup the corpus answers well and cites. Guarding
#: on the leading interrogative applies this module's existing precedence rule:
#: lookups win ties, because getting it wrong in the lookup direction costs an
#: accurate cited sentence and getting it wrong the other way replaces one with
#: a fixed paragraph.
_ASKING_ABOUT = re.compile(
    r"^\s*(?:what|which|who|when|where|why|how much|how many|how old|is|are|does|do i qualify"
    r"|que|qui|quand|quel|quels|quelle|combien|cual|cuales|quien|cuando|cuanto)\b"
)


def wants_registration(message: str) -> bool:
    """Whether this message is somebody asking to APPLY, rather than asking about
    applying.

    Consulted only when the caller cannot reach a registration agent -- see
    `cards.make_intent_gate`. A guardian saying this is routed to
    `register_agent` as before and never reaches this matcher.
    """
    folded = _fold(message)
    if not folded:
        return False
    if _ASKING_ABOUT.match(folded):
        return False
    return any(pattern.search(folded) for pattern in _REGISTER)


#: Somebody asking to create a SIGN-IN ACCOUNT, which is not an application.
#:
#: The two are a step apart and the product never had a way to say so. An
#: application enrols a child; an account is how a person signs in, and applying
#: through this assistant needs one first -- on a guardian's own account, which
#: is exactly what the reader who triggers `cards._registration_help` has not
#: got. Telling them "a guardian completes this" and leaving them to find the
#: sign-up page was the gap.
#:
#: ## Kept out of `_REGISTER`'s way on purpose
#:
#: `_REGISTER` already matches `(start|begin|open) (an? )?(application|account)`,
#: because "open an account" in a programme about savings accounts is an
#: application. So this list does NOT use `open` or `start`: it takes the verbs
#: that can only mean the sign-in credential -- create, make, set up -- and
#: leaves the ambiguous ones where they were. Two matchers competing for "open
#: an account" would be decided by whichever the gate happened to call first,
#: which is not a decision to leave to statement order.
_ACCOUNT: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:create|make|set\s+up|register\s+for)\s+(?:an?\s+|my\s+|the\s+)?"
        r"(?:new\s+)?(?:guardian|parent|carer|teacher|educator|aspire|free)?\s*account\b",
        r"\b(?:sign(?:ing)?\s+up)\s+for\s+(?:an?\s+)?account\b",
        r"\b(?:i|we)\s+(?:want|need|would\s+like)\s+(?:an?\s+)?"
        r"(?:guardian|parent|teacher|aspire)?\s*account\b",
        r"\bcrear\s+(?:una\s+|mi\s+)?cuenta\b",
        r"\bcreer\s+(?:un\s+|mon\s+)?compte\b",
    )
)


def wants_account(message: str) -> bool:
    """Whether this message asks to create a sign-in account.

    Narrow, and narrower than `wants_registration` deliberately. A false
    positive opens a sign-up wizard over a conversation somebody was in the
    middle of, which is a worse interruption than the six-step eligibility card
    -- it navigates away from the chat.
    """
    folded = _fold(message)
    if not folded:
        return False
    if _ASKING_ABOUT.match(folded):
        # "What account do I need?" is a question about the programme, not a
        # request to make one. Same precedence rule the rest of this module
        # applies: lookups win ties.
        return False
    return any(pattern.search(folded) for pattern in _ACCOUNT)


#: Somebody asking, in as many words, for a person.
#:
#: Matched deterministically for the same reason eligibility and games are, and
#: with more at stake. The router used to catch this by having `escalate_agent`
#: in its menu described as "they asked for one, they are upset or in
#: difficulty, or the question is outside what this assistant can answer" -- one
#: line covering three situations, the third of which is a catch-all. Track E.2
#: removes that menu entry; this replaces the half of it that was real.
#:
#: A regex has no opinion about being asked nicely, which matters here: a child
#: who has asked for a person should not have to phrase it in a way that
#: persuades a model.
#: A person, named in any of the ways people actually name one.
#:
#: The first draft of this list covered three of the seven labelled escalation
#: requests in `evals/routing.jsonl` and missed four -- "put me through to a
#: member of staff", "i need someone to call me", "i need to escalate this case
#: to your team", "i want a manager". The router used to catch all of them,
#: loosely, by having a catch-all in its menu; removing that menu entry without
#: widening this would have been a straight regression, and the labelled set is
#: what caught it.
_PERSON = r"(?:person|human|adult|adviser|advisor|agent|staff|manager|supervisor|someone|somebody)"

_WANTS_HUMAN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        rf"\b(?:speak|talk|chat)\s+(?:to|with)\s+(?:a|an|the|your|a\s+real)?\s*"
        rf"(?:member\s+of\s+)?{_PERSON}\b",
        rf"\b(?:put|patch|transfer)\s+me\s+(?:through|over)?\s*(?:to)?\s+(?:a|an|the)?\s*"
        rf"(?:member\s+of\s+)?{_PERSON}\b",
        rf"\b(?:get|give|find)\s+me\s+(?:a|an|the)?\s*(?:member\s+of\s+)?{_PERSON}\b",
        rf"\b(?:i\s+)?(?:want|need)\s+(?:a|an|the)?\s*(?:member\s+of\s+)?{_PERSON}\b",
        rf"\b(?:real|actual|live)\s+{_PERSON}\b",
        rf"\b{_PERSON}\s+to\s+(?:call|ring|phone|contact)\s+me\b",
        r"\b(?:call|ring|phone)\s+me\s+back\b",
        r"\bhuman\s+(?:please|help|support|agent)\b",
        r"\bcustomer\s+(?:service|support)\b",
        r"\bescalate\s+(?:this|it|my|the)\b",
        r"\b(?:hablar|habla)\s+con\s+(?:una\s+)?persona\b",
        r"\bparler\s+(?:a|au|avec)\s+(?:une\s+)?(?:personne|humain|conseiller)\b",
    )
)

#: A complaint, which is its own `EscalationReason` and had no detector at all.
#:
#: `COMPLAINT` exists in the contract because a complaint answered by an FAQ is a
#: worse complaint. Nothing produced it until this list: the router used to reach
#: escalation for "this has been wrong for three weeks and i want a manager" by
#: guessing, and after E.2 that turn had nowhere to go.
#:
#: Narrow on purpose. "This is wrong" about a fact is a correction, not a
#: complaint, and belongs with the knowledge base.
_COMPLAINT: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:make|file|lodge|raise)\s+(?:a\s+)?complaint\b",
        r"\bi\s+(?:want|wish)\s+to\s+complain\b",
        r"\b(?:want|need|speak\s+to)\s+(?:a|the|your)\s+(?:manager|supervisor)\b",
        r"\b(?:this|it)\s+(?:has\s+been|is)\s+(?:wrong|broken|unacceptable)\b",
        r"\b(?:nobody|no\s+one)\s+(?:is\s+)?(?:answering|replying|responding)\b",
        r"\bunacceptable\b",
        r"\b(?:quiero|deseo)\s+(?:hacer\s+una\s+)?queja\b",
        r"\b(?:faire|deposer)\s+une\s+reclamation\b",
    )
)


def is_complaint(message: str) -> bool:
    """Whether this message is a complaint rather than a question.

    Checked BEFORE `wants_human`, because the two overlap constantly -- "this has
    been wrong for three weeks and i want a manager" is both -- and they triage
    differently: `COMPLAINT` is high priority in a complaint queue,
    `USER_REQUESTED_HUMAN` is normal priority in the general one. Letting the
    request win would quietly downgrade every complaint that happens to name a
    person, which is most of them.
    """
    folded = _fold(message)
    return bool(folded) and any(pattern.search(folded) for pattern in _COMPLAINT)


def wants_human(message: str) -> bool:
    """Whether this message asks for a person.

    Deliberately narrow. A false positive hands somebody to a support queue they
    did not ask for, which is the failure this whole track is reducing -- so
    "can a person do this?" and "who should I speak to about X?" are questions
    about the programme and are left to the knowledge base.
    """
    folded = _fold(message)
    if not folded:
        return False
    return any(pattern.search(folded) for pattern in _WANTS_HUMAN)


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
