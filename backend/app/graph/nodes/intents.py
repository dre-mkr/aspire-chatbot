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

#: "Tell me a story." Asked for outright, and only ever asked for.
#:
#: The client's rule is that the assistant must NEVER start telling stories on
#: its own, so this is the whole trigger: there is no planner move, no
#: turns-since counter and nothing in the tutor that can reach a story without
#: a reader typing one of these. Narrow on purpose -- "what is the story with
#: my application" is not a request for a bedtime story, which is why the verb
#: has to govern the noun rather than merely appear near it.
_STORY: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        # `watch` and `see` are here because a child asked "Can I watch a
        # story?" and got a hint from a saving lesson. Only the TELL verbs were
        # listed, so watching or seeing one was not a story request at all, in
        # any of the three languages -- it fell through to mastery placement and
        # was answered as a wrong quiz answer. `asks_for_a_video` already yields
        # to a story match, so "watch a story" lands here and "watch a video"
        # still does not.
        r"\b(?:tell|read|say|give|watch|see|show)(?: me| us)?"
        r"(?: a| another| one| the)? (?:short )?(?:story|tale)\b",
        r"\b(?:can|could|may)\s+(?:i|we)\s+(?:watch|see|hear|have)"
        r"(?: a| another| the)?\s+(?:short\s+)?(?:story|tale)\b",
        r"\bi want (?:a|another) story\b",
        r"\b(?:can|could) (?:you|we) (?:tell|hear|have)(?: me| us)?(?: a)? story\b",
        r"\bstory time\b",
        # Spanish covered "cuento" but not "historia", and required "un"
        # exactly -- so "cuentame una historia", the ordinary way to ask, was
        # not a story request at all. `fold` strips the accents before these
        # run, which is why they are written without them.
        r"\b(?:cuenta|cuentame|dime|narra|nos cuentas)\b[^.?!]{0,12}?"
        r"\b(?:cuento|historia)\b",
        r"\b(?:otro cuento|otra historia)\b",
        r"\b(?:ver|mirar|escuchar)\s+(?:un|una|otro|otra|el|la)?\s*"
        r"(?:cuento|historia)\b",
        r"\bpuedo\s+(?:ver|mirar|escuchar|o[ií]r)\b[^.?!]{0,12}?"
        r"\b(?:cuento|historia)\b",
        r"\bquiero (?:un cuento|una historia)\b",
        # Same for French: "raconte" was required, and "une autre histoire" --
        # what the follow-up chip says -- matched nothing.
        r"\b(?:raconte|racontez|dis)\b[^.?!]{0,14}?\bhistoire\b",
        r"\b(?:une autre histoire|encore une histoire)\b",
        r"\b(?:regarder|voir|[eé]couter)\s+(?:une|l\'|la|encore une)?\s*"
        r"histoire\b",
        r"\b(?:puis-je|je peux|je veux|on peut)\b[^.?!]{0,16}?\bhistoire\b",
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

#: "Do you have videos?" -- asking for one outright, with nothing on the table.
#:
#: A separate list from `_WATCH`, and the separation is deliberate. `_WATCH` is
#: narrow because it decides whether an offer already on screen is being
#: accepted, and a false positive there opens a player on top of whatever the
#: reader was actually agreeing to. This list decides whether somebody is ASKING,
#: which is a thing they only ever do on purpose, so it can afford to be generous.
#:
#: The noun is required and it is always a video noun. "Tell me a story" belongs
#: to `_STORY` and the story flow writes prose; only `video`, `film` and
#: `cartoon` reach the catalog. A reader who says "story" gets a story written
#: for them, which is what they asked for and what the flow was built to do.
_ASKS_FOR_VIDEO: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        # "do you have any videos", "are there videos", "is there a video"
        r"\b(?:do you have|got|are there|is there|have you got|any)\b[^.?!]{0,20}\b(?:video|videos|film|films|cartoon|cartoons)\b",
        # "i want to watch a video", "can i watch a video", "let me see a video"
        r"\b(?:want|like|can i|could i|let me|lemme|i'd like)\b[^.?!]{0,20}\b(?:video|film|cartoon)\b",
        # "show me the videos", "play a video", "watch a video"
        r"\b(?:watch|play|show|see|open|start)\b[^.?!]{0,20}\b(?:video|videos|film|films|cartoon|cartoons)\b",
        # "videos", "video please", "a video" -- the whole message, nothing else.
        r"^(?:a |the |some )?(?:video|videos|film|cartoon)(?:,? please)?[.!?]*$",
        # Spanish and French, same three shapes collapsed.
        r"\b(?:ver|mira|muestra|pon|quiero)\b[^.?!]{0,20}\b(?:video|videos)\b",
        r"^(?:un |el |los )?videos?(?:,? por favor)?[.!?]*$",
        r"\b(?:voir|montre|regarder|je veux)\b[^.?!]{0,20}\b(?:video|videos|film)\b",
        r"^(?:une |la |le |les )?videos?(?:,? s'il vous plait)?[.!?]*$",
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


#: The whole message is the word, and nothing else.
#:
#: How a five-year-old asks. "game", "story", "story?", "a game please". Only
#: as the ENTIRE message: "story" inside a sentence is usually a noun, as in
#: "what is the story of ASPIRE", and matching that would answer a question
#: with a fairy tale.
_JUST_A_GAME = re.compile(r"^\W*(?:a\s+)?(?:game|games|play)\W*(?:please)?\W*$", re.I)
_JUST_A_STORY = re.compile(r"^\W*(?:a\s+)?(?:story|storie?s|tale)\W*(?:please)?\W*$", re.I)

#: Hedged, and still a request. Children rarely demand.
_MAYBE_A_GAME = re.compile(
    r"\b(?:maybe|perhaps|could\s+we|can\s+we)\b[^.?!]{0,12}?\b(?:game|play)\b"
    r"|\bi\s+wanna\s+play\b|\bwanna\s+play\b",
    re.IGNORECASE,
)
_MAYBE_A_STORY = re.compile(
    r"\b(?:maybe|perhaps|could\s+we|can\s+we)\b[^.?!]{0,12}?\b(?:story|tale)\b"
    r"|\bwanna\s+(?:hear|read|see|watch)\b[^.?!]{0,12}?\b(?:story|tale)\b",
    re.IGNORECASE,
)


def wants_game(message: str) -> bool:
    """Whether this message is asking to play, rather than asking about playing.

    Naming a game IS asking to play it, including when the name is misspelled.
    Without that second clause the typo tolerance in `named_game` was
    unreachable: this gate runs FIRST, and `_open_game` -- which is where
    `named_game` is called -- is only reached when this returns True.

    Measured on production after the fix shipped: "word scamble" was still not
    a game request, so a nine-year-old got the Word Scramble answer key printed
    at them as prose instead of a game. The unit was right and the path was
    not, which is what comes of testing `named_game` on its own.
    """
    folded = fold(message)
    if not _is_a_command(folded):
        return False
    if any(pattern.search(folded) for pattern in _PLAY):
        return True
    if _JUST_A_GAME.match(folded) or _MAYBE_A_GAME.search(folded):
        return True
    return named_game(message) is not None


def wants_story(message: str) -> bool:
    """Whether this message ASKS for a story. Nothing else ever starts one."""
    folded = fold(message)
    if not _is_a_command(folded):
        return False
    if any(pattern.search(folded) for pattern in _STORY):
        return True
    return bool(_JUST_A_STORY.match(folded) or _MAYBE_A_STORY.search(folded))


def wants_video(message: str) -> bool:
    """Whether this message is accepting a video, rather than mentioning one."""
    folded = fold(message)
    if not _is_a_command(folded):
        return False
    return any(pattern.search(folded) for pattern in _WATCH)


def asks_for_a_video(message: str) -> bool:
    """Whether this message is ASKING for a video, rather than accepting one.

    The bug this exists for, in the reader's own words: "Do you have videos?",
    "I want to watch a video", "Video". Six requests in one conversation, one
    video played, and the one that worked contained the word "scarcity" -- the
    TOPIC. Nothing in the system was looking for the request itself.

    `wants_video` is not that check and was never meant to be. It answers "is
    this a yes to the offer on screen", which is a narrower question with a
    worse failure mode, and it is right to stay narrow.
    """
    folded = fold(message)
    if not _is_a_command(folded):
        return False
    # A story request is a story request. The story flow writes prose, which is
    # what "tell me a story" asks for; only a video noun reaches the catalog.
    if any(pattern.search(folded) for pattern in _STORY):
        return False
    return any(pattern.search(folded) for pattern in _ASKS_FOR_VIDEO)


#: One misspelling away from a game name, for readers who are seven.
#:
#: "Ah dat me a say word scamble" launched nothing. `_NAMED_GAME` is exact, so
#: one missing letter turned a game request into a general question, and the
#: reader got a paragraph ABOUT Word Scramble -- including an improvised
#: scrambled word in prose -- instead of the game. They had to retype it
#: correctly to play.
#:
#: The primary readers of this product are five to twelve years old and type
#: like it. A game name is also a safe place to be forgiving: the worst case is
#: launching a game somebody half-named, which the card lets them leave.
_FUZZY_GAME: dict[str, str] = {
    "scramble": "scramble",
    "unscramble": "scramble",
    "letras": "scramble",
    "millionaire": "millionaire",
    "millonario": "millionaire",
    "millionnaire": "millionaire",
    "hangman": "hangman",
    "ahorcado": "hangman",
}

#: Below this and a short word matches too much: "gamble" is not "scramble".
_FUZZY_CUTOFF = 0.82

#: The second half of "true or false", where the first half is already evidence.
_FUZZY_PAIRED_CUTOFF = 0.8

#: Shorter than this and the edit distance stops being evidence of anything.
_FUZZY_MIN_LENGTH = 5


def _fuzzy_game(folded: str) -> str | None:
    """A game name that survived one typo, or None."""
    from difflib import get_close_matches

    for token in re.findall(r"[a-z]+", folded):
        if len(token) < _FUZZY_MIN_LENGTH:
            continue
        if token in _FUZZY_GAME:
            return _FUZZY_GAME[token]
        near = get_close_matches(token, _FUZZY_GAME, n=1, cutoff=_FUZZY_CUTOFF)
        if near:
            return _FUZZY_GAME[near[0]]

    # "true or fasle" -- two words, so it needs both halves rather than one.
    #
    # A looser cutoff here than above, and safely so: "true" has already been
    # found, which is the anchor. "fasle" and "flase" -- the two ways this is
    # actually mistyped -- both score exactly 0.800 against "false".
    words = re.findall(r"[a-z]+", folded)
    if any(word in ("true", "verdadero", "vrai") for word in words):
        for token in words:
            if len(token) >= _FUZZY_MIN_LENGTH and get_close_matches(
                token, ("false", "falso", "faux"), n=1, cutoff=_FUZZY_PAIRED_CUTOFF
            ):
                return "true_false"
    return None


#: An age or a school stage a reader names for SOMEBODY ELSE.
#:
#: "Can I see the lesson my nine-year-old would get." Before this there was no
#: way to say which band you wanted to look at, so `band_of` read the reader
#: every time and a parent asking for a nine-year-old's lesson was shown a
#: fourteen-year-old's -- adult falls back through 16-18 to 13-15.
#:
#: The school stages are the St Kitts and Nevis ones, because that is what a
#: teacher says. A Form 2 teacher does not say "the 13-15 band".
_AGE_SAID = re.compile(
    r"\b(?:aged?\s+)?(\d{1,2})\s*(?:-|\s)?\s*year[- ]?old\b"
    r"|\bis\s+(\d{1,2})\b"
    r"|\baged\s+(\d{1,2})\b",
    re.IGNORECASE,
)

_STAGE_SAID: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\binfant\b|\bkindergarten\b|\bgrade\s*[12]\b", re.I), "5-8"),
    (re.compile(r"\bgrade\s*[3-6]\b|\b(?:lower|upper)\s+primary\b|\bprimary\b", re.I), "9-12"),
    (re.compile(r"\bform\s*[123]\b|\blower\s+secondary\b", re.I), "13-15"),
    (re.compile(r"\bform\s*[45]\b|\bupper\s+secondary\b|\bsixth\s+form\b", re.I), "16-18"),
)

#: Age to band. The same ladder `AGE_BANDS` uses, stated once.
_BAND_FOR_AGE: tuple[tuple[int, int, str], ...] = (
    (5, 8, "5-8"), (9, 12, "9-12"), (13, 15, "13-15"), (16, 18, "16-18"),
)


def band_requested(message: str) -> str | None:
    """The band this message asks to SEE, or None.

    A band named for somebody else -- a child, a class -- not a claim about the
    reader. Only `learning_preview` and `learning_sample` act on it, so it can
    never move the reader's own gates.
    """
    text = message or ""
    for pattern, band in _STAGE_SAID:
        if pattern.search(text):
            return band
    found = _AGE_SAID.search(text)
    if found:
        digits = next((g for g in found.groups() if g), None)
        if digits:
            age = int(digits)
            for low, high, band in _BAND_FOR_AGE:
                if low <= age <= high:
                    return band
    return None


def named_game(message: str) -> str | None:
    """Which game they named, or None if they just said "a game"."""
    folded = fold(message)
    for pattern, name in _NAMED_GAME:
        if pattern.search(folded):
            return name
    return _fuzzy_game(folded)
