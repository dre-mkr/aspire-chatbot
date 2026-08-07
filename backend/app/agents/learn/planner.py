"""Which move this turn makes. Pure Python, no model, no exceptions.

    TEACH     explain the concept
    CHECK     ask a question from the bank
    EVALUATE  grade the answer that just arrived
    HINT      one rung up the ladder
    ADVANCE   they have it; move to what it unlocks
    GAME      four turns on one idea is enough; play instead
    RECAP     they have met it and are not due a check; say it a different way

The renderer is told WHICH move and renders it. It never chooses between
teaching and quizzing, and that separation is the reason a hint ladder means
anything: a rung count is only a ladder if "wrong" is decided the same way on
Tuesday as on Monday, and a model asked to decide whether to hint or reteach
gives a different answer each time it is asked.

## Why this is a function and not a graph

The lesson machine in `graph.py` already routes between nodes on `phase`. This
plans the move WITHIN a resolved concept, which is a different question: phase
says "we are mid-check", move says "and therefore evaluate". Keeping them
separate means the graph's routing stays about turn structure and this stays
about pedagogy, and each is testable without the other.

## Exhaustively unit-tested, and there is no excuse not to be

Every input is a small enum or a bounded integer. `tests/learning/test_planner.py`
walks the whole cross-product. A pure function with a state space this small that
still has an untested branch is a choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.learning.concepts import TeachingConcept


class Move(str, Enum):
    """What the renderer is asked to produce.

    `str` mixin so a move serialises into a checkpoint and a log line as its own
    name rather than as `Move.TEACH`, and so a value read back out of a
    checkpoint compares equal to the enum without a conversion nobody would
    remember to write.
    """

    TEACH = "TEACH"
    CHECK = "CHECK"
    EVALUATE = "EVALUATE"
    HINT = "HINT"
    ADVANCE = "ADVANCE"
    GAME = "GAME"
    RECAP = "RECAP"


#: Mastery at which a concept is done and the learner moves on.
MASTERED = 3

#: How many turns on one concept before a game is offered instead of more prose.
#:
#: Four. Below that the lesson has not finished; above it, a learner who is still
#: on the same idea is not being helped by a fifth explanation of it.
TURNS_BEFORE_GAME = 4

#: How many turns may pass without a check before one is due.
TURNS_BEFORE_CHECK = 2

#: Bands that get games. Not 16-18 or adult: the game seeds are written for
#: children, and offering a sixteen-year-old a matching game in place of the
#: explanation they asked for reads as being talked down to.
GAME_BANDS: frozenset[str] = frozenset({"5-8", "9-12", "13-15"})

#: The highest hint rung. Rung 3 gives the METHOD, never the bare answer -- see
#: `nodes/hint_ladder.py`. Past it the concept is retaught rather than looped.
MAX_HINT_LEVEL = 3


def band_allows_games(band: str) -> bool:
    return band in GAME_BANDS


@dataclass(frozen=True, slots=True)
class LearnerSnapshot:
    """Everything `plan_move` is allowed to know.

    A frozen record rather than the live graph state, and deliberately small. A
    planner that could see the message history would start making editorial
    judgements about tone, and this is meant to be a decision a reviewer can
    re-derive from seven numbers.

    Built by `from_state` so the graph's dict shape stays in one place.
    """

    band: str = "9-12"
    #: The concept this snapshot is about. None on a turn with nothing resolved.
    concept_id: str | None = None
    #: 0 unseen, 1 exposed, 2 practised, 3 mastered.
    mastery: int = 0
    #: A check question is outstanding and the next message is its answer.
    awaiting_check_answer: bool = False
    #: Consecutive wrong answers on THIS concept. Drives the hint rung.
    consecutive_wrong: int = 0
    #: How many turns this session has spent on this concept.
    turns_on_concept: int = 0
    #: How many turns since the last check question was asked.
    turns_since_check: int = 0
    #: Whether this learner has ever been taught this concept.
    has_been_taught: bool = False
    #: Whether a check item is available at all. A concept whose bank is empty
    #: cannot be checked, and planning CHECK anyway produces a turn that asks
    #: nothing.
    has_check_item: bool = True

    @classmethod
    def from_state(
        cls,
        learning: dict[str, Any],
        *,
        band: str,
        concept: TeachingConcept | None,
        mastery: int = 0,
    ) -> "LearnerSnapshot":
        concept_id = concept.id if concept else None
        per_concept = (learning.get("turns_on_concept") or {}) if isinstance(
            learning.get("turns_on_concept"), dict
        ) else {}
        return cls(
            band=band,
            concept_id=concept_id,
            mastery=int(mastery or 0),
            awaiting_check_answer=bool(learning.get("awaiting_check_answer")),
            consecutive_wrong=int(learning.get("consecutive_wrong") or 0),
            turns_on_concept=int(per_concept.get(concept_id or "", 0)),
            turns_since_check=int(learning.get("turns_since_check") or 0),
            has_been_taught=concept_id in set(learning.get("concepts_touched") or []),
            has_check_item=bool(concept and concept.checks_for(band)),
        )


def plan_move(snapshot: LearnerSnapshot) -> Move:
    """The one move this turn makes.

    The order of these tests IS the pedagogy, so each is annotated with what it
    is protecting against rather than with what it does.
    """
    # An outstanding question outranks everything. A learner who was asked
    # something and replied must be answered about their reply -- teaching them
    # a new idea instead is the single most disorienting thing this machine can
    # do, and it is what happens if any other test runs first.
    if snapshot.awaiting_check_answer:
        return Move.EVALUATE

    # They have just got one wrong. The ladder, not a fresh explanation: a child
    # who missed a question needs a smaller step, and re-teaching from the top is
    # how "I already told you" gets communicated without anybody saying it.
    if snapshot.consecutive_wrong >= 1:
        return Move.HINT

    # Mastered. Moving on is not optional politeness -- spaced repetition brings
    # this concept back on its own schedule, and re-teaching it now would displace
    # the concept they have not met.
    if snapshot.mastery >= MASTERED:
        return Move.ADVANCE

    # Four turns in and still here. A fifth paragraph is not the intervention;
    # doing something with the idea is.
    if snapshot.turns_on_concept >= TURNS_BEFORE_GAME and band_allows_games(snapshot.band):
        return Move.GAME

    # Never taught. This is the common case on a resolved question and it is the
    # one the whole agent exists for.
    if not snapshot.has_been_taught:
        return Move.TEACH

    # Taught, and two turns have gone by without checking. Understanding that is
    # never checked is understanding nobody has evidence of, and mastery cannot
    # move without evidence.
    if snapshot.turns_since_check >= TURNS_BEFORE_CHECK and snapshot.has_check_item:
        return Move.CHECK

    # Taught recently, nothing outstanding. Say it another way.
    return Move.RECAP


def hint_level(snapshot: LearnerSnapshot) -> int:
    """Which rung of the ladder. Capped, and the cap is not a formality.

    Past rung 3 the ladder has nothing left to offer -- rung 3 already gives the
    method -- and looping it produces a child being nudged towards an answer they
    have demonstrably not got. `graph.py` reads the cap and reteaches instead.
    """
    return max(1, min(snapshot.consecutive_wrong, MAX_HINT_LEVEL))


def exhausted_ladder(snapshot: LearnerSnapshot) -> bool:
    """Whether the ladder has run out and the concept should be retaught."""
    return snapshot.consecutive_wrong > MAX_HINT_LEVEL
