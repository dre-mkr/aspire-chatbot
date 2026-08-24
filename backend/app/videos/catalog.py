"""The ASPIRE story videos, and which question each one answers.

Two things live here and nowhere else: what the videos ARE, and when one is
worth offering. Both are server-owned on purpose.

The catalog is server-owned because the offer is a claim about content. A model
that could name its own video could name one that does not exist, or hand a
child a URL; the id it may emit is checked against this file before anything
reaches a reader, and the file is the only place a path is written.

Topic matching is deterministic -- a keyword table, not a model call. It runs on
every turn that could carry an offer, and a demo cannot afford a second model
call on the one thing that is meant to feel effortless. It is also the only way
to be sure a video is offered for scarcity and not for "scarce parking", which
is what a similarity score does on a short question.

Nothing here plays anything. The catalog answers "is one of these relevant?";
the reader answers "do you want it?", and only then does a player appear.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from app.domain import Language, Persona


@dataclass(frozen=True, kw_only=True)
class Video:
    """One ASPIRE story video."""

    id: str
    """Opaque and stable. Travels on the wire; never a path."""

    title: str
    description: str

    #: What a reader would call the subject. Shown as a chip in the library.
    topic: str

    #: Runtime, for the library card. Not enforced against the file.
    duration_seconds: int

    #: Where the story is set. Every one of these is Saint Kitts and Nevis, and
    #: saying so is half of why the client asked for them.
    setting: str

    #: The file under `frontend/public/videos/`, tracked with git-lfs.
    #: Joined to `PUBLIC_DIR` by the client; never sent as a full URL.
    filename: str

    #: Who may be offered this. Same idea as a game's `persona_bands`, and the
    #: same reason: an adult asking about eligibility is not the audience for an
    #: animated children's story, and offering one reads as not listening.
    personas: tuple[Persona, ...]

    #: Terms that settle it on their own. Domain words a reader does not reach
    #: for by accident: "scarcity" is never small talk.
    strong: tuple[str, ...]

    #: Terms that mean this video only in company. Every one of these is an
    #: ordinary English word first -- `save` a document, `want` a coffee,
    #: `share` a photo -- so one alone is not evidence and two are.
    supporting: tuple[str, ...]

    #: The line offered after an answer. Kept as a question, always declinable.
    offer: str

    #: The locales this video has a caption track for, BESIDES English.
    #:
    #: Declaring one is not the same as having one. `has_subtitle` checks the
    #: file is actually on disk before anything is offered, so a track that is
    #: commissioned but not delivered keeps the offer closed rather than sending
    #: a French reader to an English soundtrack with no captions.
    subtitles: tuple[Language, ...] = ()

    #: The subject, per locale, for the chip. English falls back to `topic`.
    topics: tuple[tuple[Language, str], ...] = ()

    #: Curriculum concept ids this video teaches ("save", "need", ...).
    #: THE FUTURE-PROOFING: the teach flow recommends by concept, so a video
    #: added later with the right tag is offered with no other change anywhere.
    concepts: tuple[str, ...] = ()

    #: The offer line per locale. English falls back to `offer`.
    #:
    #: Translating the offer is not optional decoration: the offer IS the chip
    #: the reader taps, and a French reader tapping an English sentence has been
    #: told, in the one place it matters, that this feature was not built for
    #: them.
    offers: tuple[tuple[Language, str], ...] = ()


#: Where the client looks for the files. One place, so a move is one line.
PUBLIC_DIR: Final[str] = "/videos"


#: The catalog. Two entries today; the shape assumes more.
#:
#: `personas` excludes `aurora` and `nova` for both, matching the games rule in
#: `games/models.py`: these are children's stories, and a guardian or a teacher
#: asking a practical question should get a practical answer. Both can still
#: reach every video from the Videos panel, which is browsing rather than being
#: offered something unasked.
_VIDEOS: Final[tuple[Video, ...]] = (
    Video(
        id="captain-careful-scarcity",
        title="The Adventures of Captain Careful and the Quest for Scarcity",
        description=(
            "A thunderstorm leaves Basseterre short of supplies, and Captain "
            "Careful helps the community decide what matters most: sharing what "
            "there is, saving water, and telling a need apart from a want."
        ),
        topic="Scarcity",
        duration_seconds=262,
        setting="Basseterre, St. Kitts",
        filename="captain-careful-and-the-quest-for-scarcity.mp4",
        personas=(Persona.STELLA, Persona.KALEB, Persona.ORION, Persona.GUEST),
        strong=(
            "scarcity",
            "scarce",
            "shortage",
            "ration",
            "rationing",
            "conserve",
            "conserving",
            "conservation",
            "prioritise",
            "prioritize",
            "prioritising",
            "prioritizing",
        ),
        supporting=(
            "need",
            "needs",
            "want",
            "wants",
            "limited",
            "resource",
            "resources",
            "share",
            "sharing",
            "enough",
            "priority",
            "priorities",
            "essential",
            "shortages",
        ),
        offer="Would you like to watch a short ASPIRE video about scarcity?",
        subtitles=(Language.ES, Language.FR),
        offers=(
            (Language.ES, "¿Quieres ver un vídeo corto de ASPIRE sobre la escasez?"),
            (Language.FR, "Veux-tu regarder une courte vidéo ASPIRE sur la rareté ?"),
        ),
        topics=((Language.ES, "la escasez"), (Language.FR, "la rareté")),
        concepts=("need", "spend"),
    ),
    Video(
        id="monique-saving-adventure",
        title="Monique's Saving Adventure",
        description=(
            "Monique lives on Nevis and wants the Wand of Wisdom, which costs "
            "100 magic dollars. She learns that earning takes work, that time is "
            "worth something too, and that waiting for the thing you actually "
            "want beats spending on the thing you don't."
        ),
        topic="Saving and goals",
        duration_seconds=355,
        setting="Nevis",
        filename="moniques-saving-adventure.mp4",
        personas=(Persona.STELLA, Persona.KALEB, Persona.ORION, Persona.GUEST),
        strong=(
            "saving",
            "savings",
            "allowance",
            "budgeting",
            "patience",
        ),
        supporting=(
            "save",
            "saves",
            "saved",
            "goal",
            "goals",
            "target",
            "earn",
            "earning",
            "earned",
            "patient",
            "wait",
            "waiting",
            "chores",
            "pocket",
            "spend",
            "spending",
            "afford",
            "budget",
            "money",
        ),
        offer="Would you like to watch an ASPIRE story about setting a savings goal?",
        subtitles=(Language.ES, Language.FR),
        offers=(
            (Language.ES,
             "¿Quieres ver una historia de ASPIRE sobre ahorrar para una meta?"),
            (Language.FR,
             "Veux-tu regarder une histoire ASPIRE sur l'épargne pour un objectif ?"),
        ),
        topics=((Language.ES, "el ahorro"), (Language.FR, "l'épargne")),
        concepts=("save", "goal", "habit"),
    ),
)

_BY_ID: Final[dict[str, Video]] = {video.id: video for video in _VIDEOS}


#: Where a caption track sits, next to the film it belongs to.
SUBTITLE_DIR: Final[str] = PUBLIC_DIR

#: Resolved from this file, so a checkout with no LFS pull still answers
#: honestly: no track on disk, no offer.
_ASSET_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[3] / "frontend" / "public" / "videos"
)


def subtitle_filename(video: Video, language: Language) -> str:
    """`moniques-saving-adventure.fr.vtt`. One convention, derived, never typed."""
    return f"{video.filename.rsplit('.', 1)[0]}.{language.value}.vtt"


@lru_cache(maxsize=64)
def _track_on_disk(name: str) -> bool:
    return (_ASSET_ROOT / name).is_file()


def has_subtitle(video: Video, language: Language) -> bool:
    """Whether this video can honestly be offered to a reader in this locale.

    English is the soundtrack, so it needs no track. Every other locale needs a
    file that EXISTS -- declaring it in the catalog is a commission, not a
    delivery, and the difference is a child being handed five minutes of a
    language they do not read.
    """
    if language is Language.EN:
        return True
    if language not in video.subtitles:
        return False
    return _track_on_disk(subtitle_filename(video, language))


#: The chip, per locale. A COMMAND, because the chip's text is also what gets
#: sent when it is tapped -- and `intents.wants_video` has to recognise it or the
#: tap opens nothing. Each of these starts with a verb that `_WATCH` already
#: matches in that language; `test_the_chip_it_sends_is_a_chip_it_accepts` is
#: what stops a future edit breaking that quietly.
_CHIP: Final[dict[Language, str]] = {
    Language.EN: "Watch the ASPIRE video about {topic}",
    Language.ES: "Ver el vídeo de ASPIRE sobre {topic}",
    Language.FR: "Voir la vidéo ASPIRE sur {topic}",
}


def chip_for(video: Video, language: Language) -> str:
    """The quick-reply chip offering this video, in the reader's language."""
    topic = video.topic.lower()
    for locale, localised in video.topics:
        if locale is language:
            topic = localised
            break
    return _CHIP.get(language, _CHIP[Language.EN]).format(topic=topic)


def offer_line(video: Video, language: Language) -> str:
    """The offer chip, in the reader's language, falling back to English."""
    for locale, line in video.offers:
        if locale is language:
            return line
    return video.offer

#: Letters only, so "EC$100" carries no words and a figure is never a keyword.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _fold(text: str) -> str:
    """Lowercased and stripped of accents, so `ahorré` and `ahorre` are one word."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


@lru_cache(maxsize=1)
def _term_index() -> dict[str, tuple[tuple[str, bool], ...]]:
    """`folded term -> (video id, is_strong)`, built once at import.

    A term claimed by more than one video keeps a row per video; the caller
    scores them all and then insists on a clear winner.
    """
    index: dict[str, list[tuple[str, bool]]] = {}
    for video in _VIDEOS:
        for term in video.strong:
            index.setdefault(_fold(term), []).append((video.id, True))
        for term in video.supporting:
            index.setdefault(_fold(term), []).append((video.id, False))
    return {word: tuple(rows) for word, rows in index.items()}


def all_videos() -> tuple[Video, ...]:
    """Every video, in catalog order. The library shows all of them."""
    return _VIDEOS


def by_id(video_id: str) -> Video | None:
    """One video, or None. Never raises: an unknown id means 'do not offer'."""
    return _BY_ID.get((video_id or "").strip())


def for_persona(persona: Persona | None) -> tuple[Video, ...]:
    """The videos this reader may be OFFERED. Browsing is not filtered."""
    if persona is None:
        return _VIDEOS
    return tuple(video for video in _VIDEOS if persona in video.personas)


def relevant_to(
    text: str,
    *,
    persona: Persona | None = None,
    language: Language = Language.EN,
) -> Video | None:
    """The one video worth offering for this message, or None.

    None is the common and correct answer, and the bar is deliberately high in
    both directions:

    * At least two distinct keyword hits. One is how "I want to save this chat"
      becomes a story about pocket money -- `save` is an ordinary English verb
      long before it is a financial one.
    * A clear winner. A message that matches both videos equally is a message
      about money in general, and picking one of them is guessing.

    Language narrows by CAPTION TRACK, not by locale. Both soundtracks are
    English, so a reader in Spanish or French is offered a film only when a
    caption track for them is on disk -- `has_subtitle`, which checks the file
    rather than the catalog's intention.

    This line used to read `if language is not Language.EN: return None`, and it
    was the right call while nothing was captioned. Its cost was that the videos
    did not degrade for a non-English reader, they DISAPPEARED: no offer, no
    explanation, nothing to notice. Tie it to the asset and it opens by itself
    the day the asset lands.
    """
    allowed = {
        video.id
        for video in for_persona(persona)
        if has_subtitle(video, language)
    }
    if not allowed:
        return None

    index = _term_index()
    strong: dict[str, set[str]] = {}
    supporting: dict[str, set[str]] = {}
    for word in _WORD.findall(_fold(text or "")):
        for video_id, is_strong in index.get(word, ()):
            if video_id not in allowed:
                continue
            bucket = strong if is_strong else supporting
            bucket.setdefault(video_id, set()).add(word)

    def score(video_id: str) -> int:
        """A strong term is worth the two supporting ones it replaces."""
        return 2 * len(strong.get(video_id, ())) + len(supporting.get(video_id, ()))

    candidates = set(strong) | set(supporting)
    if not candidates:
        return None
    ranked = sorted(candidates, key=score, reverse=True)
    winner = ranked[0]
    # Two supporting words, or one strong one. "What does scarcity mean?" is a
    # single word and settles it; "can you save this for me" is a single
    # ordinary verb and settles nothing.
    if score(winner) < 2:
        return None
    # A message that matches both equally is a message about money in general,
    # and choosing one of them is guessing.
    if len(ranked) > 1 and score(winner) == score(ranked[1]):
        return None
    return _BY_ID[winner]


#: The words a person uses to ASK, stripped before the topic is read.
#:
#: Found by a test, and it is the trap this whole function walks into otherwise:
#: "I want to watch a video" contains `want`, which is a supporting term for the
#: scarcity film, so a reader who named no subject at all was handed a story
#: about needs and wants -- matched on the grammar of their request rather than
#: on anything they said. Every phrase here is scaffolding, never subject.
#:
#: `want` is removed only in `want to`, because "the needs and wants video" is a
#: reader naming the topic and the same four letters have to survive that.
_REQUEST_NOISE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:"
    r"i|we|you|me|us|the|a|an|some|please|do|does|got|have|has|any|"
    r"is|are|there|can|could|may|would|"
    r"wants? to|d? ?like to|"
    r"watch|watching|play|playing|show|see|view|open|start|"
    r"videos?|films?|cartoons?|"
    r"ver|mira|muestra|pon|quiero|voir|montre|regarder|veux"
    r")\b"
)


def requested(
    text: str,
    *,
    language: Language = Language.EN,
) -> tuple[Video, ...]:
    """The videos an EXPLICIT request is asking for. Possibly none, possibly all.

    A different question from `relevant_to`, with a deliberately different bar,
    and the distinction is the whole of this fix.

    `relevant_to` decides whether to VOLUNTEER a video after answering something
    else. Its bar is high in both directions because the cost of being wrong is
    an assistant that interrupts: two keyword hits, and a clear winner, or
    nothing.

    This function runs only once the reader has said, in words, that they want a
    video. The cost of being wrong has inverted. Refusing to name one because
    they typed a single keyword is the failure now, and a tie is not a reason to
    give them nothing -- it is a reason to show them both and let them pick.

    So: one hit is enough, ties are kept rather than discarded, and the caller
    decides what to do with a list of zero, one or many.

    **Not filtered by persona.** `for_persona` gates what a reader may be
    OFFERED, on the correct reasoning that a guardian asking about eligibility
    is not the audience for an animated story. Somebody who has typed "show me
    a video" is not being offered anything -- they are browsing, and browsing
    has never been filtered. The teacher asking for the Captain Careful film is
    the client's own best demo of this product, and the offer filter would have
    refused it.
    """
    # Gate on the CAPTION TRACK, not on the locale. Every other video path was
    # moved onto `has_subtitle` when the multilingual work landed; this one kept
    # the older `language is not Language.EN` test, which is the same answer
    # today and the wrong one the morning the .vtt files arrive -- offers would
    # start working in Spanish and French while an outright request went on
    # returning nothing.
    playable = tuple(v for v in _VIDEOS if has_subtitle(v, language))
    if not playable:
        return ()

    index = _term_index()
    subject = _REQUEST_NOISE.sub(" ", _fold(text or ""))
    playable_ids = {video.id for video in playable}
    hits: dict[str, int] = {}
    for word in _WORD.findall(subject):
        for video_id, is_strong in index.get(word, ()):
            if video_id not in playable_ids:
                continue  # named, but there is no track to watch it with
            hits[video_id] = hits.get(video_id, 0) + (2 if is_strong else 1)

    if not hits:
        return ()
    best = max(hits.values())
    # Everything at the top score. One winner plays; a tie is offered as a
    # choice, which is a better answer than the silence a tie produces above.
    return tuple(video for video in playable if hits.get(video.id, 0) == best)


def for_concept(concept: str, persona: str) -> Video | None:
    """The first video that teaches this concept and admits this persona.

    Concept-keyed on purpose: a lesson never names a video id, so a video
    added to this catalog tomorrow with the right `concepts` tag starts being
    recommended everywhere that concept is taught, with no other change.
    """
    for video in all_videos():
        if concept in video.concepts and persona in {p.value for p in video.personas}:
            return video
    return None
