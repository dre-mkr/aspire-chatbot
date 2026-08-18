"""True or false."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.games.config import GameSettings
from app.games.engine import GameEngine, HintsNotAvailable, NoContentAvailable
from app.games.events import MemoryEventSink
from app.games.loader import SeedError, load_sets
from app.games.models import Language, Persona, StatementEntry, Volatility
from app.games.normalise import looks_like_yes_no, parse_verdict
from app.games.store import InMemorySessionStore
from app.games.truefalse import TrueFalseGame

SESSION = "tf-session"
TODAY = date(2026, 8, 1)

FIXTURE_SET = """
id: tf-fixture
game_type: true_false
language: en
title: True or False
source: fixture
entries:
  - id: tf-a
    statement: Saving means keeping money for later.
    answer: true
    explanation: Keeping money now so you have it later. That is all saving is.
    topic: savings
    difficulty_band: warmup
    persona_bands: [stella, orion]
  - id: tf-b
    statement: Inflation means your money buys more than it did.
    answer: false
    explanation: Inflation is prices rising, so the same money buys less.
    topic: inflation
    difficulty_band: core
    persona_bands: [orion]
  - id: tf-c
    statement: All spending decisions have opportunity costs.
    answer: true
    explanation: Spending on one thing is choosing not to spend it on another.
    topic: opportunity-cost
    difficulty_band: core
    persona_bands: [orion]
  - id: tf-d
    statement: The objective of investing is to minimise returns.
    answer: false
    explanation: Investing seeks a return; the risk is what you weigh against it.
    topic: investing
    difficulty_band: core
    persona_bands: [orion]
  - id: tf-e
    statement: A dollar today is worth more than a dollar next year.
    answer: true
    explanation: A dollar you hold now can earn. One you wait for cannot.
    topic: time-value-of-money
    difficulty_band: core
    persona_bands: [orion]
  - id: tf-f
    statement: An emergency fund is wise because the future is uncertain.
    answer: true
    explanation: You cannot plan the surprise, only whether it finds you ready.
    topic: emergency-fund
    difficulty_band: core
    persona_bands: [orion]
  - id: tf-stale
    statement: The minimum statutory deposit rate is two percent.
    answer: true
    explanation: A rate someone else sets, and can change without telling us.
    topic: interest-rates
    difficulty_band: advanced
    persona_bands: [orion]
    volatility: volatile
"""


@pytest.fixture
def tf_seed(tmp_path):
    folder = tmp_path / "en"
    folder.mkdir(parents=True)
    (folder / "tf.yaml").write_text(FIXTURE_SET, encoding="utf-8")
    return tmp_path


@pytest.fixture
def tf_settings(tf_seed) -> GameSettings:
    return GameSettings(
        games_enabled=True,
        seed_dir=tf_seed,
        volatile_review_days=180,
        max_hint_level=3,
    )


@pytest.fixture
def tf_game(tf_settings) -> TrueFalseGame:
    return TrueFalseGame(tf_settings)


@pytest.fixture
def tf_engine(tf_game, tf_settings) -> GameEngine:
    return GameEngine(
        games=[tf_game],
        store=InMemorySessionStore(3600.0),
        sink=MemoryEventSink(),
        settings=tf_settings,
        today=TODAY,
    )


def statements(game: TrueFalseGame) -> list[StatementEntry]:
    return [e for s in game.sets_for(Language.EN) for e in s.entries]


# --- answer parsing --------------------------------------------------------


@pytest.mark.parametrize("typed", ["true", "TRUE", "True", "  true ", "t", "T", "true."])
def test_true_parses(typed):
    assert parse_verdict(typed) is True


@pytest.mark.parametrize("typed", ["false", "FALSE", "False", " false ", "f", "F", "false!"])
def test_false_parses(typed):
    assert parse_verdict(typed) is False


@pytest.mark.parametrize("typed", ["yes", "no", "Y", "n", "yeah", "nope", "nah", "yup"])
def test_yes_and_no_are_refused_not_guessed(typed):
    """On a negatively-framed statement, "no" genuinely does not say which way."""
    assert parse_verdict(typed) is None
    assert looks_like_yes_no(typed) is True


@pytest.mark.parametrize("typed", ["", "   ", "maybe", "banana", "42"])
def test_gibberish_is_unreadable_but_not_a_yes_no(typed):
    assert parse_verdict(typed) is None
    assert looks_like_yes_no(typed) is False


def test_the_reprompt_says_why_for_a_yes(tf_game):
    entry = statements(tf_game)[0]
    assert tf_game.check(entry, "yes") is None
    message = tf_game.unreadable_message("yes")
    assert "true or false" in message.lower()
    assert "could mean either" in message


# --- the capability the protocol lets a game decline -----------------------


def test_true_false_declares_no_hints(tf_game):
    assert tf_game.supports_hints is False


def test_asking_for_a_hint_is_declined_not_faked(tf_engine):
    """A hint on a binary choice is the answer, so there is nothing to give."""
    tf_engine.start(SESSION, game_type="true_false")
    with pytest.raises(HintsNotAvailable) as raised:
        tf_engine.hint(SESSION)
    assert raised.value.reason == "hints_not_available"


def test_state_reports_no_hints_and_offers_no_levels(tf_engine):
    tf_engine.start(SESSION, game_type="true_false")
    state = tf_engine.state(SESSION)
    assert state.supports_hints is False
    assert state.max_hint_level == 0
    assert state.hints == ()


# --- rounds ----------------------------------------------------------------


def test_a_round_is_five_not_the_whole_bank(tf_engine):
    tf_engine.start(SESSION, game_type="true_false")
    assert tf_engine.state(SESSION).prompt.total == 5


def test_the_round_is_shuffled_per_session(tf_engine):
    """Answer FALSE every time and a fixed order is learnable. Shuffle it."""
    orders = set()
    for n in range(12):
        session = f"{SESSION}-{n}"
        tf_engine.start(session, game_type="true_false")
        first = tf_engine.state(session).prompt.text
        orders.add(first)
        tf_engine.quit(session)
    assert len(orders) > 1, "every session opened on the same statement"


def test_the_same_session_always_gets_the_same_round(tf_engine, tf_game, tf_settings):
    """Seeded on the session, so a rebuild reproduces it rather than reshuffling."""
    tf_engine.start(SESSION, game_type="true_false")
    first = tf_engine.state(SESSION).prompt.text
    tf_engine.quit(SESSION)

    fresh = GameEngine(
        games=[tf_game],
        store=InMemorySessionStore(3600.0),
        sink=MemoryEventSink(),
        settings=tf_settings,
        today=TODAY,
    )
    fresh.start(SESSION, game_type="true_false")
    assert fresh.state(SESSION).prompt.text == first


def test_the_prompt_offers_the_two_choices(tf_engine):
    tf_engine.start(SESSION, game_type="true_false")
    prompt = tf_engine.state(SESSION).prompt
    assert prompt.kind.value == "statement"
    assert prompt.choices == ("True", "False")


# --- volatility ------------------------------------------------------------


def test_a_volatile_item_with_no_verified_date_is_never_served(tf_engine, tf_game):
    """Item 3 of the ECCB bank is exactly this case."""
    stale = next(e for e in statements(tf_game) if e.id == "tf-stale")
    assert stale.volatility is Volatility.VOLATILE
    assert stale.verified_on is None

    served = set()
    for n in range(20):
        session = f"vol-{n}"
        tf_engine.start(session, game_type="true_false")
        while tf_engine.is_running(session):
            served.add(tf_engine.state(session).prompt.text)
            tf_engine.skip(session)
    assert stale.statement not in served


def test_a_volatile_item_is_servable_while_recently_verified():
    entry = StatementEntry(
        id="x",
        language=Language.EN,
        difficulty_band="core",
        persona_bands=(Persona.ORION,),
        statement="A rate.",
        answer=True,
        explanation="Because.",
        volatility=Volatility.VOLATILE,
        verified_on=TODAY - timedelta(days=30),
    )
    assert entry.servable_on(TODAY, review_days=180) is True


def test_a_volatile_item_goes_stale_after_the_review_window():
    entry = StatementEntry(
        id="x",
        language=Language.EN,
        difficulty_band="core",
        persona_bands=(Persona.ORION,),
        statement="A rate.",
        answer=True,
        explanation="Because.",
        volatility=Volatility.VOLATILE,
        verified_on=TODAY - timedelta(days=181),
    )
    assert entry.servable_on(TODAY, review_days=180) is False


def test_a_stable_definition_never_expires():
    entry = StatementEntry(
        id="x",
        language=Language.EN,
        difficulty_band="core",
        persona_bands=(Persona.ORION,),
        statement="Saving is keeping money for later.",
        answer=True,
        explanation="Because.",
        volatility=Volatility.STABLE,
        verified_on=None,
    )
    assert entry.servable_on(TODAY, review_days=180) is True


def test_a_set_of_only_stale_items_declines_rather_than_serving_them(
    tmp_path, tf_settings
):
    # tf_settings already seeded this tmp_path; overwrite what it wrote.
    folder = tmp_path / "en"
    folder.mkdir(parents=True, exist_ok=True)
    only_stale = FIXTURE_SET.split("  - id: tf-a")[0] + """  - id: tf-only
    statement: The rate is two percent.
    answer: true
    explanation: Set by someone else.
    topic: interest-rates
    difficulty_band: advanced
    persona_bands: [orion]
    volatility: volatile
"""
    (folder / "tf.yaml").write_text(only_stale, encoding="utf-8")
    settings = tf_settings.model_copy(update={"seed_dir": tmp_path})
    engine = GameEngine(
        games=[TrueFalseGame(settings)],
        store=InMemorySessionStore(3600.0),
        sink=MemoryEventSink(),
        settings=settings,
        today=TODAY,
    )
    with pytest.raises(NoContentAvailable):
        engine.start(SESSION, game_type="true_false")


# --- a full round ----------------------------------------------------------


def verdict_for(game: TrueFalseGame, statement_text: str) -> str:
    entry = next(e for e in statements(game) if e.statement == statement_text)
    return "true" if entry.answer else "false"


def wrong_for(game: TrueFalseGame, statement_text: str) -> str:
    return "false" if verdict_for(game, statement_text) == "true" else "true"


def test_a_correct_answer_teaches_and_moves_on(tf_engine, tf_game):
    tf_engine.start(SESSION, game_type="true_false")
    state = tf_engine.state(SESSION)
    result = tf_engine.submit(SESSION, verdict_for(tf_game, state.prompt.text))

    assert result.correct is True
    assert result.teaching_note
    assert result.reveal is not None
    assert result.next_prompt is not None
    assert result.next_prompt.position == 2


def test_a_wrong_answer_shows_the_explanation_and_does_not_re_ask(tf_engine, tf_game):
    """Re-asking a true/false is waiting for the coin to land the other way."""
    tf_engine.start(SESSION, game_type="true_false")
    state = tf_engine.state(SESSION)
    first = state.prompt.text

    result = tf_engine.submit(SESSION, wrong_for(tf_game, first))
    assert result.correct is False
    assert result.reveal is not None, "a wrong answer must still teach"
    assert result.teaching_note
    # Moved on, not re-asked.
    assert result.next_prompt is not None
    assert result.next_prompt.text != first


def test_an_unreadable_answer_leaves_the_statement_open(tf_engine):
    tf_engine.start(SESSION, game_type="true_false")
    before = tf_engine.state(SESSION)

    result = tf_engine.submit(SESSION, "yes")
    assert result.unreadable
    assert result.reveal is None
    assert result.correct is False

    after = tf_engine.state(SESSION)
    assert after.prompt.text == before.prompt.text, "the statement was spent"
    assert after.attempts == 0, "an unreadable answer is not an attempt"


def test_full_round_start_correct_incorrect_skip_complete(tf_engine, tf_game):
    tf_engine.start(SESSION, game_type="true_false")

    state = tf_engine.state(SESSION)
    assert state.prompt.total == 5

    # 1: correct
    tf_engine.submit(SESSION, verdict_for(tf_game, tf_engine.state(SESSION).prompt.text))
    # 2: an unreadable answer, then a wrong one
    tf_engine.submit(SESSION, "no")
    tf_engine.submit(SESSION, wrong_for(tf_game, tf_engine.state(SESSION).prompt.text))
    # 3: skipped
    tf_engine.skip(SESSION)
    # 4: correct
    tf_engine.submit(SESSION, verdict_for(tf_game, tf_engine.state(SESSION).prompt.text))
    # 5: correct, and that finishes the round
    last = tf_engine.submit(
        SESSION, verdict_for(tf_game, tf_engine.state(SESSION).prompt.text)
    )

    assert last.finished is True
    assert last.summary is not None
    assert last.summary.total == 5
    assert last.summary.solved == 3
    assert last.summary.missed == 1
    assert last.summary.skipped == 1
    assert tf_engine.state(SESSION) is None


# --- the shipped seed ------------------------------------------------------


def shipped_sets(settings: GameSettings):
    sets = load_sets(settings.resolved(settings.seed_dir), game_type="true_false")
    return [s for lang in Language for s in sets[lang]]


def test_the_eccb_set_stays_a_draft_until_its_content_lands(settings: GameSettings):
    """Placeholder copy must not be servable."""
    eccb = [s for s in shipped_sets(settings) if s.id == "truefalse-01"]
    assert eccb, "the ECCB true/false seed file did not load at all"
    assert all(s.draft for s in eccb), (
        "truefalse-01 is no longer a draft — every statement and explanation "
        "must be ECCB's verbatim text before this ships"
    )


def test_the_eccb_set_holds_sixteen_of_the_eighteen(settings: GameSettings):
    eccb = next(s for s in shipped_sets(settings) if s.id == "truefalse-01")
    assert len(eccb.entries) == 16, "expected 18 less the two malformed items"


def test_the_eccb_bank_stays_a_draft(settings: GameSettings):
    """The one that matters: `truefalse-01` still carries TODO explanations.

    This used to be written as an exact inventory of playable set ids, which
    made adding any authored set fail a test whose real subject is the ECCB
    bank. Flipping that file to `draft: false` must stay a deliberate act; a new
    sibling set must not.
    """
    eccb = next(s for s in shipped_sets(settings) if s.id == "truefalse-01")
    assert eccb.draft is True


def test_every_playable_set_is_authored_content(settings: GameSettings):
    playable = [s for s in shipped_sets(settings) if not s.draft]
    assert playable, "nothing is servable at all"
    assert "truefalse-01" not in {s.id for s in playable}
    for game_set in playable:
        assert game_set.source, f"{game_set.id}: no provenance"


def test_every_shipped_item_has_a_verdict_and_an_explanation(settings: GameSettings):
    entries = [e for s in shipped_sets(settings) for e in s.entries]
    assert entries
    for entry in entries:
        assert isinstance(entry.answer, bool), f"{entry.id}: verdict is not a bool"
        assert entry.explanation.strip(), f"{entry.id}: no explanation to teach from"
        assert entry.statement.strip(), f"{entry.id}: no statement"
        assert not entry.statement.rstrip().endswith("?")


def test_each_persona_gets_its_own_natively_written_set(settings: GameSettings):
    """Not a runtime simplification: a reworded statement is a new statement."""
    by_id = {s.id: s for s in shipped_sets(settings)}
    orion = by_id["truefalse-orion-01"]
    stella = by_id["truefalse-stella-01"]

    assert len(orion.entries) == len(stella.entries) == 5
    assert all(Persona.ORION in e.persona_bands for e in orion.entries)
    assert all(Persona.STELLA in e.persona_bands for e in stella.entries)
    # Same ideas, different words — never the same string.
    assert not {e.statement for e in orion.entries} & {
        e.statement for e in stella.entries
    }
    # Each carries its own closing, and a takeaway on every item.
    for game_set in (orion, stella):
        assert game_set.closing is not None
        assert all(e.takeaway for e in game_set.entries)
        assert all(e.paragraphs for e in game_set.entries)


def test_the_volatile_rate_item_is_gated(settings: GameSettings):
    sets = load_sets(settings.resolved(settings.seed_dir), game_type="true_false")
    entries = {e.id: e for lang in Language for s in sets[lang] for e in s.entries}
    rate = entries["tf-03-minimum-deposit-rate"]
    assert rate.volatility is Volatility.VOLATILE
    assert rate.verified_on is None, (
        "a verified_on date was added to the ECCU deposit rate — only do that "
        "when ECCB has confirmed the current figure"
    )
    assert rate.servable_on(date.today(), review_days=180) is False


# --- the verdict never leaves early ----------------------------------------


@pytest.fixture
def tf_client(tf_engine, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.games.router as router_module
    from app.games.router import router

    monkeypatch.setattr(router_module, "get_engine", lambda: tf_engine)
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


@pytest.fixture
def tf_tools(tf_engine, monkeypatch):
    from app.games import tools as tools_module

    monkeypatch.setattr(tools_module, "get_engine", lambda: tf_engine)
    return tools_module


def cfg(thread_id: str = SESSION):
    return {"configurable": {"thread_id": thread_id, "persona": None}}


def explanations(game: TrueFalseGame) -> list[str]:
    return [e.explanation for e in statements(game)]


def assert_no_explanations(payload, game, *, where: str):
    """An explanation names the verdict. Seeing one early is seeing the answer."""
    import json

    text = json.dumps(payload, default=str)
    for explanation in explanations(game):
        assert explanation not in text, f"{where} leaked an explanation: {payload}"


def test_the_state_schema_has_nowhere_to_put_a_verdict():
    from app.games.schemas import GameStateOut, PromptOut

    for forbidden in ("answer", "verdict", "correct", "explanation"):
        assert forbidden not in GameStateOut.model_fields
        assert forbidden not in PromptOut.model_fields


def test_the_api_never_returns_a_verdict_for_an_open_statement(
    tf_client, tf_game, tf_engine
):
    tf_client.post(
        "/api/games/start", json={"thread_id": SESSION, "game_type": "true_false"}
    )

    state = tf_client.get("/api/games/state", params={"thread_id": SESSION}).json()
    assert_no_explanations(state, tf_game, where="GET /state")
    # The two choices are offered; which one is right is not.
    assert state["game"]["prompt"]["choices"] == ["True", "False"]

    unreadable = tf_client.post(
        "/api/games/submit", json={"thread_id": SESSION, "answer": "yes"}
    ).json()
    assert unreadable["unreadable"]
    assert unreadable["reveal"] is None
    assert unreadable["teaching_note"] is None
    assert_no_explanations(unreadable, tf_game, where="submit(yes)")


def test_the_api_declines_a_hint_rather_than_narrowing_the_odds(tf_client):
    tf_client.post(
        "/api/games/start", json={"thread_id": SESSION, "game_type": "true_false"}
    )
    response = tf_client.post("/api/games/hint", json={"thread_id": SESSION})
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "hints_not_available"


def test_the_tools_never_hand_the_model_a_verdict_early(tf_tools, tf_game):
    started = tf_tools.start_game.invoke({"game_type": "true_false"}, config=cfg())
    assert started["ok"] is True
    assert started["kind"] == "statement"
    assert_no_explanations(started, tf_game, where="start_game")
    for forbidden in ("answer", "correct", "verdict", "explanation"):
        assert forbidden not in started

    unreadable = tf_tools.submit_answer.invoke({"answer": "no"}, config=cfg())
    assert unreadable["unreadable"]
    assert "revealed_answer" not in unreadable
    assert_no_explanations(unreadable, tf_game, where="submit_answer(no)")

    listed = tf_tools.list_games.invoke({}, config=cfg())
    assert_no_explanations(listed, tf_game, where="list_games")
    assert listed["games"][0]["supports_hints"] is False

    declined = tf_tools.get_hint.invoke({}, config=cfg())
    assert declined["ok"] is False
    assert declined["reason"] == "hints_not_available"
    assert_no_explanations(declined, tf_game, where="get_hint")


def test_the_verdict_arrives_only_with_the_item_it_belongs_to(tf_tools, tf_game):
    """And by then the engine has already moved past that statement."""
    tf_tools.start_game.invoke({"game_type": "true_false"}, config=cfg())
    resolved = tf_tools.skip_word.invoke({}, config=cfg())

    assert resolved["revealed"] is True
    assert resolved["answer"] in {"True", "False"}
    # Exactly one explanation — the resolved statement's, and no other.
    import json

    text = json.dumps(resolved)
    leaked = [e for e in explanations(tf_game) if e in text]
    assert len(leaked) == 1, f"expected one explanation, saw {len(leaked)}"


# --- loader rules specific to statements -----------------------------------


def _write(tmp_path, body: str):
    folder = tmp_path / "en"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tf.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_loader_rejects_a_statement_phrased_as_a_question(tmp_path):
    """Item 9 of the ECCB bank is exactly this."""
    body = FIXTURE_SET.replace(
        "statement: Saving means keeping money for later.",
        "statement: Is a good reason to budget that it puts you in control?",
    )
    with pytest.raises(SeedError, match="question mark"):
        load_sets(_write(tmp_path, body))


def test_loader_rejects_a_quoted_verdict(tmp_path):
    """`answer: "true"` is a string, and a string is not a verdict."""
    body = FIXTURE_SET.replace("answer: true", 'answer: "true"', 1)
    with pytest.raises(SeedError, match="must be true or false"):
        load_sets(_write(tmp_path, body))


def test_loader_rejects_a_statement_with_no_explanation(tmp_path):
    body = FIXTURE_SET.replace(
        "explanation: Keeping money now so you have it later. That is all saving is.",
        "explanation: ''",
    )
    with pytest.raises(SeedError, match="explanation is empty"):
        load_sets(_write(tmp_path, body))
