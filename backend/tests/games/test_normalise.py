"""Answer checking."""

from __future__ import annotations

import pytest

from app.games.normalise import answer_matches, letters_of, levenshtein, normalise

TOLERANCE = {"typo_tolerance_min_length": 6, "max_edits": 1}


@pytest.mark.parametrize(
    "typed",
    [
        "SAVE",
        "save",
        "Save",
        "  save  ",
        "save.",
        "save!",
        "'save'",
        "s a v e",
        "\tsave\n",
    ],
)
def test_case_whitespace_and_punctuation_are_forgiven(typed):
    assert answer_matches(typed, "SAVE", **TOLERANCE)


@pytest.mark.parametrize(
    ("typed", "target"),
    [
        ("interes", "INTERÉS"),
        ("INTERÉS", "INTERÉS"),
        ("interés", "INTERES"),
        ("interet", "INTÉRÊT"),
        ("intérêt", "INTERET"),
        ("ano", "AÑO"),
    ],
)
def test_accents_fold_both_ways(typed, target):
    """A keyboard without accents is not a wrong answer."""
    assert answer_matches(typed, target, **TOLERANCE)


@pytest.mark.parametrize("typed", ["savve", "saave", "savee", "moneyy"])
def test_a_held_key_is_forgiven_at_any_length(typed):
    """The brief's own example: `savve` is a four-letter word with a doubled key."""
    target = "MONEY" if typed.startswith("m") else "SAVE"
    assert answer_matches(typed, target, **TOLERANCE)


@pytest.mark.parametrize("typed", ["interrest", "intereest", "interst"])
def test_one_typo_is_forgiven_on_a_long_word(typed):
    assert answer_matches(typed, "INTEREST", **TOLERANCE)


@pytest.mark.parametrize("typed", ["safe", "cave", "gave", "wave", "sane"])
def test_a_different_short_word_is_not_a_typo(typed):
    """All are one edit from SAVE, and all are words a child might mean."""
    assert not answer_matches(typed, "SAVE", **TOLERANCE)


def test_a_plural_of_a_long_word_is_accepted():
    """`interests` is one edit from INTEREST, and the child clearly solved it."""
    assert answer_matches("interests", "INTEREST", **TOLERANCE)


@pytest.mark.parametrize("typed", ["invest", "interesting", "int", "interested"])
def test_near_misses_on_a_long_word_are_rejected(typed):
    assert not answer_matches(typed, "INTEREST", **TOLERANCE)


@pytest.mark.parametrize("typed", ["", "   ", "!!!", "?"])
def test_empty_and_punctuation_only_answers_are_wrong(typed):
    assert not answer_matches(typed, "SAVE", **TOLERANCE)


def test_the_scramble_itself_is_not_the_answer():
    """Typing the puzzle back is not solving it."""
    assert not answer_matches("EASV", "SAVE", **TOLERANCE)
    assert not answer_matches("NOEYM", "MONEY", **TOLERANCE)


def test_tolerance_can_be_switched_off():
    assert not answer_matches(
        "interrest", "INTEREST", typo_tolerance_min_length=6, max_edits=0
    )
    assert answer_matches(
        "interest", "INTEREST", typo_tolerance_min_length=6, max_edits=0
    )


# --- primitives ------------------------------------------------------------


def test_normalise_strips_everything_that_is_not_a_letter_or_digit():
    assert normalise("  Sa-ve!  ") == "save"
    assert normalise("MONEY") == "money"


def test_levenshtein_gives_up_past_the_cutoff():
    assert levenshtein("save", "save", max_edits=1) == 0
    assert levenshtein("save", "safe", max_edits=1) == 1
    # Far apart: reported as over the cutoff rather than computed exactly.
    assert levenshtein("save", "interest", max_edits=1) == 2


def test_letters_of_is_order_insensitive():
    assert letters_of("EASV") == letters_of("SAVE")
    assert letters_of("STERINTE") == letters_of("INTEREST")
    assert letters_of("SAVE") != letters_of("SAVES")
