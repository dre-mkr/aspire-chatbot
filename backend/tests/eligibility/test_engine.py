"""The flow: navigation, persistence of answers, and what survives a finish."""

from __future__ import annotations

import pytest

from app.eligibility.engine import (
    CheckAlreadyRunning,
    CheckNotRunning,
    EligibilityEngine,
    UnknownAnswer,
)
from app.eligibility.models import Language, Verdict
from app.eligibility.store import InMemorySessionStore

THREAD = "thread-1"


def walk(engine: EligibilityEngine, answers: dict[str, str], language=Language.EN):
    """Run the flow to its end, answering by question id. Returns the result."""
    snapshot = engine.start(THREAD, language)
    while snapshot.question is not None:
        snapshot = engine.answer(THREAD, answers[snapshot.question.id])
    assert snapshot.result is not None
    return snapshot.result


CLEAN = {
    "age": "5to18",
    "citizenship": "born_skn",
    "residence": "st_kitts",
    "school": "in_school",
    "registrant": "guardian",
}


def test_a_fresh_check_opens_on_the_first_question(engine: EligibilityEngine):
    snapshot = engine.start(THREAD)
    assert snapshot.question is not None
    assert snapshot.question.id == "age"
    assert snapshot.question.position == 1
    assert snapshot.question.total == 5
    assert snapshot.question.can_go_back is False
    assert snapshot.result is None


def test_two_checks_cannot_run_in_one_conversation(engine: EligibilityEngine):
    engine.start(THREAD)
    with pytest.raises(CheckAlreadyRunning):
        engine.start(THREAD)


def test_answering_without_starting_is_declined(engine: EligibilityEngine):
    with pytest.raises(CheckNotRunning):
        engine.answer(THREAD, "5to18")


def test_an_option_nobody_could_have_tapped_is_refused(engine: EligibilityEngine):
    """The closed option set is what stops a crafted request steering a verdict."""
    engine.start(THREAD)
    with pytest.raises(UnknownAnswer):
        engine.answer(THREAD, "definitely_eligible")


def test_the_progress_indicator_does_not_grow_while_you_answer_it(
    engine: EligibilityEngine,
):
    """`age_exact` is a follow-up to question 1, not a sixth step.

    Counting it made the card read "1 of 5" and then "2 of 6" the moment
    somebody tapped "Under 5".
    """
    snapshot = engine.start(THREAD)
    assert snapshot.question.total == 5
    snapshot = engine.answer(THREAD, "under5")
    assert snapshot.question.id == "age_exact"
    assert snapshot.question.position == 1
    assert snapshot.question.total == 5


def test_back_preserves_the_answer_already_given(engine: EligibilityEngine):
    engine.start(THREAD)
    engine.answer(THREAD, "5to18")
    snapshot = engine.answer(THREAD, "born_skn")
    assert snapshot.question.id == "residence"

    snapshot = engine.back(THREAD)
    assert snapshot.question.id == "citizenship"
    assert snapshot.question.answered_with == "born_skn"

    snapshot = engine.back(THREAD)
    assert snapshot.question.id == "age"
    assert snapshot.question.answered_with == "5to18"


def test_back_from_the_first_question_is_a_no_op_not_an_error(
    engine: EligibilityEngine,
):
    engine.start(THREAD)
    snapshot = engine.back(THREAD)
    assert snapshot.question.id == "age"


def test_going_back_and_changing_the_age_drops_the_stranded_follow_up(
    engine: EligibilityEngine,
):
    """Leaving the under-5 branch must not keep an answer to a question that is
    no longer being asked."""
    engine.start(THREAD)
    engine.answer(THREAD, "under5")
    engine.answer(THREAD, "3")
    engine.back(THREAD)  # back to age_exact
    snapshot = engine.back(THREAD)  # back to age
    assert snapshot.question.id == "age"

    snapshot = engine.answer(THREAD, "5to18")
    assert snapshot.question.id == "citizenship"

    result = walk_from_here(engine)
    assert result.reminder_year is None


def walk_from_here(engine: EligibilityEngine):
    remaining = {"citizenship": "born_skn", "residence": "nevis", "school": "in_school", "registrant": "self"}
    snapshot = engine.state(THREAD)
    while snapshot is not None and snapshot.question is not None:
        snapshot = engine.answer(THREAD, remaining[snapshot.question.id])
    assert snapshot is not None and snapshot.result is not None
    return snapshot.result


def test_changing_the_age_forward_again_inserts_the_follow_up(
    engine: EligibilityEngine,
):
    engine.start(THREAD)
    engine.answer(THREAD, "5to18")
    engine.back(THREAD)
    snapshot = engine.answer(THREAD, "under5")
    assert snapshot.question.id == "age_exact"


def test_a_refresh_mid_flow_finds_the_flow_where_it_was(engine: EligibilityEngine):
    engine.start(THREAD)
    engine.answer(THREAD, "5to18")
    engine.answer(THREAD, "born_skn")

    restored = engine.state(THREAD)
    assert restored is not None
    assert restored.question is not None
    assert restored.question.id == "residence"
    assert restored.answered == 2


def test_state_never_mutates_the_flow(engine: EligibilityEngine):
    engine.start(THREAD)
    engine.answer(THREAD, "5to18")
    first = engine.state(THREAD)
    second = engine.state(THREAD)
    assert first.question.id == second.question.id


def test_finishing_discards_the_answers_in_the_same_call(
    engine: EligibilityEngine, store: InMemorySessionStore
):
    """The result and the answers that produced it never coexist.

    This is the retention guarantee: once the verdict exists there is nothing
    left on the server to read back, so a later request cannot recover an age
    band, an island, or anything else the person tapped.
    """
    result = walk(engine, CLEAN)
    assert result.verdict is Verdict.LIKELY_ELIGIBLE
    assert store.get(THREAD) is None
    assert engine.state(THREAD) is None


def test_quitting_discards_the_answers_and_records_nothing(
    engine: EligibilityEngine, store: InMemorySessionStore
):
    engine.start(THREAD)
    engine.answer(THREAD, "5to18")
    engine.quit(THREAD)
    assert store.get(THREAD) is None
    assert engine.state(THREAD) is None


def test_quitting_a_check_that_is_not_running_is_not_an_error(
    engine: EligibilityEngine,
):
    """"Stop this" must never be able to fail."""
    engine.quit(THREAD)


def test_restart_clears_every_answer(engine: EligibilityEngine):
    engine.start(THREAD)
    engine.answer(THREAD, "under5")
    snapshot = engine.restart(THREAD)
    assert snapshot.question.id == "age"
    assert snapshot.question.answered_with is None


def test_restart_keeps_the_language_unless_told_otherwise(engine: EligibilityEngine):
    engine.start(THREAD, Language.FR)
    assert engine.restart(THREAD).language is Language.FR
    assert engine.restart(THREAD, Language.ES).language is Language.ES


def test_an_expired_session_reads_as_no_session_rather_than_a_stale_one(
    engine: EligibilityEngine, store: InMemorySessionStore
):
    """The TTL is a retention policy here, not just a cleanup."""
    engine.start(THREAD)
    engine.answer(THREAD, "5to18")
    store._age(THREAD, 7200)
    assert engine.state(THREAD) is None


def test_two_conversations_do_not_share_a_flow(engine: EligibilityEngine):
    engine.start("a")
    engine.start("b")
    engine.answer("a", "under5")
    assert engine.state("a").question.id == "age_exact"
    assert engine.state("b").question.id == "age"


# --- results ---------------------------------------------------------------


def test_a_likely_eligible_result_carries_a_checklist_and_the_steps(
    engine: EligibilityEngine,
):
    result = walk(engine, CLEAN)
    assert result.checklist
    assert len(result.steps) == 6
    assert result.notices, "the no-deadline notice belongs on an actionable result"
    assert result.contacts


def test_a_needs_confirmation_result_pre_frames_the_question_for_the_mentor(
    engine: EligibilityEngine,
):
    result = walk(engine, {**CLEAN, "residence": "abroad"})
    assert result.verdict is Verdict.NEEDS_CONFIRMATION
    assert result.mentor_question
    assert result.unresolved
    # Still actionable: nothing has ruled ASPIRE out.
    assert result.checklist and result.steps


def test_a_not_yet_on_citizenship_offers_no_checklist_to_gather(
    engine: EligibilityEngine,
):
    """A list of documents for a programme that is not open to them is not help."""
    result = walk(engine, {**CLEAN, "citizenship": "neither"})
    assert result.verdict is Verdict.NOT_YET
    assert result.checklist == ()
    assert result.steps == ()
    # But there is still somewhere to go.
    assert result.contacts


def test_the_under_five_result_names_a_year_and_says_what_to_do_meanwhile(
    engine: EligibilityEngine,
):
    """The outcome most likely to be handled badly. It must read as a date in
    the diary, not a door closing."""
    result = walk(engine, {**CLEAN, "age": "under5", "age_exact": "2"})
    assert result.verdict is Verdict.NOT_YET
    assert result.reminder_year == 2029
    assert any("2029" in line for line in result.body)
    # The no-deadline reassurance is the point of this one.
    assert result.notices


def test_every_result_carries_the_pre_check_disclaimer(engine: EligibilityEngine):
    for answers in (
        CLEAN,
        {**CLEAN, "citizenship": "neither"},
        {**CLEAN, "age": "under5", "age_exact": "1"},
        {**CLEAN, "residence": "abroad"},
        {**CLEAN, "age": "22plus"},
    ):
        engine.quit(THREAD)
        result = walk(engine, answers)
        assert result.disclaimer
        assert result.headline
        assert result.body
