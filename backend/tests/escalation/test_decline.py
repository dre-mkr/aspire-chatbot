"""The third outcome: decline twice, fetch a person on the third try."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.escalation import counter
from app.agents.escalation.decline import decline_chips, decline_text, nearest_topic
from app.agents.qa.nodes import make_ground_check
from app.graph.state import KBChunk, initial_state

pytestmark = pytest.mark.asyncio

#: Shaped like a real ingested row, which matters for one test below.
CHUNK = KBChunk(
    kb_id="ASP-070",
    title="Can a parent withdraw the child's savings?",
    content=(
        "ASP-070\nCategory: Savings\n"
        "Question: Can a parent or guardian withdraw the child's savings?\n"
        "Answer: No. Parents or guardians cannot withdraw funds."
    ),
    relevance=0.30,
    source="dense",
)
UNANSWERABLE = "can i get a loan against my childs aspire account"


def _state(question: str, *, streak=None, band="adult", persona="aurora", chunks=(CHUNK,)):
    state = initial_state(
        session_id="s-decline",
        user_id="u-1",
        device_id="d",
        persona=persona,
        age_band=band,
        account_status="guardian",
    )
    state["messages"] = [
        HumanMessage(content=question),
        AIMessage(content="An answer with no citation."),
    ]
    state["retrieved"] = list(chunks)
    state["decline_streak"] = streak or {}
    return state


async def _turn(node, question, streak, **kwargs):
    command = await node(_state(question, streak=streak, **kwargs))
    update = command.update or {}
    return update, getattr(command, "goto", None)


class TestTheFirstTwoAttemptsDecline:
    async def test_an_unanswerable_question_does_not_escalate(self):
        update, goto = await _turn(make_ground_check(), UNANSWERABLE, {})

        assert not goto
        assert "escalation_reason" not in update
        assert update["messages"][0].content

    async def test_the_decline_has_all_three_parts(self):
        """What we know, who holds the rest, something answerable."""
        text = decline_text(_state(UNANSWERABLE), [CHUNK])

        assert "do not have an answer" in text
        assert "ASPIRE team" in text
        assert CHUNK.title in text

    async def test_it_cites_nothing(self):
        """A decline is the absence of an attributable answer."""
        update, _ = await _turn(make_ground_check(), UNANSWERABLE, {})

        assert update["citations"] == []
        assert update["groundedness"] == 0.0

    async def test_the_offer_quotes_the_row_as_a_question(self):
        """Corpus titles ARE questions, so the template quotes them."""
        assert nearest_topic([CHUNK]) == CHUNK.title
        assert f'"{CHUNK.title}"' in decline_text(_state(UNANSWERABLE), [CHUNK])

    async def test_with_nothing_retrieved_no_topic_is_invented(self):
        text = decline_text(_state(UNANSWERABLE, chunks=()), [])

        assert "ASPIRE team" in text
        assert "ask me this one instead" not in text
        assert decline_chips(_state(UNANSWERABLE, chunks=()), []) == []

    async def test_it_does_not_invite_a_rephrase(self):
        """Inviting a retry invites the loop the counter exists to catch."""
        text = decline_text(_state(UNANSWERABLE), [CHUNK]).lower()

        for invitation in ("try again", "rephrase", "different words", "sorry"):
            assert invitation not in text


class TestTheThirdAttemptEscalates:
    async def test_three_turns_on_one_intent_reaches_a_person(self):
        node = make_ground_check()
        streak: dict = {}
        outcomes = []
        for _ in range(3):
            update, goto = await _turn(node, UNANSWERABLE, streak)
            streak = update.get("decline_streak", streak)
            outcomes.append(goto or "decline")

        assert outcomes == ["decline", "decline", "escalate_agent"]

    async def test_it_escalates_as_repeated_failure(self):
        node = make_ground_check()
        streak = {counter.intent_key(UNANSWERABLE): counter.LIMIT - 1}
        update, goto = await _turn(node, UNANSWERABLE, streak)

        assert goto == "escalate_agent"
        assert update["escalation_reason"] == "repeated_failure"
        assert update["escalation_summary"]

    async def test_the_streak_resets_on_escalation(self):
        """Left at the limit, every later turn on the same intent would open another ticket."""
        node = make_ground_check()
        streak = {counter.intent_key(UNANSWERABLE): counter.LIMIT - 1}
        update, goto = await _turn(node, UNANSWERABLE, streak)
        assert goto == "escalate_agent"
        assert update["decline_streak"] == {}

        after, goto_after = await _turn(node, UNANSWERABLE, update["decline_streak"])
        assert not goto_after
        assert after["decline_streak"] == {counter.intent_key(UNANSWERABLE): 1}

    async def test_changing_the_subject_resets_the_run(self):
        node = make_ground_check()
        streak: dict = {}
        for _ in range(2):
            update, _ = await _turn(node, UNANSWERABLE, streak)
            streak = update["decline_streak"]

        moved_on, goto = await _turn(node, "when is the application deadline", streak)

        assert not goto
        assert sum(moved_on["decline_streak"].values()) == 1


class TestBandAppropriateCopy:
    async def test_a_child_is_pointed_at_a_grown_up_not_a_website(self):
        text = decline_text(_state("what is saving", band="5-8", persona="stella"), [CHUNK])

        assert "grown-up" in text
        assert "aspire.gov.kn" not in text

    async def test_an_adult_gets_the_channels(self):
        text = decline_text(_state(UNANSWERABLE), [CHUNK])

        assert "aspire.gov.kn" in text

    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    async def test_every_shipped_locale_declines_in_its_own_words(self, locale):
        state = _state(UNANSWERABLE)
        state["locale"] = locale
        text = decline_text(state, [CHUNK])

        assert text
        assert "I do not have an answer" in text if locale == "en" else True

    async def test_an_unknown_locale_falls_back_to_english(self):
        state = _state(UNANSWERABLE)
        state["locale"] = "de"
        assert "I do not have an answer" in decline_text(state, [CHUNK])


class TestAGroundedAnswerIsUnaffected:
    async def test_a_cited_answer_still_returns_and_clears_the_streak(self):
        """The protected path."""
        node = make_ground_check()
        state = _state("can a parent withdraw the savings")
        state["messages"] = [
            HumanMessage(content="can a parent withdraw the savings"),
            AIMessage(content="No. Parents cannot withdraw funds [ASP-070]."),
        ]
        state["retrieved"] = [
            KBChunk(
                kb_id="ASP-070",
                title=CHUNK.title,
                content=CHUNK.content,
                relevance=0.80,
                source="dense",
            )
        ]
        state["decline_streak"] = {"whatever": 2}

        command = await node(state)
        update = command.update or {}

        assert not getattr(command, "goto", None)
        assert [citation.kb_id for citation in update["citations"]] == ["ASP-070"]
        assert update["groundedness"] > 0
        assert update["decline_streak"] == {}


class TestTheContactDetails:
    """
    The prompt has always said to offer ASPIRE's contact details and never to
    invent one, and never supplied any -- so a decline ended with a domain name
    and nothing else. `aspire.gov.kn, or any branch` was the whole answer to
    "who does know?".
    """

    async def test_an_adult_decline_names_a_channel_a_person_can_use(self):
        from app.config import get_settings

        settings = get_settings()
        text = decline_text(_state(UNANSWERABLE), [CHUNK])

        assert settings.aspire_contact_email in text
        assert settings.aspire_contact_phone in text
        assert settings.aspire_contact_website in text

    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    async def test_the_details_survive_every_locale(self, locale):
        from app.config import get_settings

        state = _state(UNANSWERABLE)
        state["locale"] = locale
        text = decline_text(state, [CHUNK])

        assert get_settings().aspire_contact_email in text, locale

    async def test_the_outbound_gate_does_not_redact_our_own_number(self):
        """
        The interaction that would have made this fix look like it worked.

        `pii._PHONE` matches `+1 (869) 667-5566` exactly and `_EMAIL` matches
        `aspire@gov.kn`, and `safety_out` redacts every prose answer -- so
        without an allowlist the decline would render "[a phone number]" and
        turn "here is who can help" into a dead end. Silently, and only once
        the gates actually affect delivered text.
        """
        from app.safety import pii

        text = decline_text(_state(UNANSWERABLE), [CHUNK])

        assert pii.redact(text) == text
        assert pii.kinds_in(text) == []

    async def test_a_reader_s_own_details_are_still_redacted(self):
        """The allowlist is ours only; it must not open the gate generally."""
        from app.safety import pii

        theirs = "Call me on +1 (869) 555-0123 or write to bea@example.com."

        assert "[a phone number]" in pii.redact(theirs)
        assert "[an email address]" in pii.redact(theirs)
