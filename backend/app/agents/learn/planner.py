"""Which move this turn makes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.learning.concepts import TeachingConcept


class Move(str, Enum):
    """What the renderer is asked to produce."""

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
TURNS_BEFORE_GAME = 4

#: How many turns may pass without a check before one is due.
TURNS_BEFORE_CHECK = 2

#: Bands that get games.
GAME_BANDS: frozenset[str] = frozenset({"5-8", "9-12", "13-15"})

#: The highest hint rung.
MAX_HINT_LEVEL = 3


def band_allows_games(band: str) -> bool:
    return band in GAME_BANDS


@dataclass(frozen=True, slots=True)
class LearnerSnapshot:
    """Everything `plan_move` is allowed to know."""

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
    #: Whether a check item is available at all.
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
    """The one move this turn makes."""
    # An outstanding question outranks everything.
    if snapshot.awaiting_check_answer:
        return Move.EVALUATE

    # They have just got one wrong.
    if snapshot.consecutive_wrong >= 1:
        return Move.HINT

    # Mastered.
    if snapshot.mastery >= MASTERED:
        return Move.ADVANCE

    # Four turns in and still here.
    if snapshot.turns_on_concept >= TURNS_BEFORE_GAME and band_allows_games(snapshot.band):
        return Move.GAME

    # Never taught.
    if not snapshot.has_been_taught:
        return Move.TEACH

    # Taught, and two turns have gone by without checking.
    if snapshot.turns_since_check >= TURNS_BEFORE_CHECK and snapshot.has_check_item:
        return Move.CHECK

    # Taught recently, nothing outstanding. Say it another way.
    return Move.RECAP


def hint_level(snapshot: LearnerSnapshot) -> int:
    """Which rung of the ladder."""
    return max(1, min(snapshot.consecutive_wrong, MAX_HINT_LEVEL))


def exhausted_ladder(snapshot: LearnerSnapshot) -> bool:
    """Whether the ladder has run out and the concept should be retaught."""
    return snapshot.consecutive_wrong > MAX_HINT_LEVEL
