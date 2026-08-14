"""The tool layer: what the agent can and cannot do."""

from __future__ import annotations

import pytest

from app.games import games_proactive_suggest
from app.games import tools as tools_module
from app.games.engine import GameEngine

# Matches the value in conftest; kept local because tests/ is not a package.
SESSION = "thread-under-test"


@pytest.fixture(autouse=True)
def wire_tools(engine: GameEngine, monkeypatch):
    monkeypatch.setattr(tools_module, "get_engine", lambda: engine)
    return engine


def cfg(persona: str | None = None, thread_id: str = SESSION, language: str | None = None):
    configurable = {"thread_id": thread_id, "persona": persona}
    if language:
        configurable["language"] = language
    return {"configurable": configurable}


# --- the six tools exist, named as specified -------------------------------


def test_the_expected_tools_are_exposed():
    assert {t.name for t in tools_module.GAME_TOOLS} == {
        "start_game",
        "submit_answer",
        "get_hint",
        "skip_word",
        "quit_game",
        "list_games",
    }


def test_list_games_describes_what_actually_exists(engine):
    payload = tools_module.list_games.invoke({}, config=cfg())
    # The fixture engine carries word scramble only, so no true/false set is listed here.
    assert payload["games"] == [
        {
            "id": "word_scramble",
            "name": "Unscramble These Words",
            "items": 4,
            "supports_hints": True,
            "languages": ["en"],
        }
    ]


# --- persona gating, through the config the request supplies ---------------


@pytest.mark.parametrize("persona", ["stella", "orion"])
def test_account_holders_may_start(persona):
    payload = tools_module.start_game.invoke({}, config=cfg(persona))
    assert payload["ok"] is True
    assert payload["text"] == "NOEYM"


@pytest.mark.parametrize("persona", ["aurora", "nova"])
def test_parents_and_newcomers_are_declined_with_a_reason(persona):
    payload = tools_module.start_game.invoke({}, config=cfg(persona))
    assert payload["ok"] is False
    assert payload["reason"] == "not_available_for_persona"
    # The agent needs something to say, not just a flag.
    assert payload["detail"]


def test_an_unknown_persona_is_allowed_rather_than_locked_out():
    assert tools_module.start_game.invoke({}, config=cfg(None))["ok"] is True


def test_a_nonsense_persona_is_ignored_not_fatal():
    payload = tools_module.start_game.invoke({}, config=cfg("teacher"))
    assert payload["ok"] is True


# --- declines are structured, never exceptions ------------------------------


def test_starting_twice_declines_cleanly():
    tools_module.start_game.invoke({}, config=cfg())
    payload = tools_module.start_game.invoke({}, config=cfg())
    assert payload == {
        "ok": False,
        "reason": "already_running",
        "detail": "A game is already running here.",
    }


def test_an_unauthored_language_declines_cleanly():
    payload = tools_module.start_game.invoke({"language": "es"}, config=cfg())
    assert payload["ok"] is False
    assert payload["reason"] == "no_set_for_language"


def test_acting_without_a_game_declines_cleanly():
    for tool, args in (
        (tools_module.submit_answer, {"answer": "money"}),
        (tools_module.get_hint, {}),
        (tools_module.skip_word, {}),
        (tools_module.quit_game, {}),
    ):
        payload = tool.invoke(args, config=cfg())
        assert payload["ok"] is False, tool.name
        assert payload["reason"] == "no_game_running", tool.name


def test_an_unknown_game_declines_cleanly():
    payload = tools_module.start_game.invoke({"game_type": "sudoku"}, config=cfg())
    assert payload["ok"] is False
    assert payload["reason"] == "unknown_game"


# --- the rules the agent is told ------------------------------------------


def test_proactive_suggestion_is_off_by_default():
    assert games_proactive_suggest() is False


def test_start_game_tells_the_agent_not_to_offer_unprompted():
    description = tools_module.start_game.description.lower()
    assert "only when the user has asked" in description
    assert "never offer a game unprompted" in description


def test_submit_answer_tells_the_agent_it_does_not_judge():
    description = tools_module.submit_answer.description.lower()
    assert "you do not decide whether an answer is right" in description
    assert "do not guess at it" in description


def test_quit_game_tells_the_agent_to_accept_any_exit_signal():
    description = tools_module.quit_game.description.lower()
    assert "any clear signal" in description
    assert "never require a particular word" in description


def test_no_model_is_asked_not_to_invent_game_content_because_none_can():
    """
    This asserted that `prompts.GAMES_INSTRUCTIONS` forbids inventing a word.

    That constant is in no live prompt -- it belonged to the v1 tool-calling
    design, which the v2 graph replaced -- so the test was certifying a rule
    that is told to nothing. Worse, it read as coverage for the property it
    names while the property was being held up by something else entirely.

    The something else is better than a prompt rule: game content is not
    generated at all. Words come from seed files on disk, so a model cannot
    invent one whatever it is or is not told.
    """
    from app.games.config import get_game_settings

    seed_dir = get_game_settings().seed_dir
    assert seed_dir.is_dir(), f"no seed directory at {seed_dir}"

    seeded = list(seed_dir.rglob("*.json")) + list(seed_dir.rglob("*.yaml"))
    assert seeded, (
        "no seed files: if game content ever starts coming from a model, the "
        "protection this test replaced would need to come back as a prompt rule"
    )
