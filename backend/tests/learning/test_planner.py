"""`plan_move` is pure, its state space is small, and it is walked exhaustively."""

from __future__ import annotations

import itertools

import pytest

from app.agents.learn.planner import (
    GAME_BANDS,
    MASTERED,
    MAX_HINT_LEVEL,
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


class TestPrecedence:
    """The order of the tests in `plan_move` IS the pedagogy. Each is pinned."""

    def test_an_outstanding_check_outranks_everything(self):
        # Every other condition set to something that would win on its own.
        move = plan_move(
            snapshot(
                awaiting_check_answer=True,
                consecutive_wrong=2,
                mastery=3,
                turns_on_concept=9,
                has_been_taught=False,
            )
        )
        assert move is Move.EVALUATE

    def test_a_wrong_answer_outranks_mastery_and_teaching(self):
        assert plan_move(snapshot(consecutive_wrong=1, mastery=3)) is Move.HINT
        assert plan_move(snapshot(consecutive_wrong=1, has_been_taught=False)) is Move.HINT

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
    def test_the_rung_follows_the_miss_count(self):
        assert hint_level(snapshot(consecutive_wrong=1)) == 1
        assert hint_level(snapshot(consecutive_wrong=2)) == 2
        assert hint_level(snapshot(consecutive_wrong=3)) == 3

    def test_the_rung_is_capped(self):
        """There is no fourth rung."""
        assert hint_level(snapshot(consecutive_wrong=9)) == MAX_HINT_LEVEL

    def test_the_rung_is_at_least_one(self):
        assert hint_level(snapshot(consecutive_wrong=0)) == 1

    def test_the_ladder_reports_when_it_is_exhausted(self):
        assert not exhausted_ladder(snapshot(consecutive_wrong=MAX_HINT_LEVEL))
        assert exhausted_ladder(snapshot(consecutive_wrong=MAX_HINT_LEVEL + 1))


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
        space = itertools.product(
            bands,
            range(0, 5),          # mastery, including the impossible 4
            (False, True),        # awaiting_check_answer
            range(0, 5),          # consecutive_wrong
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
                    consecutive_wrong=combination[3],
                    turns_on_concept=combination[4],
                    turns_since_check=combination[5],
                    has_been_taught=combination[6],
                    has_check_item=combination[7],
                )
            )
            assert isinstance(move, Move)
            seen.add(move)
            count += 1

        assert count == 5 * 5 * 2 * 5 * 6 * 4 * 2 * 2
        # Every move but GAME works from any band, and the product covers GAME's child band.
        assert seen == set(Move)
