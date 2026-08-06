"""The integrity property, asserted directly.

The answer never leaves the server until it is revealed — not in what the
browser receives, and not in what the agent sees. The second is the one that
matters: because the model is never handed an answer, no amount of "please just
tell me" gets one out of it. There is no prompt defence here to bypass, because
there is no code path that gives the model the key in the first place.

These tests drive the real tools, with the real seeds.
"""

from __future__ import annotations

import json

import pytest

from app.games import tools as tools_module
from app.games.engine import GameEngine
from app.games.models import Language
from app.games.normalise import normalise

# Matches the value in conftest; kept local because tests/ is not a package.
SESSION = "thread-under-test"


@pytest.fixture(autouse=True)
def wire_tools(engine: GameEngine, monkeypatch):
    """Point the tool layer at the test engine."""
    monkeypatch.setattr(tools_module, "get_engine", lambda: engine)
    return engine


def cfg(persona: str | None = None, thread_id: str = SESSION):
    return {"configurable": {"thread_id": thread_id, "persona": persona}}


def blob(payload) -> str:
    """Everything the model would see from a tool, as one comparable string."""
    return normalise(json.dumps(payload, default=str))


def assert_no_answers(payload, all_words, *, where: str):
    text = blob(payload)
    for word in all_words:
        assert normalise(word) not in text, f"{where} leaked {word!r}: {payload}"


# --- the model never receives an answer it was not given -------------------


def test_start_does_not_return_an_answer(all_words):
    payload = tools_module.start_game.invoke({}, config=cfg())
    assert payload["text"] == "NOEYM"
    assert_no_answers(payload, all_words, where="start_game")


def test_a_wrong_answer_reveals_nothing(all_words):
    tools_module.start_game.invoke({}, config=cfg())
    payload = tools_module.submit_answer.invoke({"answer": "banana"}, config=cfg())

    assert payload["correct"] is False
    # No answer, and no "close!" either: a near-miss signal is a side channel
    # that narrows the word for anyone probing it.
    assert "teaching_note" not in payload
    assert_no_answers(payload, all_words, where="submit_answer(wrong)")


def test_a_correct_answer_returns_the_meaning_not_the_key(all_words):
    tools_module.start_game.invoke({}, config=cfg())
    payload = tools_module.submit_answer.invoke({"answer": "money"}, config=cfg())

    assert payload["correct"] is True
    assert payload["teaching_note"] == "what we use to buy the things we need"
    # The word just solved is now known to the user anyway; what must not appear
    # is any *unsolved* answer, including the next one.
    assert "INTEREST" not in json.dumps(payload).upper()
    assert payload["next_text"] == "STERINTE"


@pytest.mark.parametrize("level", [1, 2, 3])
def test_no_hint_level_returns_the_answer(all_words, level):
    tools_module.start_game.invoke({}, config=cfg())
    payload = None
    for _ in range(level):
        payload = tools_module.get_hint.invoke({}, config=cfg())

    assert payload["revealed"] is False
    assert_no_answers(payload, all_words, where=f"get_hint(level={level})")


def test_list_games_returns_no_content(all_words):
    payload = tools_module.list_games.invoke({}, config=cfg())
    assert_no_answers(payload, all_words, where="list_games")


def test_quit_summary_returns_no_answers(all_words):
    tools_module.start_game.invoke({}, config=cfg())
    payload = tools_module.quit_game.invoke({}, config=cfg())
    assert_no_answers(payload, all_words, where="quit_game")


def test_an_entire_played_game_leaks_nothing_outside_a_reveal(all_words):
    """Walk the whole game and check every tool return."""
    seen: list[tuple[str, dict]] = []

    seen.append(("start_game", tools_module.start_game.invoke({}, config=cfg())))
    for _ in range(3):
        seen.append(("get_hint", tools_module.get_hint.invoke({}, config=cfg())))
    seen.append(
        ("submit_wrong", tools_module.submit_answer.invoke({"answer": "x"}, config=cfg()))
    )
    seen.append(
        (
            "submit_right",
            tools_module.submit_answer.invoke({"answer": "money"}, config=cfg()),
        )
    )
    seen.append(("skip_word", tools_module.skip_word.invoke({}, config=cfg())))
    seen.append(("quit_game", tools_module.quit_game.invoke({}, config=cfg())))

    for name, payload in seen:
        # A reveal is the sanctioned exception, and only ever for the item the
        # engine has already moved past. `revealed_answer` on a resolved submit,
        # `answer` on a hint that gave up or a skip.
        if payload.get("revealed") or "revealed_answer" in payload:
            assert payload.get("answer") or payload.get("revealed_answer")
            continue
        assert_no_answers(payload, all_words, where=name)


# --- the model cannot reach another session --------------------------------


def test_the_session_is_not_a_tool_argument():
    """LangChain keeps the injected config out of the schema the model sees.

    So the model cannot name a session, cannot reach another child's game, and
    cannot fabricate one. This is structural, not prompt-defended.
    """
    for tool in tools_module.GAME_TOOLS:
        visible = set(tool.args.keys())
        assert "config" not in visible, f"{tool.name} exposes config to the model"
        assert "session_id" not in visible
        assert "thread_id" not in visible

    assert set(tools_module.submit_answer.args.keys()) == {"answer"}
    assert set(tools_module.get_hint.args.keys()) == set()


def test_two_conversations_do_not_share_a_game():
    tools_module.start_game.invoke({}, config=cfg(thread_id="child-a"))
    payload = tools_module.submit_answer.invoke(
        {"answer": "money"}, config=cfg(thread_id="child-b")
    )
    assert payload["ok"] is False
    assert payload["reason"] == "no_game_running"


# --- the HTTP response carries no game state -------------------------------


def test_chat_response_schema_cannot_carry_an_answer():
    """The browser is never sent one, because there is no field for it.

    Asserted as an exact set on purpose: this test failing because someone added
    a field is the point of it. Widen it only after checking the new field
    cannot carry an answer -- which is why the nested models are checked too.
    """
    from app.schemas import ChatResponse, StartedEligibilityCheck, StartedGame

    assert set(ChatResponse.model_fields) == {
        "reply",
        "thread_id",
        "sources",
        "follow_ups",
        "game_started",
        "eligibility_started",
    }

    # The nested objects, because a closed model is only a guarantee while its
    # own fields are checked. Every one of these is already on the player's
    # screen.
    assert set(StartedGame.model_fields) == {
        "game_type",
        "display_name",
        "kind",
        "total",
    }

    # The eligibility card fetches its own question from its own endpoint, so
    # nothing about the flow rides here -- and because nothing does, there is no
    # field a game answer or a person's eligibility answers could travel in.
    assert set(StartedEligibilityCheck.model_fields) == {"check", "language"}


def test_a_game_directive_has_no_field_a_puzzle_could_travel_in():
    """The property `_extract_sources` used to be asked to guarantee.

    That test built a `ToolMessage` carrying `{"word": "MONEY"}` in its
    `artifact` and asserted `/chat`'s source extractor ignored it -- a check
    that the leak path was not TAKEN.

    There is no such path now. `/chat` is gone, sources come from
    `ground_check`'s citation set (kb ids and titles, nothing else), and a game
    is launched by a `GameDirective` whose schema is closed with
    `extra="forbid"`. The guarantee moved from "the extractor filters it out"
    to "there is no field it could be in", which is the stronger form.
    """
    from app.schemas.directives import GameDirective

    assert set(GameDirective.model_fields) == {"t", "game", "concept", "difficulty"}

    with pytest.raises(Exception):
        # `extra="forbid"`, so a puzzle cannot be smuggled in as a stray field.
        GameDirective(game="scramble", concept="saving", word="MONEY")
