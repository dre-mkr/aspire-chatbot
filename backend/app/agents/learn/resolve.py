"""What is this turn about?"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

from app.learning.concepts import ConceptStore, TeachingConcept, get_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConceptResolution:
    """What this turn is about, and how confidently we know."""

    concept: TeachingConcept | None = None
    source: str = "none"
    similarity: float = 0.0
    #: Populated on the RAG-teach path: the rows the lesson must be built from.
    kb_rows: tuple[Any, ...] = ()
    #: The runners-up, for a "did you mean" offer on the decline path.
    alternatives: tuple[TeachingConcept, ...] = ()

    @property
    def concept_id(self) -> str | None:
        return self.concept.id if self.concept else None

    @property
    def teaches(self) -> bool:
        """Whether this turn has anything to teach from at all."""
        return self.concept is not None or bool(self.kb_rows)


# ── continuation ─────────────────────────────────────────────────────────────

#: Bare acknowledgements and requests to carry on.
_CONTINUATION_WORDS = frozenset(
    {
        "yes", "yeah", "yep", "yh", "ok", "okay", "sure", "no", "nope", "nah",
        "more", "again", "next", "continue", "go on", "keep going", "carry on",
        "why", "why?", "how", "how?", "what", "huh", "eh", "i think so",
        "i dont know", "i don't know", "dunno", "idk", "not sure", "maybe",
        "got it", "i see", "cool", "thanks", "ta", "tell me", "show me",
        # The three shipped locales.
        "sí", "si", "vale", "claro", "más", "mas", "otra vez", "no sé", "no se",
        "oui", "ouais", "d'accord", "encore", "plus", "je ne sais pas",
    }
)

#: A message that is asking about a NEW thing rather than replying about this one.
_NEW_ENQUIRY = re.compile(
    r"""^\s*(?:
        (?:what|whats|what's|who|which|when|where|why|how)\b[^?]*\b\w{4,}
      | (?:tell|teach|explain|show)\s+me\s+(?:about\s+)?\w{4,}
      | (?:can|could)\s+(?:you|we)\s+(?:tell|teach|explain|show)\b
      | (?:i\s+want\s+to|i'?d\s+like\s+to)\s+(?:learn|know)\b
    )""",
    re.VERBOSE | re.IGNORECASE,
)

#: A request to work on the CURRENT concept -- practice, another question, an
#: example. It names no topic, so semantic resolution scores it against nothing
#: and the turn used to decline; but a learner mid-lesson asking to practise is
#: continuing that lesson, and §10 turns exactly this request into a widget.
_ASKS_TO_PRACTISE = re.compile(
    r"""^\s*(?:(?:can\s+)?(?:you\s+|i\s+)?(?:have|get|give|do|try|want|let'?s|lets)\s+)?
    (?:me\s+)?(?:a|an|some|another|more)?\s*
    (?:practice|practise|quiz|question|problem|exercise|example|go|try|test)
    (?:\s+(?:question|problem|one|it|please))?\s*[.!?]*\s*$""",
    re.VERBOSE | re.IGNORECASE,
)


def asks_to_practise(utterance: str) -> bool:
    """Whether this message asks to work on what is already being taught."""
    return bool(_ASKS_TO_PRACTISE.match((utterance or "").strip()))


#: How many tokens a message may have and still be read as a reply on its own.
CONTINUATION_MAX_TOKENS = 3


def is_continuation(utterance: str, *, awaiting_answer: bool = False) -> bool:
    """Whether this message continues the current concept rather than starting one."""
    text = (utterance or "").strip().lower().rstrip("?!.")
    if not text:
        return True

    if text in _CONTINUATION_WORDS:
        return True

    # Checked before `_NEW_ENQUIRY`, which reads "give me a practice question"
    # as an enquiry about the word "practice".
    if asks_to_practise(text):
        return True

    # A bare number, an amount, or a number with a unit.
    if re.fullmatch(r"[a-z$€£]{0,3}\s?\d[\d,.]*\s*[a-z%$]{0,8}", text):
        return True

    if _NEW_ENQUIRY.search(text):
        return False

    if awaiting_answer:
        # Mid-check, anything that is not plainly a new enquiry is an attempt at the question.
        return True

    return len(text.split()) <= CONTINUATION_MAX_TOKENS


# ── disambiguation ───────────────────────────────────────────────────────────

_DISAMBIGUATE_SYSTEM = """A learner asked a question. Which of these teaching concepts is
it about?

Reply with JSON only: {"concept_id": "<id from the list>"} or {"concept_id": null}.

Choose null unless the question is clearly about one of them. Null is the safe answer:
it falls through to a general search, which is better than teaching the wrong idea
confidently. Do not choose the concept that merely shares a word with the question."""


async def _disambiguate(
    utterance: str,
    candidates: Sequence[tuple[TeachingConcept, float]],
    invoke: Any,
) -> TeachingConcept | None:
    """One cheap structured call over the top few candidates."""
    if invoke is None or not candidates:
        return None

    menu = "\n".join(
        f"{concept.id} | {concept.title} | {', '.join(concept.aliases[:4])}"
        for concept, _ in candidates
    )
    by_id = {concept.id: concept for concept, _ in candidates}

    try:
        answer = await invoke(
            system=_DISAMBIGUATE_SYSTEM,
            user=f"QUESTION: {utterance}\n\nCONCEPTS:\n{menu}",
        )
    except Exception:
        logger.warning("Concept disambiguation failed; falling through.", exc_info=True)
        return None

    if not isinstance(answer, dict):
        return None
    return by_id.get(str(answer.get("concept_id") or ""))


# ── the entry point ──────────────────────────────────────────────────────────


async def resolve_concept(
    utterance: str,
    *,
    band: str,
    locale: str = "en",
    active_concept_id: str | None = None,
    awaiting_answer: bool = False,
    store: ConceptStore | None = None,
    embed: Any = None,
    retrieve: Any = None,
    disambiguate: Any = None,
    settings: Any = None,
) -> ConceptResolution:
    """What this turn is about."""
    from app.config import get_settings

    settings = settings or get_settings()
    store = store or get_store()
    text = (utterance or "").strip()

    # ── 1. continuation ─────────────────────────────────────────────────────
    if active_concept_id and is_continuation(text, awaiting_answer=awaiting_answer):
        concept = store.get(active_concept_id)
        if concept is not None:
            return ConceptResolution(concept=concept, source="continuation", similarity=1.0)
        # The active concept vanished from the store -- a reseed between turns.
        logger.info("Active concept %s is no longer in the store.", active_concept_id)

    if not text:
        return ConceptResolution(source="none")

    # ── 2. semantic ─────────────────────────────────────────────────────────
    ranked: list[tuple[TeachingConcept, float]] = []
    if embed is not None and len(store) and store.has_embeddings:
        try:
            vector = await embed(text)
            ranked = store.rank(
                vector, band=band, locale=locale, top=settings.learn_disambiguate_k
            )
        except Exception:
            logger.warning("Concept embedding failed; falling through.", exc_info=True)

    # Lexical, when there is no vector to compare against or the embedder failed.
    if not ranked and len(store):
        ranked = store.rank_lexical(
            text, band=band, locale=locale, top=settings.learn_disambiguate_k
        )
        if ranked:
            logger.debug(
                "Resolved lexically (%s at %.2f); the store has no usable vectors.",
                ranked[0][0].slug,
                ranked[0][1],
            )

    if ranked:
        best, score = ranked[0]
        if score >= settings.learn_resolve_threshold:
            return ConceptResolution(
                concept=best,
                source="semantic",
                similarity=score,
                alternatives=tuple(concept for concept, _ in ranked[1:]),
            )

        if score >= settings.learn_disambiguate_floor:
            chosen = await _disambiguate(text, ranked, disambiguate)
            if chosen is not None:
                return ConceptResolution(
                    concept=chosen,
                    source="disambiguated",
                    similarity=score,
                    alternatives=tuple(c for c, _ in ranked if c.id != chosen.id),
                )

    # ── 3. RAG teach ────────────────────────────────────────────────────────
    rows: tuple[Any, ...] = ()
    if retrieve is not None:
        try:
            rows = tuple(await retrieve(text))
        except Exception:
            logger.warning("RAG-teach retrieval failed.", exc_info=True)

    best_score = max((_score_of(row) for row in rows), default=0.0)
    if rows and best_score >= settings.qa_relevance_floor:
        return ConceptResolution(
            source="rag",
            similarity=best_score,
            kb_rows=rows,
            alternatives=tuple(concept for concept, _ in ranked[:2]),
        )

    # ── 4. nothing resolved ─────────────────────────────────────────────────
    offers = [concept for concept, _ in ranked] or store.teachable(band, locale)[:2]
    return ConceptResolution(
        source="none",
        similarity=max(best_score, ranked[0][1] if ranked else 0.0),
        alternatives=tuple(offers[:2]),
    )


# ── placement: a learning request that names nothing ─────────────────────────

#: "Teach me", "let's learn", "start a lesson" -- a request to be taught with no
#: topic in it. Semantic resolution scores these against nothing, so they used to
#: fall through to the curriculum lesson machine, which cannot emit a widget and
#: never sets `active_concept_id` -- so the session never came back to the tutor.
_WANTS_A_LESSON = re.compile(
    r"""^\s*(?:(?:can\s+you|could\s+you|please|hey|ok(?:ay)?)[\s,]+)?
    (?:
        (?:teach|show|tell)\s+me(?:\s+(?:something|anything|a\s+lesson|more|stuff))?
      | (?:i\s+(?:want|would\s+like|'?d\s+like)\s+to\s+)?learn
            (?:\s+(?:something|anything|more|about\s+money|stuff))?
      | (?:let'?s|lets)\s+(?:learn|start|begin|go)
      | (?:start|begin)(?:\s+(?:a\s+)?(?:lesson|learning))?
      | (?:next|another|a\s+new)\s+(?:lesson|topic|one)
      | help\s+me\s+learn(?:\s+about\s+\w+)?
      | (?:what|anything)\s+(?:can|should)\s+(?:you\s+teach|i\s+learn)
    )
    \s*[.!?]*\s*$""",
    re.VERBOSE | re.IGNORECASE,
)


def wants_a_lesson(text: str) -> bool:
    """Whether this asks to be taught without saying what."""
    return bool(_WANTS_A_LESSON.match((text or "").strip()))


def place_concept(
    *,
    store: ConceptStore,
    band: str,
    locale: str = "en",
    mastery: dict[str, int] | None = None,
    exclude: set[str] | None = None,
) -> TeachingConcept | None:
    """What to teach a learner who asked to learn but did not say what.

    The weakest thing they have not finished, which is the same instinct
    `scheduler.place` applies to authored lessons: something started and not
    secure comes before something never seen, because leaving a half-learned
    idea behind is how gaps are made.
    """
    scores = mastery or {}
    skip = exclude or set()

    candidates = [
        concept
        for concept in store.teachable(band, locale)
        if concept.id not in skip and scores.get(concept.id, 0) < MASTERED_SCORE
    ]
    if not candidates:
        return None

    def rank(concept: TeachingConcept) -> tuple[int, int, str]:
        score = scores.get(concept.id, 0)
        # Started but unfinished first (1..2), then untouched (0), then by slug
        # so the same learner is not given a different lesson on a re-run.
        return (0 if score else 1, -score, concept.slug)

    return sorted(candidates, key=rank)[0]


#: Mastery at which a concept no longer needs placing. Mirrors `planner.MASTERED`.
MASTERED_SCORE = 3


def _score_of(row: Any) -> float:
    for attribute in ("score", "similarity", "relevance"):
        value = getattr(row, attribute, None)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


# ── the gap list ─────────────────────────────────────────────────────────────


async def enqueue_candidate(
    utterance: str,
    *,
    band: str,
    locale: str,
    resolution: ConceptResolution,
) -> None:
    """Record that no concept covered this question."""
    text = (utterance or "").strip()[:400]
    if not text:
        return

    try:
        from sqlalchemy import text as sql

        from app.db.engine import get_sessionmaker

        maker = get_sessionmaker()
        if maker is None:
            return
        async with maker() as session:
            await session.execute(
                sql(
                    """
                    INSERT INTO concept_candidates
                        (utterance, locale, age_band, kb_ids, best_similarity)
                    VALUES (:utterance, :locale, :band, :kb_ids, :similarity)
                    ON CONFLICT (utterance, locale) DO UPDATE SET
                        hits = concept_candidates.hits + 1,
                        last_seen = now(),
                        best_similarity = GREATEST(
                            concept_candidates.best_similarity, EXCLUDED.best_similarity
                        )
                    """
                ),
                {
                    "utterance": text,
                    "locale": locale,
                    "band": band,
                    "kb_ids": [
                        str(getattr(row, "kb_id", "") or "")
                        for row in resolution.kb_rows
                        if getattr(row, "kb_id", None)
                    ],
                    "similarity": resolution.similarity,
                },
            )
            await session.commit()
    except Exception:
        logger.debug("Could not record a concept candidate.", exc_info=True)
