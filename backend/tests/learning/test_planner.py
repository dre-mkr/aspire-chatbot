"""`plan_move` is pure, its state space is small, and it is walked exhaustively."""

from __future__ import annotations

import itertools

import pytest

from app.agents.learn.evaluate import Diagnosis, Verdict
from app.agents.learn.planner import (
    EXPLAINING_MOVES,
    GAME_BANDS,
    MASTERED,
    MAX_HINT_LEVEL,
    STRUGGLES_BEFORE_STEP_BACK,
    TURNS_BEFORE_CHECK,
    TURNS_BEFORE_GAME,
    LearnerSnapshot,
    Move,
    band_allows_games,
    exhausted_ladder,
    hint_level,
    plan_move,
)
from app.learning.concepts import CheckItem, TeachingConcept


def snapshot(**changes) -> LearnerSnapshot:
    """A learner who has been taught the concept and has nothing outstanding."""
    base = dict(
        band="9-12",
        concept_id="CON-0001",
        mastery=1,
        awaiting_check_answer=False,
        consecutive_wrong=0,
        turns_on_concept=1,
        turns_since_check=0,
        has_been_taught=True,
        has_check_item=True,
    )
    base.update(changes)
    return LearnerSnapshot(**base)


def answered(verdict: Verdict, **changes) -> LearnerSnapshot:
    """A learner who has just answered the outstanding check."""
    changes.setdefault("hints_available", 3)
    return snapshot(awaiting_check_answer=True, verdict=verdict, **changes)


class TestPrecedence:
    """The order of the tests in `plan_move` IS the pedagogy. Each is pinned."""

    def test_an_explicit_request_for_the_answer_outranks_everything(self):
        """§12. The ladder exists to help them think, not to withhold."""
        move = plan_move(
            answered(
                Verdict.ASKS_FOR_ANSWER,
                mastery=3,
                turns_on_concept=9,
                has_been_taught=False,
                holds_misconception=True,
                prerequisite_available=True,
                wrong_on_concept=9,
            )
        )
        assert move is Move.ANSWER

    def test_a_correct_answer_is_reacted_to_before_anything_is_planned(self):
        move = plan_move(answered(Verdict.CORRECT, turns_on_concept=9, has_been_taught=False))
        assert move is Move.EVALUATE

    def test_a_wrong_answer_outranks_mastery_and_teaching(self):
        assert plan_move(answered(Verdict.WRONG, mastery=3)) is Move.HINT
        assert plan_move(answered(Verdict.WRONG, has_been_taught=False)) is Move.HINT

    def test_a_prerequisite_gap_outranks_hinting_at_this_concept(self):
        """§17. More of this concept cannot close a gap underneath it."""
        move = plan_move(
            answered(
                Verdict.WRONG,
                prerequisite_available=True,
                wrong_on_concept=STRUGGLES_BEFORE_STEP_BACK,
                holds_misconception=True,
            )
        )
        assert move is Move.STEP_BACK

    def test_one_wrong_answer_is_not_yet_a_prerequisite_gap(self):
        move = plan_move(
            answered(
                Verdict.WRONG,
                prerequisite_available=True,
                wrong_on_concept=STRUGGLES_BEFORE_STEP_BACK - 1,
            )
        )
        assert move is Move.HINT

    def test_a_named_misconception_outranks_the_hint_ladder(self):
        """§13. A hint scaffolds them past a wrong model without removing it."""
        move = plan_move(answered(Verdict.WRONG, holds_misconception=True))
        assert move is Move.CORRECT_MISCONCEPTION


class TestReactingToAnAnswer:
    """§8's EVALUATE stage: what the learner demonstrated drives the next move."""

    def test_a_correct_answer_below_mastery_confirms_and_continues(self):
        assert plan_move(answered(Verdict.CORRECT, mastery=1)) is Move.EVALUATE

    def test_a_correct_answer_at_mastery_advances(self):
        """§15. Mastery is the scale's call, not one answer's."""
        assert plan_move(answered(Verdict.CORRECT, mastery=MASTERED)) is Move.ADVANCE

    def test_a_conceptual_misunderstanding_is_retaught_rather_than_hinted(self):
        move = plan_move(answered(Verdict.WRONG, diagnosis=Diagnosis.CONCEPTUAL))
        assert move is Move.RETEACH

    def test_a_calculation_error_is_hinted_because_the_model_is_sound(self):
        move = plan_move(answered(Verdict.WRONG, diagnosis=Diagnosis.CALCULATION))
        assert move is Move.HINT

    def test_a_partial_answer_is_treated_as_a_miss(self):
        assert plan_move(answered(Verdict.PARTIAL)) is Move.HINT

    def test_an_exhausted_ladder_stops_hinting_and_reteaches(self):
        move = plan_move(answered(Verdict.WRONG, hints_available=3, hint_rung=3))
        assert move is Move.RETEACH

    def test_not_knowing_the_answer_is_scaffolded_rather_than_retaught(self):
        """§12. They could not recall one thing; that is what a hint is for."""
        assert plan_move(answered(Verdict.DONT_KNOW)) is Move.HINT

    def test_not_knowing_with_the_ladder_spent_reteaches(self):
        move = plan_move(answered(Verdict.DONT_KNOW, hints_available=3, hint_rung=3))
        assert move is Move.RETEACH

    def test_not_following_the_explanation_reteaches_rather_than_hints(self):
        """A hint about a question they never followed helps nobody."""
        move = plan_move(answered(Verdict.DONT_KNOW, confused=True))
        assert move is Move.RETEACH

    def test_a_non_answer_re_asks_the_question(self):
        move = plan_move(answered(Verdict.NOT_AN_ANSWER))
        assert move is Move.CHECK


class TestConfusion:
    """§14. 'I still don't understand' must not produce the same explanation."""

    def test_confusion_reteaches_even_with_no_question_outstanding(self):
        assert plan_move(snapshot(confused=True)) is Move.RETEACH

    def test_confusion_outranks_a_recap(self):
        """A recap is a reword. They have told us rewording is not the problem."""
        assert plan_move(snapshot(confused=True, turns_since_check=0)) is Move.RETEACH

    def test_confusion_steps_back_when_the_gap_is_underneath(self):
        move = plan_move(
            snapshot(
                confused=True,
                prerequisite_available=True,
                wrong_on_concept=STRUGGLES_BEFORE_STEP_BACK,
            )
        )
        assert move is Move.STEP_BACK

    def test_mastery_outranks_the_game_offer(self):
        assert plan_move(snapshot(mastery=MASTERED, turns_on_concept=99)) is Move.ADVANCE

    def test_the_game_offer_outranks_a_first_teach(self):
        move = plan_move(
            snapshot(turns_on_concept=TURNS_BEFORE_GAME, has_been_taught=False)
        )
        assert move is Move.GAME

    def test_teaching_outranks_checking(self):
        move = plan_move(snapshot(has_been_taught=False, turns_since_check=9))
        assert move is Move.TEACH


class TestEachMove:
    def test_an_untaught_concept_is_taught(self):
        assert plan_move(snapshot(has_been_taught=False, turns_on_concept=0)) is Move.TEACH

    def test_two_turns_without_a_check_asks_one(self):
        assert plan_move(snapshot(turns_since_check=TURNS_BEFORE_CHECK)) is Move.CHECK

    def test_one_turn_without_a_check_does_not(self):
        assert plan_move(snapshot(turns_since_check=TURNS_BEFORE_CHECK - 1)) is Move.RECAP

    def test_a_concept_with_no_check_bank_is_never_checked(self):
        """A CHECK turn on a concept with no items asks nothing at all."""
        move = plan_move(snapshot(turns_since_check=9, has_check_item=False))
        assert move is Move.RECAP

    def test_a_mastered_concept_advances(self):
        assert plan_move(snapshot(mastery=MASTERED)) is Move.ADVANCE

    def test_beyond_mastered_still_advances(self):
        """Scores above 3 should not fall through."""
        assert plan_move(snapshot(mastery=9)) is Move.ADVANCE


class TestGames:
    def test_only_child_bands_get_games(self):
        for band in ("5-8", "9-12", "13-15"):
            assert band_allows_games(band)
        for band in ("16-18", "adult"):
            assert not band_allows_games(band)

    def test_an_older_learner_is_taught_rather_than_offered_a_game(self):
        move = plan_move(
            snapshot(band="adult", turns_on_concept=99, has_been_taught=False)
        )
        assert move is Move.TEACH

    @pytest.mark.parametrize("band", sorted(GAME_BANDS))
    def test_a_child_band_gets_the_game(self, band):
        assert plan_move(snapshot(band=band, turns_on_concept=TURNS_BEFORE_GAME)) is Move.GAME


class TestTheHintLadder:
    """§12. Assistance increases with what the learner has shown."""

    def test_the_rung_climbs_from_the_one_already_given(self):
        assert hint_level(snapshot(hint_rung=0, hints_available=3)) == 1
        assert hint_level(snapshot(hint_rung=1, hints_available=3)) == 2
        assert hint_level(snapshot(hint_rung=2, hints_available=3)) == 3

    def test_the_rung_is_capped_at_what_the_author_wrote(self):
        """Asking for rung 3 of a two-rung ladder invents a hint."""
        assert hint_level(snapshot(hint_rung=9, hints_available=2)) == 2

    def test_the_rung_is_capped_globally(self):
        assert hint_level(snapshot(hint_rung=9, hints_available=99)) == MAX_HINT_LEVEL

    def test_the_rung_is_at_least_one(self):
        assert hint_level(snapshot(hint_rung=0, hints_available=0)) == 1

    def test_the_ladder_reports_when_it_is_exhausted(self):
        assert not exhausted_ladder(snapshot(hint_rung=2, hints_available=3))
        assert exhausted_ladder(snapshot(hint_rung=3, hints_available=3))

    def test_a_question_with_no_authored_hints_exhausts_after_one_rung(self):
        """Otherwise the ladder would run forever on an empty bank."""
        assert exhausted_ladder(snapshot(hint_rung=1, hints_available=0))


class TestFromState:
    def test_it_reads_the_graph_state_shape(self):
        concept = TeachingConcept(
            id="CON-0007",
            slug="interest",
            locale="en",
            title="Interest",
            domain="saving",
            band_min="9-12",
            band_max="adult",
            bodies={"9-12": "body"},
            check_bank=(
                CheckItem(id="chk_1", band="9_12", type="numeric", question="q?", answer="4"),
            ),
        )
        learning = {
            "awaiting_check_answer": True,
            "consecutive_wrong": 2,
            "turns_on_concept": {"CON-0007": 3},
            "turns_since_check": 1,
            "concepts_touched": ["CON-0007"],
        }
        snap = LearnerSnapshot.from_state(learning, band="9-12", concept=concept, mastery=2)

        assert snap.concept_id == "CON-0007"
        assert snap.awaiting_check_answer
        assert snap.consecutive_wrong == 2
        assert snap.turns_on_concept == 3
        assert snap.has_been_taught
        assert snap.has_check_item
        assert snap.mastery == 2

    def test_an_empty_state_is_a_fresh_learner(self):
        snap = LearnerSnapshot.from_state({}, band="5-8", concept=None)
        assert snap.mastery == 0
        assert not snap.has_been_taught
        assert not snap.awaiting_check_answer
        assert plan_move(snap) is Move.TEACH

    def test_a_concept_with_no_bank_reports_no_check_item(self):
        concept = TeachingConcept(
            id="CON-0009",
            slug="x",
            locale="en",
            title="X",
            domain="saving",
            band_min="5-8",
            band_max="adult",
            bodies={"5-8": "body"},
        )
        snap = LearnerSnapshot.from_state({}, band="5-8", concept=concept)
        assert not snap.has_check_item


class TestExhaustively:
    """Every reachable combination, walked."""

    def test_no_combination_raises_and_all_return_a_move(self):
        bands = ("5-8", "9-12", "13-15", "16-18", "adult")
        verdicts = (None, *Verdict)
        space = itertools.product(
            bands,
            range(0, 5),          # mastery, including the impossible 4
            (False, True),        # awaiting_check_answer
            verdicts,
            tuple(Diagnosis),
            (False, True),        # holds_misconception
            (False, True),        # confused
            range(0, 3),          # wrong_on_concept
            (False, True),        # prerequisite_available
            range(0, 6),          # turns_on_concept
            range(0, 4),          # turns_since_check
            (False, True),        # has_been_taught
            (False, True),        # has_check_item
        )
        seen: set[Move] = set()
        count = 0
        for combination in space:
            move = plan_move(
                LearnerSnapshot(
                    band=combination[0],
                    concept_id="CON-0001",
                    mastery=combination[1],
                    awaiting_check_answer=combination[2],
                    verdict=combination[3],
                    diagnosis=combination[4],
                    holds_misconception=combination[5],
                    confused=combination[6],
                    wrong_on_concept=combination[7],
                    prerequisite_available=combination[8],
                    turns_on_concept=combination[9],
                    turns_since_check=combination[10],
                    has_been_taught=combination[11],
                    has_check_item=combination[12],
                    hints_available=3,
                )
            )
            assert isinstance(move, Move)
            seen.add(move)
            count += 1

        assert count == (
            5 * 5 * 2 * len(verdicts) * len(Diagnosis) * 2 * 2 * 3 * 2 * 6 * 4 * 2 * 2
        )
        # Every move is reachable. GAME needs a child band, which the product includes.
        assert seen == set(Move)

    def test_a_correct_answer_never_produces_a_remedial_move(self):
        """The one invariant worth stating separately: success is never punished."""
        remedial = {
            Move.HINT,
            Move.RETEACH,
            Move.CORRECT_MISCONCEPTION,
            Move.STEP_BACK,
        }
        for combination in itertools.product(
            range(0, 5),          # mastery
            tuple(Diagnosis),
            (False, True),        # holds_misconception
            (False, True),        # confused
            range(0, 3),          # wrong_on_concept
            (False, True),        # prerequisite_available
        ):
            move = plan_move(
                LearnerSnapshot(
                    concept_id="CON-0001",
                    awaiting_check_answer=True,
                    verdict=Verdict.CORRECT,
                    mastery=combination[0],
                    diagnosis=combination[1],
                    holds_misconception=combination[2],
                    confused=combination[3],
                    wrong_on_concept=combination[4],
                    prerequisite_available=combination[5],
                )
            )
            assert move not in remedial, combination


class TestTheQuizWaitsItsTurn:
    """What a check question is anchored to, and what it is not.

    A quiz may take a turn for two reasons: it is holding a question nobody has
    answered, or the learner asked to be tested. A timer counting elapsed turns
    is neither, and a nine-year-old who asked what saving is and was told to
    name a need rather than a want learns that the thing is not listening.
    """

    def _due_for_a_check(self, **overrides):
        """A learner mid-concept with the check timer already elapsed."""
        return LearnerSnapshot(
            concept_id="CON-0001",
            band="9-12",
            has_been_taught=True,
            has_check_item=True,
            turns_since_check=TURNS_BEFORE_CHECK + 1,
            **overrides,
        )

    def test_the_timer_asks_when_the_learner_brought_nothing(self):
        assert plan_move(self._due_for_a_check()) is Move.CHECK

    def test_a_question_of_their_own_outranks_the_timer(self):
        move = plan_move(self._due_for_a_check(asked_their_own=True))
        assert move is not Move.CHECK, (
            "The learner asked something. Answering with a new quiz question is "
            "how 'Here's another money question' ends up replying to 'teach me "
            "about saving'."
        )

    def test_their_turn_is_still_answered(self):
        """Standing the timer down must not end the turn in silence."""
        move = plan_move(self._due_for_a_check(asked_their_own=True))
        assert move in EXPLAINING_MOVES

    def test_an_outstanding_check_still_owns_the_turn(self):
        """The real anchor is untouched: an unanswered question is re-asked."""
        move = plan_move(
            LearnerSnapshot(
                concept_id="CON-0001",
                has_been_taught=True,
                has_check_item=True,
                awaiting_check_answer=True,
                asked_their_own=True,
            )
        )
        assert move is Move.CHECK

    def test_asking_to_practise_still_gets_a_question(self):
        """§10's case is a request, not a timer, so the anchor leaves it alone."""
        move = plan_move(self._due_for_a_check(wants_practice=True, asked_their_own=True))
        assert move is Move.CHECK
