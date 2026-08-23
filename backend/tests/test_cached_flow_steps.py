"""A position in a flow is not an answer, and must never be cached as one.

`cacheable` already refuses lessons and stories because each was written for the
reader who asked. A registration step is worse than either: it was not written
for a reader at all, it was written for a POSITION -- step two of a form. Served
to somebody who asked a different question it is a non-sequitur that also looks
like the assistant has quietly started collecting their details.

Observed on production, 23 August 2026. The classifier routed the bare question
"What is your name?" to `register_agent_step1`; the reply "And how are you
related to the child?" was cached against that question; and it was then served
from cache to five of the seven persona/band pairs. Skye at 5-8 was one of them,
so a five-year-old asking the guide's name was shown chips reading Mother,
Father, Grandmother, Grandfather. Reproduced 3/3 on fresh sessions.

The router misroute is a separate bug. This file defends the thing that made it
permanent: one bad classification, cached, becomes every future asker's answer
and survives the router being fixed.
"""

from __future__ import annotations

import pytest

from app.turn import LESSON_AGENTS, REGISTRATION_AGENTS, cacheable


class _Record:
    """The parts of a TurnRecord `cacheable` actually reads."""

    def __init__(self, agent: str, reply: str = "Some reply.", **kw):
        self.agent = agent
        self.reply = reply
        self.card = kw.get("card")
        self.story = kw.get("story")
        self.directives = kw.get("directives", [])


class TestRegistrationTurnsAreNeverReplayed:
    @pytest.mark.parametrize("agent", sorted(REGISTRATION_AGENTS))
    def test_a_registration_step_is_not_cacheable(self, agent: str):
        assert not cacheable(_Record(agent)), (
            f"{agent} replies are positions in a form. Cached, one misroute "
            f"becomes every future asker's answer."
        )

    def test_the_exact_reply_that_reached_a_five_year_old(self):
        record = _Record("register_agent_step1", "And how are you related to the child?")
        assert not cacheable(record)

    def test_both_registration_agents_are_covered(self):
        """Named explicitly: a third one added later must be added here too."""
        assert REGISTRATION_AGENTS == {"register_agent", "register_agent_step1"}

    def test_registration_and_lesson_sets_do_not_overlap(self):
        assert not (REGISTRATION_AGENTS & LESSON_AGENTS)

    def test_an_ordinary_answer_is_still_cacheable(self):
        """The guard must not have turned the cache off."""
        assert cacheable(_Record("qa_agent_public"))
        assert cacheable(_Record("qa_agent"))


class TestDeclineChipsStayTappable:
    """A chip is the offer. Half a question is not an offer.

    Observed the same day: a decline whose prose quoted the whole suggested
    question, over a chip reading "What is the best". The old implementation
    took `words[:4]` unconditionally.
    """

    @staticmethod
    def _chunk(title: str):
        class _C:
            def __init__(self, t): self.title = t
        return _C(title)

    def test_the_whole_question_reaches_the_chip(self):
        from app.agents.escalation.decline import decline_chips

        chips = decline_chips({}, [self._chunk("What is the best investment I can make?")])
        assert chips == ["What is the best investment I can make?"]

    def test_a_topic_missing_its_question_mark_gets_one(self):
        from app.agents.escalation.decline import decline_chips

        chips = decline_chips({}, [self._chunk("What is a contingency or rainy day fund")])
        assert chips == ["What is a contingency or rainy day fund?"]

    def test_no_chip_is_a_fragment(self):
        """The property, not the example: whatever comes back still asks something."""
        from app.agents.escalation.decline import decline_chips

        for title in (
            "What is the best investment I can make?",
            "Who funds the ASPIRE contributions?",
            "At what age can I register for my own ASPIRE account?",
        ):
            for chip in decline_chips({}, [self._chunk(title)]):
                assert chip.endswith("?"), f"{chip!r} is not a question"
                assert len(chip.split()) >= 4

    def test_a_topic_too_long_to_fit_is_dropped_not_cut(self):
        from app.agents.escalation.decline import decline_chips

        long = "A question so extraordinarily long that no chip could ever carry it anywhere at all?"
        assert decline_chips({}, [self._chunk(long)]) == []

    def test_no_topic_means_no_chip(self):
        from app.agents.escalation.decline import decline_chips

        assert decline_chips({}, []) == []
