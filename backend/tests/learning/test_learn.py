"""The lesson machine, the hint ladder, explain-it-back, and the mastery scale."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from langchain_core.messages import HumanMessage  # noqa: E402

from app.agents.learn.graph import build_learn_graph, grade_answer  # noqa: E402
from app.agents.learn.nodes import explain_back as eb  # noqa: E402
from app.agents.learn.nodes import hint_ladder as hl  # noqa: E402
from app.agents.learn.state import MAX_ATTEMPTS  # noqa: E402
from app.curriculum.schema import load_all  # noqa: E402
from app.graph.state import initial_state  # noqa: E402
from app.learning import scheduler  # noqa: E402
from app.learning.mastery import (  # noqa: E402
    Evidence,
    MasteryRow,
    MasteryStore,
    apply,
    due_after,
    is_due,
)

NOW = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def curriculum():
    return load_all(refresh=True)


@pytest.fixture
def store():
    return MasteryStore()


@pytest.fixture
def lesson_graph(curriculum, store):
    return build_learn_graph(curriculum=curriculum, store=store)


def state_for(message: str, band: str = "9-12", **overrides):
    state = initial_state(
        session_id="s-learn",
        user_id="u-learn",
        device_id="d",
        persona="stella",
        age_band=band,
        account_status="beneficiary",
    )
    state["messages"] = [HumanMessage(content=message)]
    state["active_agent"] = "learn_agent"
    state.update(overrides)
    return state


async def reply(graph, state, text: str):
    """Send one child turn into the machine and return the new state."""
    state = dict(state)
    state["messages"] = list(state["messages"]) + [HumanMessage(content=text)]
    return await graph.ainvoke(state)


# ── the mastery scale ────────────────────────────────────────────────────────


class TestMasteryTransitions:
    def test_a_widget_only_learner_never_exceeds_one(self):
        """The acceptance criterion, and the rule the scale exists to hold."""
        row = MasteryRow(concept_id="save")
        for _ in range(40):
            row = apply(row, Evidence.WIDGET, now=NOW)
        assert row.score == 1
        assert row.widget_touches == 40

    def test_a_widget_does_not_drag_a_higher_score_back_down(self):
        """The same bug in the opposite direction."""
        row = MasteryRow(concept_id="save", score=3)
        assert apply(row, Evidence.WIDGET, now=NOW).score == 3

    def test_a_game_is_exposure_too(self):
        """A game score mixes understanding, reading speed and luck."""
        row = MasteryRow(concept_id="save")
        for _ in range(10):
            row = apply(row, Evidence.GAME, now=NOW)
        assert row.score == 1

    def test_correct_with_no_hints_moves_up_one(self):
        row = apply(MasteryRow(concept_id="save"), Evidence.CORRECT, now=NOW)
        assert row.score == 1
        assert apply(row, Evidence.CORRECT, now=NOW).score == 2

    def test_correct_after_hints_does_not_move(self):
        """They arrived, and they arrived with help. That is exposure."""
        row = MasteryRow(concept_id="save", score=2)
        after = apply(row, Evidence.CORRECT_AFTER_HINTS, now=NOW)
        assert after.score == 2
        assert after.hinted_attempts == 1

    def test_wrong_twice_costs_a_point_and_wrong_once_does_not(self):
        row = MasteryRow(concept_id="save", score=2)
        once = apply(row, Evidence.WRONG, now=NOW)
        assert once.score == 2
        twice = apply(once, Evidence.WRONG, now=NOW)
        assert twice.score == 1

    def test_the_floor_is_zero(self):
        row = MasteryRow(concept_id="save", score=0)
        for _ in range(6):
            row = apply(row, Evidence.WRONG, now=NOW)
        assert row.score == 0

    def test_a_correct_answer_clears_the_wrong_streak(self):
        row = apply(MasteryRow(concept_id="save", score=2), Evidence.WRONG, now=NOW)
        row = apply(row, Evidence.CORRECT, now=NOW)
        row = apply(row, Evidence.WRONG, now=NOW)
        assert row.score == 3  # one wrong since the last correct is not two

    def test_explaining_it_back_moves_up_and_caps_at_three(self):
        row = MasteryRow(concept_id="save", score=2)
        assert apply(row, Evidence.EXPLAINED, now=NOW).score == 3
        assert apply(
            MasteryRow(concept_id="save", score=3), Evidence.EXPLAINED, now=NOW
        ).score == 3

    @pytest.mark.asyncio
    async def test_the_store_reads_applies_and_writes(self, store):
        row = await store.record("learner-1", "save", Evidence.CORRECT, now=NOW)
        assert row.score == 1
        assert (await store.get("learner-1", "save")).score == 1


class TestSpacedRepetition:
    @pytest.mark.parametrize(
        ("score", "days"), [(0, 1), (1, 3), (2, 7), (3, 21)]
    )
    def test_the_intervals(self, score, days):
        assert due_after(score, NOW) == NOW + timedelta(days=days)

    def test_a_never_seen_concept_is_due(self):
        """What makes placement work without a separate "unseen" query."""
        assert is_due(MasteryRow(concept_id="save"), now=NOW)

    def test_a_concept_becomes_due_again_on_schedule(self):
        """The acceptance criterion."""
        row = apply(MasteryRow(concept_id="save"), Evidence.CORRECT, now=NOW)
        assert not is_due(row, now=NOW + timedelta(days=2))
        assert is_due(row, now=NOW + timedelta(days=3, seconds=1))

    def test_due_concepts_surface_most_overdue_first(self):
        rows = [
            MasteryRow(concept_id="a", next_due=NOW - timedelta(days=1)),
            MasteryRow(concept_id="b", next_due=NOW - timedelta(days=9)),
            MasteryRow(concept_id="c", next_due=NOW + timedelta(days=4)),
        ]
        assert scheduler.due_concepts(rows, now=NOW) == ["b", "a"]

    def test_an_unseen_concept_is_not_folded_in_as_review(self):
        """It is due in the PLACEMENT sense and `place` handles it."""
        assert scheduler.due_concepts([MasteryRow(concept_id="a")], now=NOW) == []

    def test_at_most_two_reviews_per_lesson(self):
        """Three revisited ideas in one check is a quiz, not a lesson."""
        rows = [
            MasteryRow(concept_id=str(index), next_due=NOW - timedelta(days=index + 1))
            for index in range(6)
        ]
        assert len(scheduler.due_concepts(rows, now=NOW)) == 2

    def test_the_lessons_own_concept_is_not_review(self):
        rows = [MasteryRow(concept_id="save", next_due=NOW - timedelta(days=1))]
        assert scheduler.due_concepts(rows, exclude={"save"}, now=NOW) == []


class TestPlacement:
    def test_a_new_learner_starts_at_the_first_lesson(self, curriculum):
        placement = scheduler.place(curriculum, "9-12", [], now=NOW)
        assert placement.lesson.id == "l01_what_is_saving"

    def test_a_mastered_lesson_is_skipped(self, curriculum):
        placement = scheduler.place(
            curriculum, "9-12", [MasteryRow(concept_id="save", score=3)], now=NOW
        )
        assert placement.lesson.id == "l02_spending_is_fine"

    def test_placement_follows_course_order_not_the_lowest_score(self, curriculum):
        """Curriculum order encodes prerequisites."""
        placement = scheduler.place(
            curriculum,
            "9-12",
            [MasteryRow(concept_id="budget", score=0), MasteryRow(concept_id="save", score=1)],
            now=NOW,
        )
        assert placement.lesson.id == "l01_what_is_saving"

    def test_an_interrupted_lesson_resumes_inside_the_window(self, curriculum):
        placement = scheduler.place(
            curriculum,
            "9-12",
            [],
            last_lesson_id="l03_a_goal",
            last_seen_at=NOW - timedelta(hours=10),
            now=NOW,
        )
        assert placement.resumed
        assert placement.lesson.id == "l03_a_goal"

    def test_it_does_not_resume_after_the_window(self, curriculum):
        """Outside 48 hours the setup is forgotten, and being dropped into the middle of an explanation is worse than st…"""
        placement = scheduler.place(
            curriculum,
            "9-12",
            [],
            last_lesson_id="l03_a_goal",
            last_seen_at=NOW - timedelta(days=5),
            now=NOW,
        )
        assert not placement.resumed
        assert placement.lesson.id == "l01_what_is_saving"

    def test_a_finished_course_is_a_real_outcome(self, curriculum):
        mastered = [
            MasteryRow(concept_id=concept, score=3) for concept in curriculum.concepts
        ]
        assert scheduler.place(curriculum, "9-12", mastered, now=NOW).lesson is None


class TestSessionLength:
    def test_a_lesson_that_finishes_early_ends_early(self):
        wrap, why = scheduler.should_wrap(
            NOW, at_natural_break=True, lesson_complete=True, now=NOW + timedelta(minutes=6)
        )
        assert wrap and why == "lesson complete"

    def test_it_never_ends_mid_explanation(self):
        """The rule: never cut off mid-explanation, whatever the clock says."""
        wrap, why = scheduler.should_wrap(
            NOW,
            at_natural_break=False,
            lesson_complete=False,
            now=NOW + timedelta(minutes=30),
        )
        assert not wrap and why == "mid-explanation"

    def test_it_wraps_at_the_first_break_past_the_soft_limit(self):
        wrap, _ = scheduler.should_wrap(
            NOW, at_natural_break=True, lesson_complete=False, now=NOW + timedelta(minutes=9)
        )
        assert wrap

    def test_it_does_not_wrap_before_the_soft_limit(self):
        wrap, _ = scheduler.should_wrap(
            NOW, at_natural_break=True, lesson_complete=False, now=NOW + timedelta(minutes=3)
        )
        assert not wrap

    def test_fifteen_minutes_is_the_ceiling(self):
        wrap, why = scheduler.should_wrap(
            NOW, at_natural_break=True, lesson_complete=False, now=NOW + timedelta(minutes=16)
        )
        assert wrap and why == "hard limit"


class TestStreaks:
    def test_two_sessions_in_one_day_are_one_day(self):
        assert scheduler.streak_after(4, NOW, now=NOW + timedelta(hours=3)) == 4

    def test_a_consecutive_day_extends_it(self):
        assert scheduler.streak_after(4, NOW, now=NOW + timedelta(days=1)) == 5

    def test_a_gap_resets_to_one_not_to_zero(self):
        """Today's session did happen. Showing a zero for it would be a lie."""
        assert scheduler.streak_after(9, NOW, now=NOW + timedelta(days=4)) == 1

    def test_a_first_session_is_one(self):
        assert scheduler.streak_after(0, None, now=NOW) == 1


# ── the hint ladder ──────────────────────────────────────────────────────────


class TestHintLadder:
    def test_three_wrong_answers_produce_nudge_narrow_reveal_and_no_fourth(
        self, curriculum
    ):
        """The acceptance criterion, stated exactly."""
        question = curriculum.lessons["l01_what_is_saving"].check_questions[0]

        first = hl.hint_for(question, "9-12", 1)
        second = hl.hint_for(question, "9-12", 2)
        third = hl.hint_for(question, "9-12", 3)

        assert (first.rung, second.rung, third.rung) == (hl.NUDGE, hl.NARROW, hl.REVEAL)
        assert not first.reveals and not second.reveals and third.reveals
        # There is no fourth rung to ask for.
        assert hl.hint_for(question, "9-12", 9).rung == hl.REVEAL

    def test_the_reveal_arrives_after_two_helped_failures(self):
        """Nudge, narrow, reveal. Two failures *after* being helped is the cap."""
        assert MAX_ATTEMPTS == 3

    def test_rung_two_narrows_to_exactly_two_options(self, curriculum):
        question = curriculum.lessons["l01_what_is_saving"].check_questions[0]
        hint = hl.hint_for(question, "9-12", 2)
        assert len(hint.options) == 2
        assert question.options[question.answer] in hint.options

    def test_a_free_text_question_narrows_nothing_rather_than_inventing_options(
        self, curriculum
    ):
        question = curriculum.lessons["l01_what_is_saving"].check_questions[1]
        assert hl.narrow_options(question) == []

    @pytest.mark.parametrize(
        "text",
        [
            "Wrong. Try again.",
            "That is incorrect.",
            "No. Think harder.",
            "Nope!",
            "✗ not that one",
            "X",
            "That was a mistake.",
            "Sorry, that failed.",
        ],
    )
    def test_a_verdict_is_detected(self, text):
        assert hl.contains_negative(text)

    @pytest.mark.parametrize(
        "text",
        [
            "A plan with no enjoyment in it is a plan you abandon.",
            "Was that a bad thing to do?",
            "There is no single right answer here.",
            "Think about where the money goes first.",
        ],
    )
    def test_an_ordinary_sentence_with_a_negation_in_it_is_not_a_verdict(self, text):
        """Banning "no" outright would flag real sentences and `sanitise` would then delete the word, leaving the opposi…"""
        assert not hl.contains_negative(text)

    def test_sanitising_leaves_a_readable_sentence(self):
        assert hl.sanitise("Wrong! Think about the coin.") == "Think about the coin."
        assert hl.sanitise("✗ Incorrect, try the other one") == "try the other one"

    def test_sanitising_does_not_delete_an_innocent_negation(self):
        text = "A plan with no enjoyment is a plan you abandon."
        assert hl.sanitise(text) == text

    def test_a_question_with_no_authored_hints_still_gets_three(self, curriculum, caplog):
        from app.curriculum.schema import CheckQuestion

        question = CheckQuestion(
            id="q_bare", prompt={"9-12": "?"}, options=["a", "b"], answer=0
        )
        with caplog.at_level("INFO"):
            rungs = hl.rungs_for(question, "9-12")
        assert len(rungs) == 3
        assert "generic ladder" in caplog.text


# ── explain-it-back ──────────────────────────────────────────────────────────


class TestExplainBack:
    ACCEPT = ["keep", "later", "save", "not spend", "put away"]

    def test_a_misspelled_answer_is_accepted_whole(self):
        """No spelling correction. Not gently, not in passing."""
        result = eb.grade("yu kepp the muny for latr", self.ACCEPT)
        assert result.accepted

    def test_spoken_filler_is_read_as_speech(self):
        """Bands 5-8 and 9-12 answer by voice. A transcript is messy."""
        assert eb.grade("um, i think, um, you keep it?", self.ACCEPT).accepted

    def test_one_concept_word_is_enough(self):
        """The threshold is low on purpose."""
        assert eb.grade("save", self.ACCEPT).accepted

    def test_a_thin_answer_is_built_on_rather_than_graded(self):
        result = eb.grade("keep", self.ACCEPT)
        assert result.accepted and result.partial
        reply = eb.response_for(result, "9-12")
        assert "?" in reply  # a follow-up, not a mark

    def test_i_dont_know_is_not_a_wrong_answer(self):
        """A child asking for help has already asked for the hint."""
        for text in ["I don't know", "idk", "dunno", "no idea", "?"]:
            assert eb.grade(text, self.ACCEPT).no_attempt

    def test_an_unrelated_answer_is_offered_the_words_not_marked_down(self):
        result = eb.grade("purple elephants", self.ACCEPT)
        assert not result.accepted
        reply = eb.response_for(result, "9-12")
        assert not hl.contains_negative(reply)
        assert "keeping money" in reply

    def test_the_reply_quotes_the_child_back(self):
        """"Well done!" is a noise. Quoting is somebody having listened."""
        result = eb.grade("you keep the money for later", self.ACCEPT)
        assert "keep" in eb.response_for(result, "9-12")

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15"])
    def test_no_reply_ever_contains_a_verdict(self, band):
        for answer in ["keep it", "keep", "purple", "idk", ""]:
            result = eb.grade(answer, self.ACCEPT)
            assert not hl.contains_negative(eb.response_for(result, band))


# ── grading a check answer ───────────────────────────────────────────────────


class TestGradeAnswer:
    def test_a_tapped_chip_is_graded_by_its_text(self, curriculum):
        question = curriculum.lessons["l01_what_is_saving"].check_questions[0]
        assert grade_answer(question, "Saving")
        assert not grade_answer(question, "Spending")

    def test_case_and_surrounding_words_do_not_matter(self, curriculum):
        question = curriculum.lessons["l01_what_is_saving"].check_questions[0]
        assert grade_answer(question, "i think it is saving!")

    def test_an_empty_answer_is_not_correct(self, curriculum):
        question = curriculum.lessons["l01_what_is_saving"].check_questions[0]
        assert not grade_answer(question, "   ")

    def test_grading_is_deterministic_not_a_model_call(self, curriculum):
        """A rung count only means something if "wrong" is decided identically every time."""
        question = curriculum.lessons["l01_what_is_saving"].check_questions[0]
        assert all(grade_answer(question, "Saving") for _ in range(20))


# ── the whole machine ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTheLessonRuns:
    async def test_a_full_lesson_teach_check_correct_mastery_next(
        self, lesson_graph, store
    ):
        """The acceptance criterion."""
        first = await lesson_graph.ainvoke(state_for("teach me about saving"))
        assert first["learning"]["phase"] == "checking"
        assert first["learning"]["lesson_id"] == "l01_what_is_saving"
        assert first["quick_replies"] == ["Saving", "Spending"]

        second = await reply(lesson_graph, first, "Saving")
        assert second["learning"]["phase"] == "explaining_back"

        third = await reply(lesson_graph, second, "you keep the money for later")
        rows = await store.all_for("u-learn")
        assert any(row.concept_id == "save" and row.score > 0 for row in rows)
        assert third["learning"]["phase"] in ("placing", "wrapping", "done")

    async def test_a_wrong_answer_runs_the_hint_ladder(self, lesson_graph):
        """The acceptance criterion."""
        first = await lesson_graph.ainvoke(state_for("teach me about saving"))
        second = await reply(lesson_graph, first, "Spending")

        assert second["learning"]["hint_rung"] == hl.NUDGE
        assert not hl.contains_negative(second["messages"][-1].content)

    async def test_a_second_wrong_answer_narrows_then_reveals(self, lesson_graph):
        state = await lesson_graph.ainvoke(state_for("teach me about saving"))
        first_lesson = state["learning"]["lesson_id"]

        state = await reply(lesson_graph, state, "Spending")
        assert state["learning"]["hint_rung"] == hl.NUDGE

        state = await reply(lesson_graph, state, "Spending")
        assert state["learning"]["hint_rung"] == hl.NARROW

        state = await reply(lesson_graph, state, "Spending")
        # The reveal ENDS the question.
        assert state["learning"]["lesson_id"] != first_lesson
        assert state["learning"]["attempts"] == 0

    async def test_no_negative_word_appears_anywhere_in_a_failed_run(
        self, lesson_graph
    ):
        """The acceptance criterion: no negative word in any output."""
        state = await lesson_graph.ainvoke(state_for("teach me about saving"))
        said: list[str] = []
        for _ in range(3):
            state = await reply(lesson_graph, state, "Spending")
            said.append(state["messages"][-1].content)
        for text in said:
            assert not hl.contains_negative(text), text

    async def test_every_speaking_node_offers_chips(self, lesson_graph):
        """Tap-not-type is the mode, and it is generated rather than re-prompted."""
        state = await lesson_graph.ainvoke(state_for("teach me about saving", band="5-8"))
        assert state["quick_replies"]
        state = await reply(lesson_graph, state, "Spending")
        assert state["quick_replies"]

    async def test_an_off_topic_question_is_answered_and_steered_back(
        self, lesson_graph
    ):
        """The acceptance criterion."""
        state = await lesson_graph.ainvoke(state_for("teach me about saving"))
        state["safety_flags"] = {"off_topic": True}
        state = await reply(lesson_graph, state, "what is a dinosaur")

        text = state["messages"][-1].content
        assert "back to" in text.lower()
        assert state["learning"]["digression_count"] == 1
        # NOT an attempt. Curiosity must not run the hint ladder.
        assert state["learning"]["attempts"] == 0

    async def test_two_digressions_then_the_line_is_held_warmly(self, lesson_graph):
        state = await lesson_graph.ainvoke(state_for("teach me about saving"))
        for _ in range(3):
            state["safety_flags"] = {"off_topic": True}
            state = await reply(lesson_graph, state, "what is a dinosaur")

        assert state["learning"]["digression_count"] == 3
        text = state["messages"][-1].content
        assert not hl.contains_negative(text)
        assert "hold that one" in text or "keep it for the end" in text

    async def test_an_on_topic_turn_resets_the_digression_run(self, lesson_graph):
        state = await lesson_graph.ainvoke(state_for("teach me about saving"))
        state["safety_flags"] = {"off_topic": True}
        state = await reply(lesson_graph, state, "what is a dinosaur")
        assert state["learning"]["digression_count"] == 1

        state["safety_flags"] = {}
        state = await reply(lesson_graph, state, "Saving")
        assert state["learning"]["digression_count"] == 0

    async def test_a_five_to_eight_gets_the_five_to_eight_lessons_only(
        self, lesson_graph, curriculum
    ):
        state = await lesson_graph.ainvoke(state_for("teach me", band="5-8"))
        allowed = {lesson.id for lesson in curriculum.lessons_for_band("5-8")}
        assert state["learning"]["lesson_id"] in allowed
