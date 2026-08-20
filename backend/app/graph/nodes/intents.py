"""Recognising the two questions that are answered by a card, not by prose."""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def fold(text: str) -> str:
    """Lowercase, strip accents, normalise apostrophes, collapse whitespace.

    Runs of three or more identical letters collapse too, so "siiign me up"
    matches the same pattern "sign me up" does. No English, Spanish or French
    word carries a triple letter, so nothing real is damaged by it.
    """
    from app.casual import squeeze_runs

    lowered = unicodedata.normalize("NFKD", squeeze_runs(text).lower())
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

#: Questions ABOUT the rules and the process. These get a cited answer.
#:
#: They lived in `_ELIGIBILITY` and opened the wizard, which is a form carrying
#: no prose at all -- so someone who asked a question was handed a form and
#: never answered. The two tests either side of this file already name the
#: intended line: `personal_eligibility_questions_open_the_card` against
#: `lookups_stay_prose`, "a question about ONE rule gets a cited answer, not a
#: form". These twelve were simply on the wrong side of it.
#:
#: The corpus agreed all along. `evals/golden.yaml` en-02 ("Who is eligible to
#: join ASPIRE?" -> ASP-026) and en-03 ("How do I apply for ASPIRE?" -> ASP-045)
#: both expect an answer, and the latency probe measured five of thirty golden
#: questions producing no visible token at all -- en-02, en-03, es-02, es-03,
#: fr-03 -- because the card claimed them.
_ELIGIBILITY_LOOKUP: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        # ── English ──────────────────────────────────────────────────────────
        r"\bwho (?:is|are) eligible\b",
        r"\bwho can (?:join|apply|sign up|register|participate)\b",
        r"\bhow (?:can|do) (?:i|we) (?:apply|join|sign up|register|enrol|enroll)\b",
        r"\bhow (?:to|do you) (?:apply|join|sign up|register)\b",
        r"\bwhat do (?:i|we) need to (?:apply|join|sign up|register)\b",
        r"\bwhat (?:documents|papers|paperwork) do (?:i|we) need\b",
        # ── Spanish ──────────────────────────────────────────────────────────
        r"\bquien(?:es)? puede(?:n)? participar\b",
        r"\bcomo (?:me inscribo|puedo inscribirme|me registro|solicito)\b",
        r"\bque necesito para (?:inscribirme|participar|solicitar)\b",
        # ── French ───────────────────────────────────────────────────────────
        r"\bqui peut participer\b",
        r"\bcomment (?:s'?inscrire|m'?inscrire|postuler|faire une demande)\b",
        r"\bque faut-?il pour s'?inscrire\b",
    )
)

#: "Can *I* join?" -- somebody working out their own position, not looking a rule
#: up. Only these open the card, because only these are a question the card can
#: actually answer: it asks about one person and returns a verdict on them.
_ELIGIBILITY: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        # ── English ──────────────────────────────────────────────────────────
        r"\bam i (?:eligible|able to join|too old|too young|old enough)\b",
        r"\b(?:can|could|may) (?:i|we|my (?:son|daughter|child|kid|children|kids|boy|girl))\b"
        r".{0,24}\b(?:join|apply|sign up|register|enrol|enroll|participate|take part|get an account)\b",
        r"\bdo(?:es)? (?:i|we|my (?:son|daughter|child|kid)) (?:qualify|meet)\b",
        r"\bam i (?:the )?right age\b",
        r"\b(?:eligibility|elegibility) check\b",
        # ── Spanish ──────────────────────────────────────────────────────────
        r"\bpuedo (?:participar|inscribirme|unirme|registrarme|apuntarme)\b",
        r"\bpuede mi (?:hijo|hija|nino|nina)\b",
        r"\bsoy (?:demasiado|muy) (?:mayor|joven)\b",
        r"\bcalifico\b",
        # ── French ───────────────────────────────────────────────────────────
        # The apostrophe is optional in every one of these.
        r"\bpuis-?je (?:participer|m'?inscrire|adherer|postuler)\b",
        r"\bmon (?:fils|enfant|fille) peut-?il\b",
        r"\bsuis-?je trop (?:age|jeune|vieux)\b",
        r"\bsuis-?je eligible\b",
    )
)

#: "Let's play." Asking to play is the only thing that starts a game.
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
        r"\bhangman\b",
        r"\bmillionaire\b",
        r"\bjugar\b",
        r"\b(?:un|el) juego\b",
        r"\bjouer\b",
        r"\b(?:un|le) jeu\b",
    )
)

#: "Yes, show me the video." Accepting an offer, or asking for one outright.
#:
#: Deliberately narrow. A bare "yes" is NOT here: it is the commonest word in
#: the language and the offer is one line in an answer that may have said
#: several things, so treating every "yes" as an acceptance would open a player
#: on top of whatever the reader was actually agreeing to. The chip sends its
#: own unambiguous text, and a reader typing it by hand says something like it.
_WATCH: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:watch|play|show|see) (?:me |us )?(?:the |that |this |a |an )?(?:aspire )?(?:video|story|film|cartoon)\b",
        r"\b(?:yes|yeah|sure|ok|okay)[, ]+(?:please )?(?:watch|show|play)\b",
        r"\bvideo,? (?:please|yes)\b",
        r"\b(?:ver|mira|muestra|pon) (?:el |un )?(?:video|cuento)\b",
        r"\b(?:voir|montre|regarder) (?:la |une |le )?(?:video|histoire)\b",
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
    (
        re.compile(
            r"\bhangman\b|\bahorcado\b|\ble pendu\b|\bpendu\b"
        ),
        "hangman",
    ),
)


#: The longest a message can be and still be a command rather than a question.
#:
#: A card answers before the model reads the message, which is right for "sign
#: me up" and wrong for anything with a sentence's worth of context in it. The
#: measured failure was "Can my daughter play a game about who is eligible?" --
#: ten words, captured by the eligibility card because it contains "eligible",
#: and so answered with a form instead of an answer.
#:
#: Eight rather than six: "i want to play the word scramble game" is eight words
#: and is unambiguously a command. The one-word cases the tests pin -- "scramble",
#: "jugar", "jouer" -- are unaffected; this is a ceiling, not a floor.
_COMMAND_MAX_WORDS = 8


def _is_a_command(folded: str) -> bool:
    """Short enough to be a command rather than a question with context in it.

    Length only. A question-word test belongs to the individual matcher and not
    here: `_ASKING_ABOUT` lists "do i qualify", which is the eligibility card's
    whole purpose, and it matches "what games are there", which is how a reader
    asks to see the games. Both are cards, correctly, and a shared question-word
    guard would suppress the two things these cards exist for.
    """
    if not folded:
        return False
    return len(folded.split()) <= _COMMAND_MAX_WORDS


def wants_eligibility(message: str) -> bool:
    """Whether this message is somebody working out if they can join."""
    folded = fold(message)
    if not folded:
        return False
    if any(pattern.search(folded) for pattern in _LOOKUP):
        return False
    # A question about the rules or the process is answered, not formed at.
    if any(pattern.search(folded) for pattern in _ELIGIBILITY_LOOKUP):
        return False
    if not _is_a_command(folded):
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
    folded = fold(message)
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
    folded = fold(message)
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

#: A complaint, which is its own `EscalationReason`.
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
    folded = fold(message)
    return bool(folded) and any(pattern.search(folded) for pattern in _COMPLAINT)


def wants_human(message: str) -> bool:
    """Whether this message asks for a person."""
    folded = fold(message)
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
    folded = fold(message)
    if not folded:
        return False
    if _ASKING_ABOUT.match(folded):
        # "What will you teach me?" is a question about the product; lookups win ties.
        return False
    return any(pattern.search(folded) for pattern in _LESSON)


def wants_game(message: str) -> bool:
    """Whether this message is asking to play, rather than asking about playing."""
    folded = fold(message)
    if not _is_a_command(folded):
        return False
    return any(pattern.search(folded) for pattern in _PLAY)


def wants_video(message: str) -> bool:
    """Whether this message is accepting a video, rather than mentioning one."""
    folded = fold(message)
    if not _is_a_command(folded):
        return False
    return any(pattern.search(folded) for pattern in _WATCH)


def named_game(message: str) -> str | None:
    """Which game they named, or None if they just said "a game"."""
    folded = fold(message)
    for pattern, name in _NAMED_GAME:
        if pattern.search(folded):
            return name
    return None
