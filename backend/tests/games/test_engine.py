"""The engine: state, scoring, and the hint ladder."""

from __future__ import annotations

import pytest

from app.games.engine import (
    GameAlreadyRunning,
    GameNotRunning,
    NoContentAvailable,
    PersonaNotEligible,
    UnknownGameType,
)
from app.games.events import (
    GAME_COMPLETED,
    GAME_STARTED,
    HINT_USED,
    WORD_SKIPPED,
    WORD_SOLVED,
)
from app.games.models import Language, Persona
from app.games.normalise import normalise

# Matches the value in conftest; kept local because tests/ is not a package.
SESSION = "thread-under-test"

# Seed order, which is the ECCB handout's order.
WORDS = ["MONEY", "INTEREST", "INVEST", "SAVE"]


def test_start_serves_the_first_scramble(engine):
    result = engine.start(SESSION)
    assert result.game_type == "word_scramble"
    assert result.prompt.text == "NOEYM"
    assert result.prompt.position == 1
    assert result.prompt.total == 4


def test_start_twice_is_refused(engine):
    engine.start(SESSION)
    with pytest.raises(GameAlreadyRunning):
        engine.start(SESSION)


def test_operations_need_a_running_game(engine):
    for call in (
        lambda: engine.submit(SESSION, "money"),
        lambda: engine.hint(SESSION),
        lambda: engine.skip(SESSION),
        lambda: engine.quit(SESSION),
    ):
        with pytest.raises(GameNotRunning):
            call()


def test_unknown_game_type_is_refused(engine):
    with pytest.raises(UnknownGameType):
        engine.start(SESSION, game_type="sudoku")


def test_language_without_a_set_is_refused(store, sink, settings):
    """Better no puzzle than a wrong one.

    Built on `hangman` rather than the shared `engine` fixture, which is word
    scramble: Spanish and French are no longer empty everywhere. `true_false`
    and `word_scramble` are authored in both, so asked of either this would
    assert nothing. Hangman is still English only and is the honest subject.
    """
    from app.games.engine import GameEngine
    from app.games.hangman import HangmanGame

    only_hangman = GameEngine(
        games=[HangmanGame(settings)], store=store, sink=sink, settings=settings
    )
    for language in (Language.ES, Language.FR):
        with pytest.raises(NoContentAvailable):
            only_hangman.start(SESSION, language=language, game_type="hangman")


# --- persona gate ----------------------------------------------------------


@pytest.mark.parametrize("persona", [Persona.STELLA, Persona.ORION])
def test_account_holders_can_play(engine, persona):
    assert engine.start(SESSION, persona=persona).prompt.text == "NOEYM"


@pytest.mark.parametrize("persona", [Persona.AURORA, Persona.NOVA])
def test_a_guardian_or_teacher_may_now_play(engine, persona):
    """These two used to raise, which made any "play a game" control a button
    that could not work for a third of the voices.

    Offering is still not allowing: Imani never raises an activity unprompted
    and Azuri is evaluating rather than playing, and both cards say so. But
    asked directly, the engine hands one over rather than refusing.
    """
    assert engine.start(SESSION, persona=persona) is not None


def test_unknown_persona_may_play(engine):
    """Unknown is not the same as ineligible."""
    assert engine.start(SESSION, persona=None).prompt.total == 4


# --- answering -------------------------------------------------------------


def test_a_correct_answer_teaches_and_advances(engine):
    engine.start(SESSION)
    result = engine.submit(SESSION, "money")

    assert result.correct is True
    assert result.teaching_note == "what we use to buy the things we need"
    assert result.next_prompt is not None
    assert result.next_prompt.text == "STERINTE"
    assert result.next_prompt.position == 2


def test_a_wrong_answer_holds_position_and_says_nothing_else(engine):
    engine.start(SESSION)
    result = engine.submit(SESSION, "banana")

    assert result.correct is False
    assert result.attempts == 1
    assert result.teaching_note is None
    assert result.next_prompt is None
    # Still on word one.
    assert engine.submit(SESSION, "money").correct is True


def test_attempts_accumulate_then_reset_on_the_next_word(engine):
    engine.start(SESSION)
    engine.submit(SESSION, "wrong")
    assert engine.submit(SESSION, "wrong again").attempts == 2
    assert engine.submit(SESSION, "money").attempts == 3
    # New word, fresh count.
    assert engine.submit(SESSION, "nope").attempts == 1


# --- hints -----------------------------------------------------------------


def test_hints_climb_three_rungs_then_reveal(engine):
    engine.start(SESSION)

    first = engine.hint(SESSION)
    assert first.level == 1
    assert first.text == "It starts with M."
    assert first.reveal is None

    second = engine.hint(SESSION)
    assert second.level == 2
    assert second.text.startswith("5 letters —")
    assert second.reveal is None

    third = engine.hint(SESSION)
    assert third.level == 3
    assert third.text == "what we use to buy the things we need."
    assert third.reveal is None

    # A fourth ask is not a hint; it is a child who has had enough.
    fourth = engine.hint(SESSION)
    assert fourth.reveal is not None
    assert fourth.reveal.answer == "MONEY"
    assert fourth.reveal.explanation
    assert fourth.next_prompt is not None
    assert fourth.next_prompt.text == "STERINTE"


def test_no_hint_ever_contains_the_answer(engine, game):
    for game_set in game.sets_for(Language.EN):
        for entry in game_set.entries:
            for level in (1, 2, 3):
                text = game.hint(entry, level)
                assert normalise(entry.word) not in normalise(text), (
                    f"{entry.id} hint level {level} contains the answer"
                )


def test_hints_are_counted_but_do_not_block_solving(engine):
    engine.start(SESSION)
    engine.hint(SESSION)
    engine.hint(SESSION)
    result = engine.submit(SESSION, "money")
    assert result.correct is True


# --- skipping and finishing ------------------------------------------------


def test_skip_reveals_teaches_and_moves_on(engine):
    engine.start(SESSION)
    result = engine.skip(SESSION)

    assert result.reveal.answer == "MONEY"
    assert result.reveal.explanation == "what we use to buy the things we need"
    assert result.next_prompt.text == "STERINTE"
    assert result.finished is False


def test_a_revealed_word_is_no_longer_scorable(engine):
    """The cursor moves in the same call that reveals."""
    engine.start(SESSION)
    revealed = engine.skip(SESSION).reveal.answer
    # Submitting the word we were just given now grades against the NEXT word.
    assert engine.submit(SESSION, revealed).correct is False


def test_full_lifecycle_start_hint_solve_skip_complete(engine, sink):
    engine.start(SESSION)

    engine.hint(SESSION)  # MONEY
    assert engine.submit(SESSION, "MONEY").correct is True
    assert engine.submit(SESSION, "  interest.  ").correct is True  # INTEREST
    engine.skip(SESSION)  # INVEST given up

    final = engine.submit(SESSION, "savve")  # SAVE, with a held key
    assert final.correct is True
    assert final.finished is True
    assert final.summary is not None
    assert final.summary.solved == 3
    assert final.summary.skipped == 1
    assert final.summary.total == 4
    assert final.summary.hints_used == 1

    # The session is gone; the game is over.
    with pytest.raises(GameNotRunning):
        engine.submit(SESSION, "anything")

    assert sink.names() == [
        GAME_STARTED,
        HINT_USED,
        WORD_SOLVED,
        WORD_SOLVED,
        WORD_SKIPPED,
        WORD_SOLVED,
        GAME_COMPLETED,
    ]


def test_quitting_ends_it_immediately(engine, sink):
    engine.start(SESSION)
    engine.submit(SESSION, "money")

    summary = engine.quit(SESSION)
    assert summary.solved == 1
    assert summary.total == 4

    with pytest.raises(GameNotRunning):
        engine.hint(SESSION)

    completed = [e for e in sink.events if e.event == GAME_COMPLETED]
    assert completed[-1].data["reason"] == "quit"


def test_skipping_everything_still_completes_cleanly(engine):
    engine.start(SESSION)
    for _ in range(3):
        assert engine.skip(SESSION).finished is False
    last = engine.skip(SESSION)
    assert last.finished is True
    assert last.summary.skipped == 4
    assert last.summary.solved == 0


# --- events ----------------------------------------------------------------


def test_events_carry_what_gamification_will_need(engine, sink):
    engine.start(SESSION, persona=Persona.STELLA)
    engine.submit(SESSION, "money")

    solved = next(e for e in sink.events if e.event == WORD_SOLVED)
    payload = solved.as_dict()
    for key in (
        "session_id",
        "persona",
        "language",
        "game_type",
        "timestamp",
        "elapsed_seconds",
        "entry_id",
        "attempts",
        "hints_used",
        "first_try",
    ):
        assert key in payload, f"event is missing {key!r}"
    assert payload["persona"] == "stella"
    assert payload["first_try"] is True


def test_events_record_no_answer_value(engine, sink, all_words):
    """Events reference a word by id, never by value."""
    engine.start(SESSION)
    engine.hint(SESSION)
    engine.submit(SESSION, "money")
    engine.skip(SESSION)
    engine.quit(SESSION)

    assert sink.events
    for event in sink.events:
        payload = event.as_dict()
        for forbidden in ("word", "answer", "definition", "scramble", "reveal"):
            assert forbidden not in payload, (
                f"{event.event} carries a {forbidden!r} field"
            )

        # And no value anywhere is an answer, entry_id excepted.
        values = normalise(
            str({k: v for k, v in payload.items() if k != "entry_id"})
        )
        for word in all_words:
            assert normalise(word) not in values, (
                f"{event.event} leaked {word!r} into the event stream"
            )
