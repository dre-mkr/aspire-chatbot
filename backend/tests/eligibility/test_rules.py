"""The verdict logic, tested against the audit rather than against itself."""

from __future__ import annotations

from datetime import date

import pytest

from app.eligibility.models import Criterion, Verdict
from app.eligibility.rules import (
    COUNTED,
    OPTIONS,
    decide,
    documents_for,
    plan,
    reminder_year,
    steps_for,
)

# A set of answers that passes cleanly, to vary one field at a time from.
CLEAN = {
    "age": "5to18",
    "citizenship": "born_skn",
    "residence": "st_kitts",
    "school": "in_school",
    "registrant": "guardian",
}


def test_clean_answers_are_likely_eligible_and_nothing_stronger():
    decision = decide(CLEAN)
    assert decision.verdict is Verdict.LIKELY_ELIGIBLE
    assert decision.criterion is Criterion.NONE
    assert decision.unresolved == ()


def test_non_citizen_is_the_only_firm_refusal():
    """ASP-039: "Non-citizens and permanent residents are not eligible." The one place the source says no outright."""
    decision = decide({**CLEAN, "citizenship": "neither"})
    assert decision.verdict is Verdict.NOT_YET
    assert decision.criterion is Criterion.CITIZENSHIP


def test_under_five_is_not_yet_with_a_year_to_come_back():
    """ASP-029, ASP-041, ASP-042. A real "not yet", not a refusal."""
    decision = decide({**CLEAN, "age": "under5", "age_exact": "3"})
    assert decision.verdict is Verdict.NOT_YET
    assert decision.criterion is Criterion.AGE_MINIMUM
    assert reminder_year({"age": "under5", "age_exact": "3"}, date(2026, 8, 2)) == 2028


def test_nineteen_to_twentyone_is_never_a_flat_no():
    """The audit's headline finding."""
    decision = decide({**CLEAN, "age": "19to21"})
    assert decision.verdict is Verdict.NEEDS_CONFIRMATION
    assert decision.criterion is Criterion.AGE_COHORT


def test_over_twentyone_still_surfaces_the_cohort_clause():
    """Outside both clauses on any ordinary birthday -- but we asked for a band."""
    decision = decide({**CLEAN, "age": "22plus"})
    assert decision.verdict is Verdict.NOT_YET
    assert decision.criterion is Criterion.AGE_COHORT
    assert "age_cohort" in decision.unresolved


def test_living_abroad_is_a_question_not_a_refusal():
    """Audit finding B."""
    decision = decide({**CLEAN, "residence": "abroad"})
    assert decision.verdict is Verdict.NEEDS_CONFIRMATION
    assert decision.criterion is Criterion.RESIDENCE


def test_not_in_school_is_a_question_not_a_refusal():
    """Audit finding C."""
    decision = decide({**CLEAN, "school": "not_in_school"})
    assert decision.verdict is Verdict.NEEDS_CONFIRMATION
    assert decision.criterion is Criterion.SCHOOL


def test_home_schooling_passes_cleanly():
    """ASP-033, ASP-034: registered home schooling is explicitly eligible."""
    assert decide({**CLEAN, "school": "home_school"}).verdict is Verdict.LIKELY_ELIGIBLE


def test_citizen_by_descent_passes_cleanly():
    """ASP-028, ASP-038, ASP-240."""
    assert decide({**CLEAN, "citizenship": "by_descent"}).verdict is Verdict.LIKELY_ELIGIBLE


@pytest.mark.parametrize("island", ["st_kitts", "nevis"])
def test_island_never_changes_the_verdict(island: str):
    """ASP-044, ASP-247: both islands are covered identically."""
    decision = decide({**CLEAN, "residence": island})
    assert decision.verdict is Verdict.LIKELY_ELIGIBLE
    assert decision.criterion is Criterion.NONE


@pytest.mark.parametrize("who", ["guardian", "self", "unsure"])
def test_who_registers_never_changes_the_verdict(who: str):
    """ASP-049, ASP-050, ASP-295 make this paperwork, never a criterion."""
    assert decide({**CLEAN, "registrant": who}).verdict is Verdict.LIKELY_ELIGIBLE


# --- "I am not sure" on every question, one at a time ----------------------


@pytest.mark.parametrize("question", ["age", "citizenship", "residence", "school"])
def test_unsure_on_a_criterion_gives_a_conditional_result_not_a_block(question: str):
    decision = decide({**CLEAN, question: "unsure"})
    assert decision.verdict is Verdict.NEEDS_CONFIRMATION
    assert decision.unresolved, "an unresolved answer must name what is unresolved"


def test_unsure_on_everything_still_reaches_an_outcome():
    decision = decide({key: "unsure" for key in CLEAN})
    assert decision.verdict is Verdict.NEEDS_CONFIRMATION
    # Every open criterion is listed, not just the one it is filed under.
    assert len(decision.unresolved) >= 4


def test_unsure_exact_age_still_produces_the_not_yet_result():
    """Losing the year must not lose the result."""
    decision = decide({**CLEAN, "age": "under5", "age_exact": "unsure"})
    assert decision.verdict is Verdict.NOT_YET
    assert reminder_year({"age": "under5", "age_exact": "unsure"}, date(2026, 8, 2)) is None


# --- exhaustive: no dead ends ----------------------------------------------


def _every_combination():
    """The whole answer space, including every unsure and both plan shapes."""
    from itertools import product

    keys = ["age", "citizenship", "residence", "school", "registrant"]
    for values in product(*(OPTIONS[key] for key in keys)):
        answers = dict(zip(keys, values, strict=True))
        if answers["age"] == "under5":
            for exact in OPTIONS["age_exact"]:
                yield {**answers, "age_exact": exact}
        else:
            yield answers


def test_every_reachable_answer_set_reaches_one_of_the_three_outcomes():
    """The no-dead-ends guarantee, checked by exhaustion rather than by sampling."""
    seen = set()
    for answers in _every_combination():
        decision = decide(answers)
        assert decision.verdict in set(Verdict)
        assert decision.copy_key, "every outcome must name the copy that renders it"
        seen.add(decision.verdict)
    assert seen == set(Verdict), "all three outcomes must be reachable"


def test_every_answer_set_produces_a_usable_document_list():
    for answers in _every_combination():
        documents = documents_for(answers)
        assert documents, "a checklist must never come back empty"
        # Proof of citizenship is the one thing every route needs.
        assert any(
            key in documents
            for key in ("birth_certificate", "descent_certificate")
        )
        assert len(set(documents)) == len(documents), "no document listed twice"


def test_every_answer_set_produces_a_full_walkthrough():
    for answers in _every_combination():
        steps = steps_for(answers)
        assert len(steps) == 6
        assert len(set(steps)) == len(steps)


# --- the plan --------------------------------------------------------------


def test_plan_is_five_questions_and_six_only_under_five():
    assert plan({}) == ("age", "citizenship", "residence", "school", "registrant")
    assert "age_exact" in plan({"age": "under5"})
    assert "age_exact" not in plan({"age": "5to18"})


def test_the_flow_never_exceeds_six_questions():
    """The brief's ceiling. Four to six, one per step."""
    for answers in _every_combination():
        assert 5 <= len(plan(answers)) <= 6
    assert len(COUNTED) == 5


# --- documents, against the audit ------------------------------------------


def test_born_here_is_asked_for_a_birth_certificate_not_a_descent_certificate():
    """ASP-035/036."""
    documents = documents_for({**CLEAN, "citizenship": "born_skn"})
    assert "birth_certificate" in documents
    assert "descent_certificate" not in documents


def test_by_descent_is_asked_for_the_descent_certificate():
    """ASP-028, ASP-035, ASP-038."""
    documents = documents_for({**CLEAN, "citizenship": "by_descent"})
    assert "descent_certificate" in documents
    assert "birth_certificate" not in documents


def test_unsure_citizenship_is_offered_both_routes():
    documents = documents_for({**CLEAN, "citizenship": "unsure"})
    assert "birth_certificate" in documents
    assert "descent_certificate" in documents


def test_guardian_id_appears_only_when_an_adult_is_filling_the_form():
    """ASP-248, ASP-295."""
    assert "guardian_id" in documents_for({**CLEAN, "registrant": "guardian"})
    assert "guardian_id" not in documents_for({**CLEAN, "registrant": "self"})
    # Not sure yet gets it: a spare line costs nothing, a missing one costs a trip.
    assert "guardian_id" in documents_for({**CLEAN, "registrant": "unsure"})


def test_no_document_outside_the_audited_set():
    """The hard rule, as an assertion."""
    audited = {
        "birth_certificate",  # ASP-035, ASP-036
        "descent_certificate",  # ASP-028, ASP-035, ASP-038
        "passport",  # ASP-250, hedged by ASP-037
        "guardian_id",  # ASP-248
        "proof_of_address",  # ASP-251
    }
    for answers in _every_combination():
        assert set(documents_for(answers)) <= audited


# --- the walkthrough -------------------------------------------------------


def test_only_st_kitts_is_sent_to_the_basseterre_walk_in_centre():
    """ASP-299, ASP-300 name a centre in Basseterre and the knowledge base names no equivalent on Nevis."""
    assert "in_person_kitts" in steps_for({**CLEAN, "residence": "st_kitts"})
    for elsewhere in ("nevis", "abroad", "unsure"):
        steps = steps_for({**CLEAN, "residence": elsewhere})
        assert "in_person_kitts" not in steps
        assert "in_person_events" in steps
