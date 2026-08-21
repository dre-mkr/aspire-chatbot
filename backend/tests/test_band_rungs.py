"""One key with two rungs must be two cards that actually differ.

`orion` spans 13 to 18 as one persona key and one label, but the six-persona
brief gives it two settings: tighter and about identity at 13-15, fuller and
about consequence at 16-18. Splitting the file was step one and it is already
done. This module is step two, and it exists because step one alone bought
nothing: for a while both files carried the WHOLE two-setting block and
differed only in a single line naming which rung they were, so the model
answering a fourteen-year-old was still reading the instruction written for a
seventeen-year-old, and the reverse.

A card is a prompt. Every line in it is read. A rung that names the other
rung's length has not been split, it has been labelled.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CARDS = Path(__file__).resolve().parents[1] / "app" / "prompting" / "personas"

YOUNGER = CARDS / "orion.13-15.md"
OLDER = CARDS / "orion.16-18.md"

#: The length target belonging to each rung, and the one that must not appear.
RUNGS = (
    pytest.param(YOUNGER, "120 words", "180 words", id="13-15"),
    pytest.param(OLDER, "180 words", "120 words", id="16-18"),
)


@pytest.mark.parametrize(("card", "mine", "theirs"), RUNGS)
def test_a_rung_states_its_own_length_target(card, mine, theirs):
    text = card.read_text(encoding="utf-8")
    assert mine in text, f"{card.name} no longer states its own length target"


@pytest.mark.parametrize(("card", "mine", "theirs"), RUNGS)
def test_a_rung_never_states_the_other_rungs_length(card, mine, theirs):
    """The failure this module was written for.

    Both files once carried both targets. A model has no way to know which of
    two numbers in front of it applies, so the split did nothing at all.
    """
    text = card.read_text(encoding="utf-8")
    assert theirs not in text, (
        f"{card.name} still names {theirs}, which belongs to the other rung. "
        "Two length targets in one prompt is the same as none."
    )


@pytest.mark.parametrize(("card", "mine", "theirs"), RUNGS)
def test_a_rung_says_the_other_one_is_a_separate_card(card, mine, theirs):
    """Not decoration. Without it the card reads as the whole persona, and the
    model fills the gap by inventing the range it thinks it covers."""
    text = card.read_text(encoding="utf-8")
    assert "SEPARATE CARD" in text


def test_the_two_rungs_are_not_the_same_card_with_one_line_changed():
    """The regression guard.

    Before the split these two files differed by exactly one line. If that ever
    returns, the persona has quietly gone back to one voice for a five-year age
    span -- and nothing else in the suite would notice.
    """
    younger = YOUNGER.read_text(encoding="utf-8").splitlines()
    older = OLDER.read_text(encoding="utf-8").splitlines()
    differing = sum(1 for a, b in zip(younger, older) if a != b)
    differing += abs(len(younger) - len(older))
    assert differing >= 4, (
        f"the two rung cards differ on {differing} line(s). They were written "
        "to be two voices; this is one voice with a label on it."
    )
