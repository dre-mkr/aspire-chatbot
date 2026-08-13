"""The HTTP surface, and the contract a card turn has with /chat."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.eligibility.engine import EligibilityEngine
from app.eligibility.router import router


@pytest.fixture
def client(wired: EligibilityEngine) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def start(client: TestClient, thread: str = "t", language: str = "en"):
    response = client.post(
        "/api/eligibility/start", json={"thread_id": thread, "language": language}
    )
    assert response.status_code == 200
    return response.json()


def answer(client: TestClient, value: str, thread: str = "t"):
    response = client.post(
        "/api/eligibility/answer", json={"thread_id": thread, "value": value}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_start_returns_the_first_question_and_its_chrome(client: TestClient):
    body = start(client)
    assert body["active"] is True
    assert body["question"]["id"] == "age"
    assert body["question"]["position"] == 1
    assert body["question"]["total"] == 5
    assert body["result"] is None
    # The card's own labels ride along, so no button is English beside a French question.
    assert body["labels"]["back"] == "Back"
    assert body["labels"]["banner"]


def test_the_labels_come_back_in_the_flow_s_language(client: TestClient):
    body = start(client, language="fr")
    assert body["language"] == "fr"
    assert body["labels"]["back"] == "Retour"
    assert body["question"]["options"][0]["label"] == "Moins de 5 ans"


def test_an_unknown_language_falls_back_rather_than_refusing(client: TestClient):
    """An unfamiliar locale starts the flow in English rather than refusing to start at all."""
    body = start(client, language="pt-BR")
    assert body["active"] is True
    assert body["language"] == "en"


def test_a_second_start_in_one_conversation_is_a_conflict(client: TestClient):
    start(client)
    response = client.post(
        "/api/eligibility/start", json={"thread_id": "t", "language": "en"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "already_running"


def test_an_option_nobody_could_have_tapped_is_refused(client: TestClient):
    start(client)
    response = client.post(
        "/api/eligibility/answer", json={"thread_id": "t", "value": "make_me_eligible"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unknown_answer"


def test_answering_without_a_check_running_is_a_404(client: TestClient):
    response = client.post(
        "/api/eligibility/answer", json={"thread_id": "nope", "value": "5to18"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "no_check_running"


def test_the_whole_flow_reaches_a_result_over_http(client: TestClient):
    start(client)
    body = answer(client, "5to18")
    body = answer(client, "born_skn")
    body = answer(client, "st_kitts")
    body = answer(client, "in_school")
    body = answer(client, "guardian")

    assert body["active"] is False
    assert body["question"] is None
    assert body["result"]["verdict"] == "likely_eligible"
    assert body["result"]["checklist"]
    assert len(body["result"]["steps"]) == 6
    assert body["result"]["disclaimer"]


def test_back_over_http_restores_the_chosen_option(client: TestClient):
    start(client)
    answer(client, "5to18")
    answer(client, "born_skn")
    body = client.post("/api/eligibility/back", json={"thread_id": "t"}).json()
    assert body["question"]["id"] == "citizenship"
    assert body["question"]["answered_with"] == "born_skn"


def test_state_restores_a_flow_mid_way(client: TestClient):
    start(client)
    answer(client, "5to18")
    body = client.get("/api/eligibility/state", params={"thread_id": "t"}).json()
    assert body["active"] is True
    assert body["question"]["id"] == "citizenship"


def test_state_for_a_finished_flow_is_inactive_and_empty(client: TestClient):
    """Not half-rendered: the client holds the result from here on."""
    start(client)
    for value in ("5to18", "born_skn", "st_kitts", "in_school", "guardian"):
        answer(client, value)

    body = client.get("/api/eligibility/state", params={"thread_id": "t"}).json()
    assert body["active"] is False
    assert body["question"] is None
    assert body["result"] is None
    # Chrome still comes back, so a restarting card has its labels.
    assert body["labels"]["restart"]


def test_state_for_a_thread_with_no_flow_is_inactive(client: TestClient):
    body = client.get("/api/eligibility/state", params={"thread_id": "fresh"}).json()
    assert body["active"] is False
    assert body["question"] is None


def test_quit_always_succeeds_even_with_nothing_running(client: TestClient):
    response = client.post("/api/eligibility/quit", json={"thread_id": "never-started"})
    assert response.status_code == 200
    assert response.json()["active"] is False


def test_restart_clears_the_answers(client: TestClient):
    start(client)
    answer(client, "under5")
    body = client.post("/api/eligibility/restart", json={"thread_id": "t"}).json()
    assert body["question"]["id"] == "age"
    assert body["question"]["answered_with"] is None


def test_every_unsure_path_over_http_ends_in_a_conditional_result(client: TestClient):
    start(client)
    for _ in range(5):
        body = answer(client, "unsure")
        if body["question"] is None:
            break
    assert body["result"]["verdict"] == "needs_confirmation"
    assert body["result"]["mentor_question"]
    assert body["result"]["unresolved"]


# --- the /chat contract ----------------------------------------------------


def test_the_chat_response_has_no_field_an_answer_could_travel_in():
    """`StartedEligibilityCheck` is a closed model on purpose."""
    from app.schemas import StartedEligibilityCheck

    assert set(StartedEligibilityCheck.model_fields) == {"check", "language"}


def test_a_started_check_is_recognised_before_a_model_is_called():
    """The three tests that stood here read `main._started_eligibility`."""
    from app.graph.nodes.intents import wants_eligibility

    assert wants_eligibility("can I join?")
    assert not wants_eligibility("what is compound interest?")


def test_the_card_directive_has_no_field_an_answer_could_travel_in():
    """The closed-model property, on the type that replaced `StartedEligibilityCheck`."""
    from app.schemas.directives import EligibilityDirective

    assert set(EligibilityDirective.model_fields) == {"t", "check", "language"}
