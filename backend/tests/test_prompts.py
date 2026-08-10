"""What the system prompt must and must not ask the assistant to do."""

from __future__ import annotations

import re

from app.prompts import ASPIRE_SYSTEM_PROMPT

#: The prompt is hard-wrapped for editing, so a phrase these tests care about is as likely to straddle a newline…
FLAT = " ".join(ASPIRE_SYSTEM_PROMPT.split()).lower()

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
    assert re.search(
        r"never mention when a record was checked", FLAT
    ), "the prompt no longer forbids repeating the record's date"


def test_the_uncertainty_rules_that_matter_are_still_there():
    """The date stamp went; the reasons it existed did not."""
    assert "if two rows disagree" in FLAT
    assert "do not quietly pick one" in FLAT
    assert "never present a figure as current when you cannot tell that it is" in FLAT


def test_the_prompt_forbids_narrating_the_search():
    """Answers must not report on where they came from."""
    assert "answer, do not narrate" in FLAT
    assert "never say where the answer came from" in FLAT
    assert "the published information says" in FLAT, (
        "the prompt no longer names the attribution phrasing it is banning"
    )
    assert "never add what you did not find to an answer you did give" in FLAT


def test_not_knowing_is_still_a_complete_answer():
    """The one case that DOES get spoken about, and must survive the rule above."""
    assert "when you genuinely cannot answer" in FLAT
    assert "i don't have that one" in FLAT
    assert "a guess is not" in FLAT
