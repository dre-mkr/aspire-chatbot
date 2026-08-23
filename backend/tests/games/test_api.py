"""The HTTP surface the game card talks to."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.games.router as router_module
from app.games.normalise import normalise
from app.games.router import router

THREAD = "thread-http"


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(router_module, "get_engine", lambda: engine)
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def no_answers(payload, all_words, *, where: str):
    text = normalise(json.dumps(payload, default=str))
    for word in all_words:
        assert normalise(word) not in text, f"{where} leaked {word!r}: {payload}"


# --- state and lifecycle ---------------------------------------------------


def test_state_is_empty_before_anything_starts(client):
    body = client.get("/api/games/state", params={"thread_id": THREAD}).json()
    assert body == {"active": False, "game": None}


def test_start_returns_the_first_scramble(client, all_words):
    response = client.post("/api/games/start", json={"thread_id": THREAD})
    assert response.status_code == 200

    body = response.json()
    assert body["active"] is True
    assert body["game"]["prompt"]["text"] == "NOEYM"
    assert body["game"]["prompt"]["position"] == 1
    assert body["game"]["prompt"]["total"] == 4
    assert body["game"]["hints"] == []
    no_answers(body, all_words, where="start")


def test_state_survives_a_reload(client, all_words):
    """A refresh is a new GET, and the game is still there."""
    client.post("/api/games/start", json={"thread_id": THREAD})
    client.post("/api/games/hint", json={"thread_id": THREAD})

    body = client.get("/api/games/state", params={"thread_id": THREAD}).json()
    assert body["active"] is True
    assert body["game"]["prompt"]["text"] == "NOEYM"
    assert body["game"]["hint_level"] == 1
    # The spent clue comes back, so the card redraws exactly as it was.
    assert body["game"]["hints"] == ["It starts with M."]
    no_answers(body, all_words, where="state after reload")


def test_a_wrong_answer_says_only_that(client, all_words):
    client.post("/api/games/start", json={"thread_id": THREAD})
    body = client.post(
        "/api/games/submit", json={"thread_id": THREAD, "answer": "banana"}
    ).json()

    assert body["correct"] is False
    assert body["attempts"] == 1
    assert body["teaching_note"] is None
    # Still on word one, and told nothing about it.
    assert body["game"]["prompt"]["position"] == 1
    no_answers(body, all_words, where="submit(wrong)")


def test_a_correct_answer_teaches_and_advances(client):
    client.post("/api/games/start", json={"thread_id": THREAD})
    body = client.post(
        "/api/games/submit", json={"thread_id": THREAD, "answer": "  MoNeY! "}
    ).json()

    assert body["correct"] is True
    assert body["teaching_note"] == "what we use to buy the things we need"
    assert body["game"]["prompt"]["text"] == "STERINTE"
    assert body["game"]["prompt"]["position"] == 2
    assert body["game"]["solved"] == 1


def test_hints_climb_then_reveal(client, all_words):
    client.post("/api/games/start", json={"thread_id": THREAD})

    for level in (1, 2, 3):
        body = client.post("/api/games/hint", json={"thread_id": THREAD}).json()
        assert body["revealed"] is False
        assert body["level"] == level
        assert body["hint"]
        no_answers(body, all_words, where=f"hint {level}")

    given_up = client.post("/api/games/hint", json={"thread_id": THREAD}).json()
    assert given_up["revealed"] is True
    assert given_up["reveal"]["answer"] == "MONEY"
    assert given_up["reveal"]["explanation"]
    assert given_up["game"]["prompt"]["text"] == "STERINTE"


def test_skip_reveals_and_moves_on(client):
    client.post("/api/games/start", json={"thread_id": THREAD})
    body = client.post("/api/games/skip", json={"thread_id": THREAD}).json()

    assert body["reveal"]["answer"] == "MONEY"
    assert body["game"]["prompt"]["position"] == 2
    assert body["game"]["skipped"] == 1


def test_finishing_returns_a_summary_and_clears_state(client):
    client.post("/api/games/start", json={"thread_id": THREAD})
    for _ in range(3):
        client.post("/api/games/skip", json={"thread_id": THREAD})

    last = client.post("/api/games/skip", json={"thread_id": THREAD}).json()
    assert last["finished"] is True
    assert last["game"] is None
    assert last["summary"]["skipped"] == 4
    assert last["summary"]["total"] == 4

    after = client.get("/api/games/state", params={"thread_id": THREAD}).json()
    assert after["active"] is False


def test_quit_ends_it(client):
    client.post("/api/games/start", json={"thread_id": THREAD})
    body = client.post("/api/games/quit", json={"thread_id": THREAD}).json()
    assert body["total"] == 4
    assert client.get(
        "/api/games/state", params={"thread_id": THREAD}
    ).json()["active"] is False


# --- declines carry a machine-readable reason ------------------------------


def test_acting_without_a_game_is_404(client):
    for path, payload in (
        ("/api/games/submit", {"thread_id": THREAD, "answer": "money"}),
        ("/api/games/hint", {"thread_id": THREAD}),
        ("/api/games/skip", {"thread_id": THREAD}),
        ("/api/games/quit", {"thread_id": THREAD}),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 404, path
        assert response.json()["detail"]["reason"] == "no_game_running"


def test_starting_twice_is_409(client):
    client.post("/api/games/start", json={"thread_id": THREAD})
    response = client.post("/api/games/start", json={"thread_id": THREAD})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "already_running"


@pytest.mark.parametrize("persona", ["aurora", "nova"])
def test_a_guardian_or_teacher_gets_a_game_rather_than_a_403(client, persona):
    """This returned 403 `not_available_for_persona`, which is what made a
    "play a game" control unshippable: it threw for two of the six voices.

    They are served the 13-18 bank, because they have none of their own -- see
    `_CONTENT_BANK`. Restraint about *offering* now lives in the persona cards,
    where it can say "do not raise this unprompted" instead of "never".
    """
    response = client.post(
        "/api/games/start", json={"thread_id": THREAD, "persona": persona}
    )
    assert response.status_code == 200, response.text
    assert response.json()["game"] is not None


def test_an_unauthored_language_is_422(client):
    """A language a GAME has no set for.

    Was any of Spanish or French, when every seed was English. Two games are now
    authored in both, so the refusal has to be asked of one that is not --
    `hangman` -- or it tests nothing.
    """
    response = client.post(
        "/api/games/start",
        json={"thread_id": THREAD, "language": "es", "game_type": "hangman"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "no_set_for_language"

def test_an_authored_language_starts(client):
    """The other half, so the 422 above cannot pass by everything being broken."""
    response = client.post(
        "/api/games/start",
        json={"thread_id": THREAD + "-es", "language": "es", "game_type": "word_scramble"},
    )
    assert response.status_code == 200


def test_an_unknown_persona_is_ignored_not_rejected(client):
    response = client.post(
        "/api/games/start", json={"thread_id": THREAD, "persona": "teacher"}
    )
    assert response.status_code == 200


def test_threads_do_not_share_a_game(client):
    client.post("/api/games/start", json={"thread_id": "child-a"})
    response = client.post(
        "/api/games/submit", json={"thread_id": "child-b", "answer": "money"}
    )
    assert response.status_code == 404


# --- the whole surface, swept ----------------------------------------------


def test_no_endpoint_leaks_an_answer_outside_a_reveal(client, all_words):
    client.post("/api/games/start", json={"thread_id": THREAD})

    calls = [
        ("GET /state", client.get("/api/games/state", params={"thread_id": THREAD})),
        ("GET /", client.get("/api/games")),
        (
            "POST /submit",
            client.post("/api/games/submit", json={"thread_id": THREAD, "answer": "zz"}),
        ),
        ("POST /hint", client.post("/api/games/hint", json={"thread_id": THREAD})),
        ("POST /quit", client.post("/api/games/quit", json={"thread_id": THREAD})),
    ]
    for where, response in calls:
        no_answers(response.json(), all_words, where=where)


def test_the_state_schema_has_no_place_to_put_an_answer():
    from app.games.schemas import GameStateOut

    assert "word" not in GameStateOut.model_fields
    assert "answer" not in GameStateOut.model_fields
    assert "definition" not in GameStateOut.model_fields
