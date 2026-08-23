"""One rung fires per turn, and rung six is most of them.

WHAT THIS FILE IS GUARDING
    Not that the suggester suggests. That is the easy half. It is guarding the
    turns where it must NOT: a form, a game result, a reader already holding an
    offer, a reader who is stuck. A suggester that always suggests is a nag, and
    the reader closes the tab rather than complaining about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.learning.mastery import MAX_SCORE, MasteryRow
from app.pathway.suggest import MAX_CHIP_WORDS, Rung, next_step

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
NAMES = {"save": "saving", "spend": "spending", "goal": "goals", "budget": "budgets"}


@dataclass(frozen=True)
class FakeLesson:
    id: str
    concept_id: str
    suggested_widget_kind: str | None = None


LESSONS = [
    FakeLesson("l_save", "save", "allocator"),
    FakeLesson("l_spend", "spend"),
    FakeLesson("l_goal", "goal", "allocator"),
]


def row(concept_id, **kwargs):
    base = {"score": 0, "attempts": 1, "last_seen": NOW - timedelta(days=1)}
    return MasteryRow(concept_id=concept_id, **{**base, **kwargs})


def state(**kwargs):
    return {"safety_flags": {}, "concepts_touched": [], **kwargs}


class TestTheTurnsThatTakeNoSuggestion:
    """Every one of these already has a job. Rung six, unconditionally."""

    @pytest.mark.parametrize(
        "flag", ["card", "widget_interaction", "game_result"]
    )
    def test_a_turn_that_is_already_something_gets_nothing(self, flag):
        assert (
            next_step(
                state(safety_flags={flag: True}),
                mastery=[row("save", wrong_streak=2)],
                lessons=LESSONS,
                concept_names=NAMES,
                now=NOW,
            )
            is None
        )

    def test_a_reader_already_holding_a_video_offer_gets_nothing(self):
        """Two offers on one turn is the assistant talking over itself."""
        assert (
            next_step(
                state(offered_video="captain-careful-scarcity"),
                mastery=[row("save", wrong_streak=2)],
                lessons=LESSONS,
                concept_names=NAMES,
                now=NOW,
            )
            is None
        )

    def test_never_twice_running(self):
        assert (
            next_step(
                state(suggested_step="l_save"),
                mastery=[row("save", wrong_streak=2)],
                lessons=LESSONS,
                concept_names=NAMES,
                now=NOW,
            )
            is None
        )


class TestRungOneComesFirst:
    """Moving a stuck reader forward is the one suggestion that makes it worse."""

    def test_a_stuck_concept_beats_everything_below_it(self):
        result = next_step(
            state(),
            mastery=[
                row("save", wrong_streak=2),
                row("spend", next_due=NOW - timedelta(days=9)),
                row("goal", widget_touches=5),
            ],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is not None
        assert result.rung is Rung.STUCK
        assert result.concept_id == "save"

    def test_one_wrong_answer_is_not_stuck(self):
        """Everybody gets one wrong. Reacting to it is hovering."""
        result = next_step(
            state(),
            mastery=[row("save", wrong_streak=1)],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is None or result.rung is not Rung.STUCK

    def test_the_most_recent_stumble_wins(self):
        result = next_step(
            state(),
            mastery=[
                row("save", wrong_streak=3, last_seen=NOW - timedelta(days=6)),
                row("goal", wrong_streak=2, last_seen=NOW - timedelta(minutes=2)),
            ],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is not None and result.concept_id == "goal", (
            "the one they are still holding, not the most overdue"
        )


class TestRungTwoIsSpacedRepetition:
    def test_the_most_overdue_comes_back_first(self):
        result = next_step(
            state(),
            mastery=[
                row("save", score=2, next_due=NOW - timedelta(days=1)),
                row("spend", score=1, next_due=NOW - timedelta(days=8)),
            ],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is not None
        assert result.rung is Rung.DUE_FOR_REVIEW
        assert result.concept_id == "spend"

    def test_nothing_due_yet_is_not_offered(self):
        result = next_step(
            state(),
            mastery=[row("save", score=2, next_due=NOW + timedelta(days=6))],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is None or result.rung is not Rung.DUE_FOR_REVIEW

    def test_something_covered_this_session_is_not_re_offered(self):
        """Re-offering it reads as the assistant not having noticed."""
        result = next_step(
            state(concepts_touched=["spend"]),
            mastery=[row("spend", score=1, next_due=NOW - timedelta(days=8))],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is None or result.concept_id != "spend"


class TestRungThreeIsObservedNotAsked:
    def test_a_reader_who_uses_the_widgets_is_offered_one(self):
        result = next_step(
            state(),
            mastery=[row("save", widget_touches=4, next_due=NOW + timedelta(days=6))],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is not None
        assert result.rung is Rung.HANDS_ON
        assert result.lesson_id == "l_save"

    def test_one_touch_is_not_a_preference(self):
        result = next_step(
            state(),
            mastery=[row("save", widget_touches=1, next_due=NOW + timedelta(days=6))],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is None or result.rung is not Rung.HANDS_ON

    def test_it_does_not_offer_a_widget_on_something_already_mastered(self):
        result = next_step(
            state(),
            mastery=[
                MasteryRow(
                    concept_id="save",
                    score=MAX_SCORE,
                    widget_touches=4,
                    next_due=NOW + timedelta(days=21),
                )
            ],
            lessons=[LESSONS[0]],
            concept_names=NAMES,
            now=NOW,
        )
        assert result is None or result.concept_id != "save"


class TestRungFourIsCourseOrder:
    def test_it_offers_the_next_unmastered_lesson(self):
        result = next_step(
            state(),
            mastery=[
                MasteryRow(
                    concept_id="save",
                    score=MAX_SCORE,
                    next_due=NOW + timedelta(days=21),
                )
            ],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is not None
        assert result.rung is Rung.CONTINUE
        assert result.concept_id == "spend"

    def test_everything_mastered_is_silence_not_a_repeat(self):
        result = next_step(
            state(),
            mastery=[
                MasteryRow(
                    concept_id=lesson.concept_id,
                    score=MAX_SCORE,
                    next_due=NOW + timedelta(days=21),
                )
                for lesson in LESSONS
            ],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is None


class TestRungFiveIsTheFirstVisit:
    def test_a_learner_with_no_history_is_invited_once(self):
        result = next_step(state(), mastery=[], lessons=LESSONS, now=NOW)
        assert result is not None
        assert result.rung is Rung.START
        assert result.lesson_id == "l_save"

    def test_with_no_lessons_there_is_nothing_to_start(self):
        assert next_step(state(), mastery=[], lessons=[], now=NOW) is None


class TestRungSixIsTheUsualAnswer:
    def test_no_inputs_at_all_is_silence(self):
        """`safety_out` calls this on every turn, including ones with no learner."""
        assert next_step(state(), now=NOW) is None

    def test_mastery_without_lessons_does_not_invent_one(self):
        assert (
            next_step(
                state(),
                mastery=[row("save", score=1, next_due=NOW + timedelta(days=6))],
                lessons=None,
                concept_names=NAMES,
                now=NOW,
            )
            is None
        )


class TestTheChipSurvivesTheWire:
    """A chip is also what gets SENT when it is tapped."""

    @pytest.mark.parametrize(
        ("mastery", "lessons"),
        [
            ([row("save", wrong_streak=2)], LESSONS),
            ([row("spend", next_due=NOW - timedelta(days=8))], LESSONS),
            ([row("save", widget_touches=4, next_due=NOW + timedelta(days=9))], LESSONS),
            ([], LESSONS),
        ],
    )
    def test_every_rung_fits_the_chip_budget(self, mastery, lessons):
        result = next_step(
            state(), mastery=mastery, lessons=lessons, concept_names=NAMES, now=NOW
        )
        if result is not None:
            assert 1 <= len(result.chip.split()) <= MAX_CHIP_WORDS

    def test_a_concept_with_no_short_name_declines_rather_than_overflowing(self):
        result = next_step(
            state(),
            mastery=[row("save", wrong_streak=2)],
            lessons=LESSONS,
            concept_names={"save": "the difference between needs and wants"},
            now=NOW,
        )
        assert result is None or result.rung is not Rung.STUCK


class TestEveryAnswerCanBeExplained:
    def test_a_suggestion_says_why_it_was_made(self):
        """The client will ask why a chip appeared. So will a log."""
        result = next_step(
            state(),
            mastery=[row("save", wrong_streak=2)],
            lessons=LESSONS,
            concept_names=NAMES,
            now=NOW,
        )
        assert result is not None and result.why
        assert "save" in result.why


class TestItIsOffUntilSomebodyDecidesOtherwise:
    def test_the_flag_defaults_to_off(self):
        """Judging week is the wrong time to start putting new chips on screen.

        The function is written, tested and wired. Turning it on is one env var
        and a client conversation, which is the order those two belong in.
        """
        from app.config import Settings

        assert Settings().pathway_suggestions_enabled is False

    def test_safety_out_asks_for_nothing_while_it_is_off(self, monkeypatch):
        """Not merely no chip -- no mastery read either.

        This runs on the path of every reply, so a flag that still costs a
        database round trip is a flag that is not really off.
        """
        import asyncio

        from app.graph.nodes import safety_out as module

        def explode(*_args, **_kwargs):  # pragma: no cover - must not run
            raise AssertionError("the store was read while the flag was off")

        monkeypatch.setattr("app.learning.mastery.MasteryStore.all_for", explode)
        result = asyncio.run(
            module._pathway_step({"user_id": "u1", "age_band": "9-12"})
        )
        assert result is None
