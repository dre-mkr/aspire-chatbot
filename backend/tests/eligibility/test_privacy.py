"""What must never leave the engine, and what must never reach Postgres."""

from __future__ import annotations

import json

import pytest

from app.db.models import EligibilityOutcome
from app.eligibility.engine import EligibilityEngine
from app.eligibility.models import Criterion, Language, Outcome, Verdict
from app.eligibility.router import _envelope
from app.eligibility.tools import start_eligibility_check

# Every answer token a person can tap.
ANSWER_TOKENS = (
    "under5",
    "5to18",
    "19to21",
    "22plus",
    "born_skn",
    "by_descent",
    "neither",
    "st_kitts",
    "nevis",
    "abroad",
    "in_school",
    "home_school",
    "not_in_school",
    "guardian",
)

DISTINCTIVE = {
    "age": "under5",
    "age_exact": "4",
    "citizenship": "by_descent",
    "residence": "nevis",
    "school": "not_in_school",
    "registrant": "self",
}


def walk(engine: EligibilityEngine, thread: str, answers: dict[str, str]):
    snapshot = engine.start(thread, Language.EN)
    while snapshot.question is not None:
        snapshot = engine.answer(thread, answers[snapshot.question.id])
    return snapshot


def test_the_outcome_row_has_no_field_an_answer_could_occupy():
    """Checked against the ORM column set, not against a dict we built."""
    columns = {column.name for column in EligibilityOutcome.__table__.columns}
    assert columns == {"id", "verdict", "criterion", "language", "created_at"}


def test_the_outcome_row_has_no_link_back_to_a_conversation():
    """A join key would tie a verdict to a transcript, and a transcript identifies a person far better than an age b…"""
    assert EligibilityOutcome.__table__.foreign_keys == set()
    columns = {column.name for column in EligibilityOutcome.__table__.columns}
    for identifying in ("conversation_id", "thread_id", "session_id", "user_id"):
        assert identifying not in columns


def test_the_outcome_dataclass_cannot_carry_an_answer():
    """The function that writes to Postgres takes this type and nothing else."""
    assert set(Outcome.__dataclass_fields__) == {"verdict", "criterion", "language"}


def test_the_persisted_outcome_contains_no_answer_token(engine: EligibilityEngine):
    snapshot = walk(engine, "privacy-1", DISTINCTIVE)
    assert snapshot.result is not None

    outcome = EligibilityEngine.outcome_of(snapshot.result, Language.EN)
    row = EligibilityOutcome(
        verdict=outcome.verdict.value,
        criterion=outcome.criterion.value,
        language=outcome.language.value,
    )
    stored = f"{row.verdict} {row.criterion} {row.language}"
    for token in ANSWER_TOKENS:
        assert token not in stored

    # And specifically: no island, ever, alongside anything else.
    assert "nevis" not in stored.lower()
    assert "kitts" not in stored.lower()


def test_the_outcome_is_only_ever_one_of_the_declared_values(
    engine: EligibilityEngine,
):
    snapshot = walk(engine, "privacy-2", DISTINCTIVE)
    outcome = EligibilityEngine.outcome_of(snapshot.result, Language.EN)
    assert outcome.verdict in set(Verdict)
    assert outcome.criterion in set(Criterion)


def test_the_agent_tool_returns_nothing_about_the_person(wired: EligibilityEngine):
    """The model's whole view of this feature."""
    result = start_eligibility_check.invoke(
        {},
        config={"configurable": {"thread_id": "privacy-3", "language": "en"}},
    )
    assert set(result) == {"ok", "started", "check"}
    assert result["check"] == "aspire_eligibility"
    # And the card really was opened, in the conversation's own language.
    assert wired.state("privacy-3").question.id == "age"


def test_the_history_line_carries_no_answer_and_no_verdict():
    """It is written into a transcript that identifies a conversation."""
    # Moved to `app/turn.py` with the rest of the persistence when `/chat` went.
    from app.turn import eligibility_history_line

    line = eligibility_history_line().lower()
    for token in ANSWER_TOKENS:
        assert token not in line
    for verdict in Verdict:
        assert verdict.value not in line
    # It still has to do its job: stop the model re-asking.
    assert "do not re-ask" in line


def test_a_question_response_carries_only_the_answer_to_its_own_question(
    engine: EligibilityEngine,
):
    """`answered_with` is the one place an answer appears, and it is scoped to the question being shown -- never the…"""
    engine.start("privacy-4", Language.EN)
    engine.answer("privacy-4", "under5")
    engine.answer("privacy-4", "4")
    snapshot = engine.answer("privacy-4", "by_descent")

    body = json.loads(_envelope(snapshot, Language.EN).model_dump_json())
    rendered = json.dumps(body)
    # The current question is `residence`; nothing from the three answered before it may be in the payload.
    assert "under5" not in rendered
    assert "by_descent" not in rendered
    assert body["question"]["id"] == "residence"
    assert body["question"]["answered_with"] is None


def test_going_back_shows_only_that_question_s_own_answer(engine: EligibilityEngine):
    engine.start("privacy-5", Language.EN)
    engine.answer("privacy-5", "5to18")
    engine.answer("privacy-5", "by_descent")
    snapshot = engine.back("privacy-5")

    body = json.loads(_envelope(snapshot, Language.EN).model_dump_json())
    assert body["question"]["id"] == "citizenship"
    assert body["question"]["answered_with"] == "by_descent"
    # The age answer is not in this payload.
    assert "5to18" not in json.dumps(body)


def test_a_finished_flow_leaves_nothing_on_the_server(engine: EligibilityEngine):
    """The retention guarantee, from the outside."""
    walk(engine, "privacy-6", DISTINCTIVE)
    assert engine.state("privacy-6") is None
    envelope = _envelope(engine.state("privacy-6"), Language.EN)
    assert envelope.active is False
    assert envelope.result is None


def test_the_result_payload_holds_no_raw_answer(engine: EligibilityEngine):
    """The verdict and the checklist are derived from the answers."""
    snapshot = walk(engine, "privacy-7", DISTINCTIVE)
    rendered = json.dumps(json.loads(_envelope(snapshot, Language.EN).model_dump_json()))
    for token in ANSWER_TOKENS:
        assert token not in rendered


@pytest.mark.parametrize(
    "answers",
    [
        DISTINCTIVE,
        {**DISTINCTIVE, "age": "5to18", "residence": "st_kitts"},
        {key: "unsure" for key in DISTINCTIVE},
    ],
)
def test_no_log_line_names_a_thread_alongside_an_answer(
    engine: EligibilityEngine, answers: dict[str, str], caplog
):
    """No PII in logs."""
    with caplog.at_level("DEBUG"):
        walk(engine, "privacy-8", answers)

    for record in caplog.records:
        message = record.getMessage().lower()
        assert "privacy-8" not in message
        for token in ANSWER_TOKENS:
            assert token not in message
