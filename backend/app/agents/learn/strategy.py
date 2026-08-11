"""When the explanation did not land, change the explanation.

Two things a tutor does that this agent could not.

§14 -- the strategy ladder. "I still don't understand" used to produce another
lesson from the same prompt with a different opening sentence, because varying
the opening was the only variety mechanism there was. A learner who did not
follow a definition does not need the definition again in a fresh voice; they
need an analogy, and then a worked number, and then to be walked through it.
The rung is state, so a second failure moves down rather than round.

§17 -- prerequisites. Reteaching compound interest to a learner whose problem
is percentages is the classic way to spend a lesson achieving nothing. The
curriculum already carries an authored prerequisite graph, keyed by the same
slugs the teachable-concept rows were seeded with, so the link is a lookup
rather than a new table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.agents.learn.evaluate import Diagnosis
from app.learning.concepts import ConceptStore, TeachingConcept

logger = logging.getLogger(__name__)


class Strategy(str, Enum):
    """How the idea is put across. The rungs of §14, in order."""

    DEFINITION = "DEFINITION"
    ANALOGY = "ANALOGY"
    NUMERIC_EXAMPLE = "NUMERIC_EXAMPLE"
    WALKTHROUGH = "WALKTHROUGH"
    GUIDED_QUESTION = "GUIDED_QUESTION"
    PRACTICE = "PRACTICE"


#: The ladder, in the order a tutor works down it.
LADDER: tuple[Strategy, ...] = (
    Strategy.DEFINITION,
    Strategy.ANALOGY,
    Strategy.NUMERIC_EXAMPLE,
    Strategy.WALKTHROUGH,
    Strategy.GUIDED_QUESTION,
    Strategy.PRACTICE,
)

#: What each rung tells the renderer to do. Written as instructions, not labels.
INSTRUCTIONS: dict[Strategy, str] = {
    Strategy.DEFINITION: (
        "Explain the idea directly: what it is, then why it works that way."
    ),
    Strategy.ANALOGY: (
        "Do NOT define it again -- that did not land. Open with a concrete "
        "everyday comparison from their world (a shop, a bus fare, a bucket "
        "filling up, sharing out a plate of food) and let the idea arrive "
        "through the comparison. Name the idea only after the picture is clear."
    ),
    Strategy.NUMERIC_EXAMPLE: (
        "Words have not worked twice. Use the numbers you were given and walk "
        "one small case all the way through, stating each figure as it appears. "
        "Invent no numbers of your own."
    ),
    Strategy.WALKTHROUGH: (
        "Break it into the smallest steps it has and take them one at a time, "
        "saying what happens at each and why. Do not compress."
    ),
    Strategy.GUIDED_QUESTION: (
        "Stop explaining. They have heard it explained three ways. Ask them one "
        "short question about the very first step only -- something they can "
        "almost certainly answer -- so you can see where the understanding "
        "actually stops."
    ),
    Strategy.PRACTICE: (
        "Explaining has run its course. Give them something to do with the idea "
        "rather than something to follow, and keep it small enough to finish."
    ),
}


def _as_strategy(value: Strategy | str | None) -> Strategy | None:
    """A rung from either an enum member or its stored value, or None.

    `str()` on a member of a `str, Enum` returns "Strategy.ANALOGY" rather than
    "ANALOGY", so coercing through `str` loses every enum that arrives already
    typed -- and loses it silently, into whatever the caller's fallback is.
    """
    if isinstance(value, Strategy):
        return value
    try:
        return Strategy(value)
    except (ValueError, TypeError):
        return None


def next_strategy(
    current: Strategy | str | None, *, diagnosis: Diagnosis | None = None
) -> Strategy:
    """The rung to try now, given the one that just failed.

    A calculation error is the exception: their model of the idea is fine and
    the arithmetic slipped, so dropping to an analogy would be teaching them
    something they already know. Show the numbers again instead.
    """
    rung = _as_strategy(current)

    if diagnosis is Diagnosis.CALCULATION:
        return Strategy.NUMERIC_EXAMPLE
    if diagnosis is Diagnosis.TERMINOLOGY:
        # They have the idea and the wrong label for it. Naming beats re-explaining.
        return Strategy.ANALOGY if rung is Strategy.DEFINITION else Strategy.DEFINITION

    if rung is None:
        return LADDER[0]
    return LADDER[min(LADDER.index(rung) + 1, len(LADDER) - 1)]


def instruction_for(strategy: Strategy | str | None) -> str:
    """The renderer-facing sentence for a rung."""
    return INSTRUCTIONS[_as_strategy(strategy) or Strategy.DEFINITION]


# ── §17: prerequisites ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Prerequisite:
    """A concept to step back to, and why we think so."""

    concept: TeachingConcept
    #: authored | heuristic. Logged, so the two are never confused in the data.
    source: str
    reason: str = ""


#: Mastery at or above which a concept counts as secure enough to build on.
WEAK_ABOVE = 2


def _authored_prerequisites(concept: TeachingConcept, curriculum: Any) -> list[str]:
    """The curriculum's prerequisite slugs for this concept, if it authored any.

    The teachable-concept rows were seeded with `slug = id`, so a concept whose
    slug is a curriculum concept id inherits that concept's prerequisites. A
    synthesised concept matches nothing here and gets an empty list, which is
    the correct answer rather than a failure.
    """
    if curriculum is None:
        return []
    try:
        authored = curriculum.concepts.get(concept.slug)
    except Exception:  # pragma: no cover - a curriculum without a concept map
        return []
    return list(getattr(authored, "prerequisites", []) or [])


def find_prerequisite(
    concept: TeachingConcept | None,
    *,
    band: str,
    store: ConceptStore,
    mastery: dict[str, int],
    curriculum: Any = None,
    locale: str = "en",
) -> Prerequisite | None:
    """A concept to step back to, or None to carry on where we are.

    Only weak prerequisites are returned. A learner who has demonstrated the
    prerequisite and is still struggling has a problem with THIS idea, and
    sending them backwards would be both wrong and patronising.
    """
    if concept is None:
        return None

    for slug in _authored_prerequisites(concept, curriculum):
        earlier = store.by_slug(slug, locale) or store.by_slug(slug, concept.locale)
        if earlier is None or not earlier.teachable_at(band):
            continue
        if mastery.get(earlier.id, 0) >= WEAK_ABOVE:
            continue
        return Prerequisite(
            concept=earlier,
            source="authored",
            reason=f"{concept.slug} requires {slug}, and it is not yet secure",
        )

    # No authored chain. A concept in the same domain that this band can already
    # be taught and that starts EARLIER is a reasonable guess at what comes
    # first -- a guess, and logged as one.
    from app.learning.concepts import band_index

    candidates = [
        other
        for other in store.teachable(band, locale)
        if other.id != concept.id
        and other.domain == concept.domain
        and band_index(other.band_min) < band_index(concept.band_min)
        and mastery.get(other.id, 0) < WEAK_ABOVE
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda other: (band_index(other.band_min), other.slug))
    return Prerequisite(
        concept=candidates[0],
        source="heuristic",
        reason=(
            f"nothing authored for {concept.slug}; {candidates[0].slug} is the "
            "earliest unmastered concept in the same domain"
        ),
    )
