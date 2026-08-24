"""The learn-vs-teach clarifier, for Azuri and Imani.

An educator or a parent who asks to be taught is ambiguous where a child is
not: they may be learning for themselves, or preparing to teach it to their
students or their own child. The clarifier asks once, remembers the answer for
the session, and resumes the original request so "for myself" does not become a
lesson topic in its own right.

Guest is deliberately never asked -- a signed-out adult has no third party to
teach, so their learning intent is taken at its word.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.qa.nodes import speaking_as
from app.graph.nodes.cards import make_intent_gate
from app.graph.state import initial_state

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


gate = make_intent_gate()


def _state(message, persona="nova", **overrides):
    state = initial_state(
        session_id="s-1", user_id="u-1", device_id="d-1",
        persona=persona, age_band="adult", account_status="active", locale="en",
    )
    state["messages"] = [HumanMessage(content=message)]
    state.update(overrides)
    return state


def _card(out):
    return (out.get("safety_flags") or {}).get("card")


class TestItAsksTheRightPeople:
    async def test_azuri_ambiguous_lesson_is_asked(self):
        out = await gate(_state("teach me about budgeting", persona="nova"))
        assert _card(out) == "learner_purpose"
        assert out["quick_replies"] == ["For myself", "To teach my students"]
        assert out.get("awaiting_learner_purpose") is True
        assert out.get("pending_learning") == "teach me about budgeting"

    async def test_imani_is_asked_about_her_child(self):
        out = await gate(_state("teach me about budgeting", persona="aurora"))
        assert _card(out) == "learner_purpose"
        assert out["quick_replies"] == ["For myself", "To help my child"]

    async def test_guest_is_never_asked(self):
        out = await gate(_state("teach me about budgeting", persona="guest"))
        assert _card(out) is None

    async def test_a_child_persona_is_never_asked(self):
        out = await gate(_state("teach me about budgeting", persona="stella"))
        assert _card(out) is None


class TestItDoesNotAskWhenItNeedNot:
    async def test_an_explicit_self_request_is_taken_at_its_word(self):
        out = await gate(_state("teach me about saving for myself", persona="nova"))
        assert _card(out) is None

    async def test_a_teaching_request_is_not_a_learning_one(self):
        # "how do I teach this to my Form 2s" is not `wants_lesson`; it never
        # reaches the clarifier and is answered as a teacher downstream.
        out = await gate(_state("how do I teach this to my Form 2s", persona="nova"))
        assert _card(out) is None

    async def test_a_plain_question_is_not_a_lesson(self):
        out = await gate(_state("what is compound interest", persona="nova"))
        assert _card(out) is None

    async def test_it_asks_only_once_per_session(self):
        out = await gate(
            _state("now teach me about saving", persona="nova", learner_purpose="self")
        )
        assert _card(out) is None


class TestItRemembersAndResumes:
    def _answering(self, reply, pending="teach me about budgeting", persona="nova"):
        state = initial_state(
            session_id="s-1", user_id="u-1", device_id="d-1",
            persona=persona, age_band="adult", account_status="active", locale="en",
        )
        state["messages"] = [
            HumanMessage(content=pending),
            AIMessage(content="Quick check..."),
            HumanMessage(content=reply),
        ]
        state["awaiting_learner_purpose"] = True
        state["pending_learning"] = pending
        return state

    async def test_for_myself_becomes_a_learner_and_resumes(self):
        out = await gate(self._answering("For myself"))
        assert out["learner_purpose"] == "self"
        assert out["awaiting_learner_purpose"] is False
        # the original request is resumed as the effective message
        assert out["messages"][-1].content == "teach me about budgeting"
        assert speaking_as({"learner_purpose": "self", "messages": []}) == "learner"

    async def test_teaching_answer_becomes_a_teacher(self):
        out = await gate(self._answering("To teach my students"))
        assert out["learner_purpose"] == "students"
        assert speaking_as({"learner_purpose": "students", "messages": []}) == "teacher"

    async def test_imani_helping_her_child_becomes_a_parent(self):
        out = await gate(self._answering("To help my child", persona="aurora"))
        assert out["learner_purpose"] == "child"
        assert speaking_as({"learner_purpose": "child", "messages": []}) == "parent"

    async def test_an_unrelated_reply_abandons_rather_than_resumes(self):
        out = await gate(
            self._answering("actually what is the ASPIRE grant and who is eligible for it")
        )
        assert out["awaiting_learner_purpose"] is False
        # no resumed human message: the new question is left to flow as itself
        assert not any(getattr(m, "type", None) == "human" for m in out.get("messages", []))


class TestTheRememberedAnswerRanksCorrectly:
    async def test_this_turns_role_beats_a_remembered_one(self):
        # Remembered "self", but the message today is plainly teaching.
        state = {
            "learner_purpose": "self",
            "messages": [HumanMessage(content="how do I teach compound interest to my Form 2s")],
            "safety_flags": {"route": {"role": "teacher"}},
        }
        assert speaking_as(state) == "teacher"
