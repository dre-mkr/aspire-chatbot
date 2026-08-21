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

import pytest

from app.agents.qa.nodes import QA_AGENT_ROLE, qa_agent_role
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


class TestEveryPersonaGetsTheGroundingRules:
    """The role card varies by persona now, so one variant is no longer the subject.

    `QA_AGENT_ROLE` used to be a single string and these tests certified it. It
    was also the strongest length instruction in the prompt -- "be thorough",
    "use every extract", "structure a longer answer" -- and it was persona-blind,
    so it argued with Stella's card and won. Splitting the depth half per persona
    is the fix; keeping the grounding half identical is the thing that must not
    quietly stop being true while the depth half moves.
    """

    PERSONAS = ["stella", "orion", "aurora", "nova", "guest"]

    @pytest.mark.parametrize("persona", PERSONAS)
    def test_the_grounding_rules_survive_every_variant(self, persona):
        flat = " ".join(qa_agent_role(persona).split()).lower()
        assert "answer only from the extracts" in flat
        assert "an answer with no citation will not be served" in flat
        assert "do not round, convert, average or infer one" in flat

    @pytest.mark.parametrize("persona", PERSONAS)
    def test_every_variant_still_says_what_depth_to_write_at(self, persona):
        assert "DEPTH AND COMPLETENESS" in qa_agent_role(persona)

    def test_an_unknown_persona_gets_the_fullest_card(self):
        """The safe direction for depth is more of it, not less."""
        assert qa_agent_role("not-a-persona") == qa_agent_role("nova")
        assert qa_agent_role(None) == qa_agent_role("nova")

    def test_the_depth_blocks_are_actually_different(self):
        """If these collapse, the persona work has silently been undone."""
        cards = {p: qa_agent_role(p) for p in self.PERSONAS}
        assert len(set(cards.values())) == len(self.PERSONAS)

    def test_the_child_card_does_not_ask_for_exceptions_and_conditions(self):
        """The specific instruction that was overriding Stella's eight-word card."""
        flat = " ".join(qa_agent_role("stella").split()).lower()
        assert "be thorough" not in flat
        assert "structure a longer answer" not in flat
        assert "not the conditions, not the exceptions" in flat

    def test_the_teacher_card_still_asks_for_the_exception(self):
        flat = " ".join(qa_agent_role("nova").split()).lower()
        assert "be thorough" in flat
        assert "state the exception" in flat
