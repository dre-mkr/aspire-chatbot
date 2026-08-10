"""Which move this turn makes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.agents.learn.evaluate import Diagnosis, Verdict
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
    #: The explanation did not land. Come at it from a different direction --
    #: which direction is `strategy.next_strategy`'s decision, not this one's.
    RETEACH = "RETEACH"
    #: They hold a specific wrong model, and it is named. Address that model.
    CORRECT_MISCONCEPTION = "CORRECT_MISCONCEPTION"
    #: They asked for the answer. §12: give it, with the reasoning.
    ANSWER = "ANSWER"
    #: The gap is underneath this concept, not in it. Teach the thing below.
    STEP_BACK = "STEP_BACK"


#: Mastery at which a concept is done and the learner moves on.
MASTERED = 3

#: How many turns on one concept before a game is offered instead of more prose.
TURNS_BEFORE_GAME = 4

#: How many turns may pass without a check before one is due.
TURNS_BEFORE_CHECK = 2

#: Wrong answers on one concept before its prerequisites are suspected.
STRUGGLES_BEFORE_STEP_BACK = 2

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

    # ── what this turn demonstrated ─────────────────────────────────────────── None when the learner asked somethin…

    #: This turn's grading, or None when there was nothing to grade.
    verdict: Verdict | None = None
    diagnosis: Diagnosis = Diagnosis.NONE
    #: Whether the evaluation matched one of the concept's authored misconceptions.
    holds_misconception: bool = False
    #: Whether the learner said, in any words, that they do not follow. Set
    #: whether or not a check was outstanding -- "I still don't understand"
    #: after an explanation is the case §14 is about, and no question is open.
    confused: bool = False
    #: Wrong answers on this concept across the session, not just consecutively.
    wrong_on_concept: int = 0
    #: How many hint rungs this question's author actually wrote.
    hints_available: int = 0
    #: The rung already given on the current question.
    hint_rung: int = 0
    #: Whether a weak prerequisite for this concept exists to step back to.
    prerequisite_available: bool = False
    #: Whether the learner asked, in so many words, to practise. §10's first case.
    wants_practice: bool = False

    @classmethod
    def from_state(
        cls,
        learning: dict[str, Any],
        *,
        band: str,
        concept: TeachingConcept | None,
        mastery: int = 0,
        verdict: Verdict | None = None,
        diagnosis: Diagnosis = Diagnosis.NONE,
        holds_misconception: bool = False,
        confused: bool = False,
        hints_available: int = 0,
        prerequisite_available: bool = False,
        wants_practice: bool = False,
    ) -> "LearnerSnapshot":
        concept_id = concept.id if concept else None
        per_concept = (learning.get("turns_on_concept") or {}) if isinstance(
            learning.get("turns_on_concept"), dict
        ) else {}
        wrong_counts = (learning.get("wrong_by_concept") or {}) if isinstance(
            learning.get("wrong_by_concept"), dict
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
            verdict=verdict,
            diagnosis=diagnosis,
            holds_misconception=holds_misconception,
            confused=confused,
            wrong_on_concept=int(wrong_counts.get(concept_id or "", 0)),
            hints_available=int(hints_available or 0),
            hint_rung=int(learning.get("hint_rung_now") or 0),
            prerequisite_available=bool(prerequisite_available),
            wants_practice=bool(wants_practice),
        )

    @property
    def ladder_exhausted(self) -> bool:
        """Whether every hint this question's author wrote has been given."""
        return self.hint_rung >= max(self.hints_available, 1)


def plan_move(snapshot: LearnerSnapshot) -> Move:
    """The one move this turn makes.

    The order of the tests IS the pedagogy, and it reads top to bottom as a
    tutor's priorities: answer what they explicitly asked for, respond to what
    they just demonstrated, and only then decide what to do next.
    """
    # ── what they asked for outranks what we planned ────────────────────────
    if snapshot.verdict is Verdict.ASKS_FOR_ANSWER:
        return Move.ANSWER

    # ── what they just demonstrated ─────────────────────────────────────────
    if snapshot.verdict is Verdict.CORRECT:
        # One correct answer is not mastery (§15). The scale decides, not this turn.
        return Move.ADVANCE if snapshot.mastery >= MASTERED else Move.EVALUATE

    if snapshot.verdict is not None and snapshot.verdict.is_attempt:
        return _after_a_miss(snapshot)

    if snapshot.verdict is Verdict.DONT_KNOW or snapshot.confused:
        # Not a wrong answer -- an absence of one. Teaching it as a wrong answer
        # is how a learner is taught to guess instead of to say so.
        return _after_confusion(snapshot)

    # A check was outstanding and what came back was not an attempt at it. Ask
    # it again rather than dropping the thread.
    if snapshot.awaiting_check_answer and snapshot.has_check_item:
        return Move.CHECK

    # ── nothing to react to: what next? ─────────────────────────────────────
    if snapshot.mastery >= MASTERED:
        return Move.ADVANCE

    if snapshot.turns_on_concept >= TURNS_BEFORE_GAME and band_allows_games(snapshot.band):
        return Move.GAME

    if not snapshot.has_been_taught:
        # A first teach ends with a check question, so a practice request made
        # before the idea has been met is still answered by teaching it.
        return Move.TEACH

    # §10's first case: they asked to practise, so practise rather than recap.
    if snapshot.wants_practice and snapshot.has_check_item:
        return Move.CHECK

    if snapshot.turns_since_check >= TURNS_BEFORE_CHECK and snapshot.has_check_item:
        return Move.CHECK

    # Taught recently, nothing outstanding. Say it another way.
    return Move.RECAP


def _after_a_miss(snapshot: LearnerSnapshot) -> Move:
    """They answered, and it was not right."""
    # The gap is underneath this concept, so more of this concept cannot close it.
    if snapshot.prerequisite_available and snapshot.wrong_on_concept >= STRUGGLES_BEFORE_STEP_BACK:
        return Move.STEP_BACK

    # A named wrong model is worth addressing directly; a hint would scaffold
    # them towards the right answer while leaving the wrong model in place.
    if snapshot.holds_misconception:
        return Move.CORRECT_MISCONCEPTION

    # Hinting only helps when the understanding underneath is sound.
    if snapshot.diagnosis.needs_reteach:
        return Move.RETEACH

    if snapshot.ladder_exhausted:
        # Every rung given and still not there. Do not repeat the last one.
        return Move.RETEACH

    return Move.HINT


def _after_confusion(snapshot: LearnerSnapshot) -> Move:
    """They said they cannot do it -- §14's case, and §12's.

    "I don't know" and "I don't understand" are different admissions. The first
    is about this question and is answered by scaffolding them into an attempt;
    the second is about the explanation and is answered by giving a different
    one. Re-explaining a whole concept because someone could not recall one
    number is as unhelpful as hinting at a question they never followed.
    """
    if snapshot.prerequisite_available and snapshot.wrong_on_concept >= STRUGGLES_BEFORE_STEP_BACK:
        return Move.STEP_BACK
    if snapshot.holds_misconception:
        return Move.CORRECT_MISCONCEPTION

    stuck_on_the_question = (
        snapshot.verdict is Verdict.DONT_KNOW
        and not snapshot.confused
        and not snapshot.ladder_exhausted
    )
    if stuck_on_the_question:
        return Move.HINT

    # Never the same explanation again. `next_strategy` chooses the direction.
    return Move.RETEACH


def hint_level(snapshot: LearnerSnapshot) -> int:
    """Which rung of the ladder to give now.

    Assistance increases with what the learner has shown, which is what makes
    this scaffolding rather than a fixed script (§12). The ceiling is the
    number of rungs the question's author actually wrote -- there is no rung
    that gives the answer, and `Move.ANSWER` is a different move.
    """
    ceiling = min(snapshot.hints_available or MAX_HINT_LEVEL, MAX_HINT_LEVEL)
    return max(1, min(snapshot.hint_rung + 1, ceiling))


def exhausted_ladder(snapshot: LearnerSnapshot) -> bool:
    """Whether the ladder has run out and the concept should be retaught."""
    return snapshot.ladder_exhausted


#: Moves that teach rather than react, and so consume a rung of the strategy ladder.
EXPLAINING_MOVES: frozenset[Move] = frozenset(
    {Move.TEACH, Move.RECAP, Move.RETEACH, Move.CORRECT_MISCONCEPTION, Move.STEP_BACK}
)

#: Moves that put a check question to the learner, so the next message answers it.
ASKING_MOVES: frozenset[Move] = frozenset(
    {Move.TEACH, Move.CHECK, Move.RECAP, Move.ADVANCE, Move.HINT, Move.EVALUATE, Move.RETEACH}
)
