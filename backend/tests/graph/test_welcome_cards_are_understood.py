"""A welcome card must send something the backend actually understands.

The card read "Tell me a story" and sent "Can I watch a story?". The first
phrase the story intent matched; the second it did not, because only the TELL
verbs were listed. So a child clicked a button labelled with a working phrase,
the product sent a different one, and Skye answered with a hint from a saving
lesson -- in French, which is how it was noticed.

The cards live in the frontend and the intents live here, so nothing connected
them. This reaches across the boundary on purpose: it is the only place the two
halves are compared, and a promise made on a button is worth as much as the
handler behind it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.graph.nodes import intents

CARDS = Path(__file__).parents[3] / "frontend/src/components/chat/ChatWelcome.tsx"


def _cards() -> list[tuple[str, str]]:
    """`(title, question)` for every welcome card, in file order."""
    if not CARDS.exists():  # pragma: no cover - a backend-only checkout
        pytest.skip("no frontend checkout beside this one")
    text = CARDS.read_text(encoding="utf-8")
    pairs = re.findall(
        r'title:\s*"([^"]+)".*?question:\s*"([^"]+)"', text, re.S
    )
    assert pairs, "no welcome cards found -- has the file been restructured?"
    return pairs


#: A card whose TITLE promises an activity, and the intent that must fire.
PROMISES = (
    (re.compile(r"\bstor(?:y|ies)\b|\btale\b", re.I), "story", intents.wants_story),
    (re.compile(r"\bgame\b|\bchallenge\b|\bplay\b", re.I), "game", intents.wants_game),
)


def test_there_are_cards_to_check():
    assert len(_cards()) >= 4


@pytest.mark.parametrize("title,question", _cards())
def test_a_card_that_promises_an_activity_sends_one(title: str, question: str):
    for pattern, name, understood in PROMISES:
        if not pattern.search(title):
            continue
        assert understood(question), (
            f"the card {title!r} promises a {name}, and sends {question!r}, "
            f"which `wants_{name}` does not match. The reader taps a button and "
            f"gets something else entirely."
        )


@pytest.mark.parametrize("title,question", _cards())
def test_no_card_sends_an_empty_or_stub_question(title: str, question: str):
    assert question.strip(), title
    assert len(question.strip()) > 4, f"{title!r} sends {question!r}"


def test_the_story_card_still_works_in_both_phrasings():
    """The two that matter: what the button says, and what it sends."""
    assert intents.wants_story("Tell me a story")
    assert intents.wants_story("Can I watch a story?")
