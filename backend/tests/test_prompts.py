"""What the system prompt must and must not ask the assistant to do.

Cheap, deterministic guards on prompt text. They do not call a model, so they
cannot prove the assistant complies -- only that the instruction it would be
complying with still says what we think it says. That is worth having on its
own: every behaviour in this file was changed by editing one sentence, and the
next person to edit that sentence should find out here rather than in a reply.
"""

from __future__ import annotations

import re

from app.prompts import ASPIRE_SYSTEM_PROMPT

#: The prompt is hard-wrapped for editing, so a phrase these tests care about is
#: as likely to straddle a newline as not. Every lookup below runs against this
#: rather than the raw text; without it the tests pass or fail on where the
#: paragraph happened to wrap, which is not a property worth guarding.
FLAT = " ".join(ASPIRE_SYSTEM_PROMPT.split()).lower()

#: How the "last checked" stamp reads once the model has put it into prose.
#: Matched loosely on purpose -- the instruction was reworded twice and came
#: back each time as a different phrasing of the same sentence.
DATE_STAMP = re.compile(
    r"say when it was last checked"
    r"|state when .{0,30}checked"
    r"|mention .{0,30}(?:last checked|as_of)"
    r"|include the (?:as_of|last checked)",
    re.IGNORECASE,
)


def test_the_prompt_does_not_ask_for_a_last_checked_date():
    """The assistant must not date-stamp its answers.

    Every reply used to end with "This information was last checked on 30 July
    2026." It came from one line in UNCERTAINTY telling the model to say when a
    row was last checked, fed by the `as_of` column that `ingest.row_to_document`
    writes into the retrieved text.

    The effect was the opposite of the intent. A hedge attached to every answer
    is not a hedge -- it reads as the assistant doubting facts that were never in
    question, and it buried the cases where confirming really does matter.
    """
    assert not DATE_STAMP.search(FLAT), (
        "the prompt asks the assistant to report when information was checked"
    )


def test_the_prompt_forbids_the_bookkeeping_date_explicitly():
    """Silence is not enough, because the date is still in front of the model.

    `as_of` remains in each row's `page_content`, so removing the instruction
    only stops the assistant being *told* to repeat it. An explicit prohibition
    is what stops it volunteering the date anyway, which it will otherwise do on
    exactly the questions the old rule targeted -- amounts, deadlines, rules.
    """
    assert "as_of" in FLAT
    assert re.search(
        r"never mention when a record was checked", FLAT
    ), "the prompt no longer forbids repeating the record's date"


def test_the_uncertainty_rules_that_matter_are_still_there():
    """The date stamp went; the reasons it existed did not.

    Two rows disagreeing, and a figure presented as current when it may not be,
    are real hazards and still have to be handled. This is here so that "stop
    stamping every answer" is not quietly widened into "stop flagging uncertainty
    at all".
    """
    assert "if two rows disagree" in FLAT
    assert "do not quietly pick one" in FLAT
    assert "never present a figure as current when you cannot tell that it is" in FLAT


def test_the_prompt_forbids_narrating_the_search():
    """Answers must not report on where they came from.

    The assistant was framing every reply as a description of its own lookup --
    "the published information does not say...", "it only confirms that..." --
    and following a complete answer with an inventory of what the records did not
    also cover. Both turn an answer into a status report on the knowledge base.
    """
    assert "answer, do not narrate" in FLAT
    assert "never say where the answer came from" in FLAT
    assert "the published information says" in FLAT, (
        "the prompt no longer names the attribution phrasing it is banning"
    )
    assert "never add what you did not find to an answer you did give" in FLAT


def test_not_knowing_is_still_a_complete_answer():
    """The one case that DOES get spoken about, and must survive the rule above.

    Suppressing commentary about the source must not suppress "I don't have
    that". It is the difference between an answer that is clean and one that is
    confidently wrong, so the exception is asserted as explicitly as the rule.
    """
    assert "when you genuinely cannot answer" in FLAT
    assert "i don't have that one" in FLAT
    assert "a guess is not" in FLAT
