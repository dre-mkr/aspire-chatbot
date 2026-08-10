"""What is this turn about? Four answers, in strict order of precedence.

    continuation  the learner is still on the concept they were on
    semantic      the utterance matches an authored concept
    rag           no concept matches, but the knowledge base has enough to teach
    none          nothing above the floor; say so, in persona, and offer two others

Before this module existed, the learning agent answered a fifth way: *whatever
the spaced-repetition scheduler placed next*. `resume_or_place` chose a lesson
from mastery rows and the band, and the child's message was never consulted --
so "What is compound interest?" was answered with a competent lesson about what
saving is. That is the defect this file exists to close, and it is worth stating
plainly because the symptom ("the explanation is thin and generic") points at the
renderer while the cause was here.

Placement still exists and is still right. It decides what to teach when the
learner has not asked for anything -- a session that opens with "hi", a lesson
that finishes and rolls into the next. Resolution decides when they HAVE asked.

## Why continuation is checked first, and is not a similarity question

A learner who has just been asked "how much after 4 weeks?" replies "20". That
message embeds close to nothing in the concept store, because it is not about a
topic -- it is an answer. Every other branch of this function would get it wrong,
and getting it wrong means treating a correct answer as a new question and
teaching them something else.

So continuation is decided structurally, not semantically: is there an active
concept, and does this message look like a reply rather than an enquiry? Short,
no new subject noun, no question about a different thing. `is_continuation`
carries the whole rule and is unit-tested against the phrasings that matter.

## Why the thresholds are configuration

0.62 and 0.45 are decision boundaries. A concept resolved at 0.61 rather than
falling through to RAG-teach is a different lesson delivered to a child, and the
only honest way to set a boundary like that is to measure where the two
populations actually separate -- see `evals/learning_resolution.jsonl` and
`scripts/calibrate_resolution.py`. They live in `Settings` so a recalibration is
a config change rather than a code change.

## Falling through is a feature

`source="rag"` teaches from raw knowledge-base rows when no concept covers the
question. `source="none"` declines. Both are better than the two alternatives an
agent reaches for on its own: improvising a lesson about something nobody
authored, or escalating to a human because a nine-year-old asked about
cryptocurrency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence

from app.learning.concepts import ConceptStore, TeachingConcept, get_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConceptResolution:
    """What this turn is about, and how confidently we know.

    `source` is the thing worth logging on every turn. The rate of `"none"` is
    the product's blind-spot metric and the rate of `"rag"` is its authoring
    backlog, and neither is visible from a similarity score alone.
    """

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

#: Bare acknowledgements and requests to carry on. These are continuations at any
#: length because they name no subject at all.
_CONTINUATION_WORDS = frozenset(
    {
        "yes", "yeah", "yep", "yh", "ok", "okay", "sure", "no", "nope", "nah",
        "more", "again", "next", "continue", "go on", "keep going", "carry on",
        "why", "why?", "how", "how?", "what", "huh", "eh", "i think so",
        "i dont know", "i don't know", "dunno", "idk", "not sure", "maybe",
        "got it", "i see", "cool", "thanks", "ta", "tell me", "show me",
        # The three shipped locales. A Spanish learner answering "sí" is
        # continuing, and a continuation check that only speaks English routes
        # them into a new knowledge query on every affirmative.
        "sí", "si", "vale", "claro", "más", "mas", "otra vez", "no sé", "no se",
        "oui", "ouais", "d'accord", "encore", "plus", "je ne sais pas",
    }
)

#: A message that is asking about a NEW thing rather than replying about this one.
#:
#: Deliberately narrow. A false positive here breaks a lesson mid-check by
#: treating "what is that?" as a topic change; a false negative merely leaves a
#: genuine new question resolving through the semantic path, which handles it
#: correctly anyway. So this only fires on an interrogative attached to a noun
#: phrase -- "what is inflation", not "what?".
_NEW_ENQUIRY = re.compile(
    r"""^\s*(?:
        (?:what|whats|what's|who|which|when|where|why|how)\b[^?]*\b\w{4,}
      | (?:tell|teach|explain|show)\s+me\s+(?:about\s+)?\w{4,}
      | (?:can|could)\s+(?:you|we)\s+(?:tell|teach|explain|show)\b
      | (?:i\s+want\s+to|i'?d\s+like\s+to)\s+(?:learn|know)\b
    )""",
    re.VERBOSE | re.IGNORECASE,
)

#: How many tokens a message may have and still be read as a reply on its own.
#:
#: Three, from the brief. It is the length at which a message stops being an
#: answer and starts being a sentence: "twenty dollars" and "the blue one" are
#: replies; "how does saving money work" is not.
CONTINUATION_MAX_TOKENS = 3


def is_continuation(utterance: str, *, awaiting_answer: bool = False) -> bool:
    """Whether this message continues the current concept rather than starting one.

    `awaiting_answer` widens the rule and is the reason it is a parameter rather
    than an inference. A learner who was just asked a question is REPLYING, and a
    reply may legitimately be a whole sentence -- "because the bank adds a bit
    every year" is thirty characters of continuation. Outside a pending check the
    same sentence would be a new topic.
    """
    text = (utterance or "").strip().lower().rstrip("?!.")
    if not text:
        return True

    if text in _CONTINUATION_WORDS:
        return True

    # A bare number, an amount, or a number with a unit. This is the case the
    # whole function exists for: `4`, `EC$20`, `20 dollars`, `4 weeks`.
    if re.fullmatch(r"[a-z$€£]{0,3}\s?\d[\d,.]*\s*[a-z%$]{0,8}", text):
        return True

    if _NEW_ENQUIRY.search(text):
        return False

    if awaiting_answer:
        # Mid-check, anything that is not plainly a new enquiry is an attempt at
        # the question. Grading it wrongly costs a hint; treating it as a topic
        # change costs the lesson.
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
    """One cheap structured call over the top few candidates.

    Only reached in the band between the two thresholds, which is where the
    embedding genuinely cannot tell -- "what happens to my money in the bank"
    sits equidistant from `interest`, `saving_account` and `bank_safety`. A model
    reading three titles and one sentence settles it for a fraction of a cent.

    Returns None on any failure. The caller falls through to RAG-teach, which
    still teaches.
    """
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
    """What this turn is about.

    Every collaborator is injected and optional, which is what lets the unit tests
    drive the precedence order with no network and no database. With all of them
    None the function still answers -- `source="none"` -- rather than raising,
    because a learning turn that cannot resolve must still say something in
    persona.
    """
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
        # Fall through rather than declining: the utterance may still resolve.
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
    #
    # Reached in two situations and neither is exotic: a concept table seeded
    # while the embeddings model was unavailable, and an embedder outage on a
    # live turn. Both leave complete teaching material in the store with no way
    # to find it, and word overlap over titles and aliases is a poor index that
    # is enormously better than declining every question.
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

    # ── 3. RAG-teach ────────────────────────────────────────────────────────
    #
    # No concept covers this. The knowledge base might still, and teaching from
    # rows is a great deal better than declining -- the corpus is 706 verified
    # rows and the taxonomy is a few dozen concepts, so there is real material
    # here that no concept has been authored around yet.
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

    # ── 4. decline ──────────────────────────────────────────────────────────
    #
    # Two concepts they have not seen come back as `alternatives`, and the
    # renderer offers them. A decline with nothing attached is a dead end, and a
    # dead end in a lesson is where a child stops.
    offers = [concept for concept, _ in ranked] or store.teachable(band, locale)[:2]
    return ConceptResolution(
        source="none",
        similarity=max(best_score, ranked[0][1] if ranked else 0.0),
        alternatives=tuple(offers[:2]),
    )


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
    """Record that no concept covered this question.

    Written on the `rag` and `none` paths, upserted on the utterance so that the
    `hits` column becomes an ordering for the authoring backlog. One child asking
    once is noise; forty asking is a missing lesson, and that distinction is not
    available from a log grep.

    Swallows every failure. A gap-tracking write must never be the thing that
    breaks a turn -- the child is owed a lesson, not a complete audit trail.
    """
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
