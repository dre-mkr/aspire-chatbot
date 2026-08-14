"""What the SHIPPED system prompt must and must not ask the assistant to do.

These tests used to assert against `app.prompts.ASPIRE_SYSTEM_PROMPT`, which
the v2 graph replaced and which nothing has composed since -- `app/main.py`
carries the tombstone: "The v1 turn pipeline lived here; the graph router at
/v2 replaced it." So every property below was being certified against a string
no reader has ever seen, and passing said nothing about the live service.

It was not harmless. Retargeted at the real prompt, one of them failed: the
live layers had no rule against narrating the search, and the deleted one did.
The symptom was in the judging transcript all along -- "The extracts only
explain that a capital gain is profit from selling an investment", which tells
the reader about the retrieval instead of answering them.

The prompt is composed from layers now, so the subject is the layers a QA turn
actually gets: the global rules plus the agent's role card.
"""

from __future__ import annotations

import re

from app.agents.qa.nodes import QA_AGENT_ROLE
from app.prompting.global_rules import GLOBAL

#: The prompt is hard-wrapped, so flatten whitespace before matching phrases
#: across newlines.
FLAT = " ".join(f"{GLOBAL}\n{QA_AGENT_ROLE}".split()).lower()

#: How the "last checked" stamp reads once the model has put it into prose.
DATE_STAMP = re.compile(
    r"say when it was last checked"
    r"|state when .{0,30}checked"
    r"|mention .{0,30}(?:last checked|as_of)"
    r"|include the (?:as_of|last checked)",
    re.IGNORECASE,
)


def test_the_prompt_does_not_ask_for_a_last_checked_date():
    """The assistant must not date-stamp its answers."""
    assert not DATE_STAMP.search(FLAT), (
        "the prompt asks the assistant to report when information was checked"
    )


def test_the_prompt_forbids_the_bookkeeping_date_explicitly():
    """Silence is not enough, because the date is still in front of the model."""
    assert "as_of" in FLAT
    assert "never mention when a record was checked" in FLAT, (
        "the prompt no longer forbids repeating the record's date"
    )


def test_the_uncertainty_rules_that_matter_are_still_there():
    """The date stamp went; the reasons it existed did not."""
    assert "two sources disagree" in FLAT
    assert "do not quietly pick a side" in FLAT
    assert "do not accept a premise you found no record of" in FLAT


def test_the_prompt_forbids_narrating_the_search():
    """
    Answers must not report on where they came from.

    This is the one that was being certified against dead text while the live
    prompt had no such rule at all.
    """
    assert "answer, do not narrate" in FLAT
    assert "never say where the answer came from" in FLAT
    assert "the extracts" in FLAT, (
        "the prompt no longer names the attribution phrasing it is banning"
    )
    assert "never add what you did not find to an answer you did give" in FLAT


def test_not_knowing_is_still_a_complete_answer():
    """The one case that DOES get spoken about, and must survive the rule above."""
    assert "i don't have that one" in FLAT
    assert "a guess is not" in FLAT


def test_the_grounding_rules_reach_a_qa_turn():
    """
    The role card is half of what a QA turn is told, so it is half of the subject.

    Asserting only against `GLOBAL` would miss the rules that make an answer
    citable, which is the property the whole eval harness is built on.
    """
    assert "answer only from the extracts" in FLAT
    assert "an answer with no citation will not be served" in FLAT
