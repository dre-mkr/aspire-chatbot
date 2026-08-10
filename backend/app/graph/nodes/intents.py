"""Recognising the two questions that are answered by a card, not by prose."""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def _fold(text: str) -> str:
    """Lowercase, strip accents, normalise apostrophes, collapse whitespace."""
    lowered = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    stripped = stripped.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", stripped).strip()


#: Checked FIRST.
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

#: "Can *I* join?" -- somebody working out their own position, not looking a rule up.
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
        # The apostrophe is optional in every one of these.
        r"\bpuis-?je (?:participer|m'?inscrire|adherer|postuler)\b",
        r"\bmon (?:fils|enfant|fille) peut-?il\b",
        r"\bsuis-?je trop (?:age|jeune|vieux)\b",
        r"\bcomment (?:s'?inscrire|m'?inscrire|postuler|faire une demande)\b",
        r"\bque faut-?il pour s'?inscrire\b",
        r"\bsuis-?je eligible\b",
    )
)

#: "Let's play." Asking to play is the ONLY thing that starts a game -- v1's tool description said so in as many…
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

#: Which game a message names, if it names one.
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
_ASKING_ABOUT = re.compile(
    r"^\s*(?:what|which|who|when|where|why|how much|how many|how old|is|are|does|do i qualify"
    r"|que|qui|quand|quel|quels|quelle|combien|cual|cuales|quien|cuando|cuanto)\b"
)


def wants_registration(message: str) -> bool:
    """Whether this message is somebody asking to APPLY, rather than asking about applying."""
    folded = _fold(message)
    if not folded:
        return False
    if _ASKING_ABOUT.match(folded):
        return False
    return any(pattern.search(folded) for pattern in _REGISTER)


#: Somebody asking to create a SIGN-IN ACCOUNT, which is not an application.
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
    """Whether this message asks to create a sign-in account."""
    folded = _fold(message)
    if not folded:
        return False
    if _ASKING_ABOUT.match(folded):
        # "What account do I need?" is a question about the programme, not a request to make one.
        return False
    return any(pattern.search(folded) for pattern in _ACCOUNT)


#: Somebody asking, in as many words, for a person.
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
    """Whether this message is a complaint rather than a question."""
    folded = _fold(message)
    return bool(folded) and any(pattern.search(folded) for pattern in _COMPLAINT)


def wants_human(message: str) -> bool:
    """Whether this message asks for a person."""
    folded = _fold(message)
    if not folded:
        return False
    return any(pattern.search(folded) for pattern in _WANTS_HUMAN)


#: Somebody asking to be TAUGHT rather than asking a fact.
_LESSON: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bteach me\b",
        r"\b(?:i|we) want to learn\b",
        r"\b(?:can|could|will) you teach\b",
        r"\bhelp me (?:learn|understand|practice|practise)\b",
        r"\b(?:start|begin|continue|resume) (?:a |the |my |our )?lesson\b",
        r"\b(?:give|show) me a lesson\b",
        r"\blearn about\b",
        r"\bnext lesson\b",
        r"\bensename\b|\bquiero aprender\b|\bleccion\b",
        r"\bapprends?-moi\b|\bje veux apprendre\b|\bune lecon\b",
    )
)


def wants_lesson(message: str) -> bool:
    """Whether this message asks to be taught, rather than asking a fact."""
    folded = _fold(message)
    if not folded:
        return False
    if _ASKING_ABOUT.match(folded):
        # "What will you teach me?" is a question about the product; lookups win ties.
        return False
    return any(pattern.search(folded) for pattern in _LESSON)


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
