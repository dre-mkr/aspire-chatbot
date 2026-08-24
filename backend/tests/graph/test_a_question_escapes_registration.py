"""A guardian mid-application may ask a question without losing the form.

`apply_stickiness` grew an exit for a reader trapped inside a LESSON. An
application is not a lesson, so `active in TEACHING_AGENTS` never matched and a
guardian part-way through one had no exit at all.

Measured on aspire.eccugenai.app, 23 August 2026, signed out, guest persona:

    "I want to sign up"
        -> "And how are you related to the child?"
    "Are there tutorials to help me sign up my child?"
        -> "Pick the closest one -- mother, father, grandmother, grandfather,
           aunt, uncle, legal guardian, or other."
    "Grandmother"
        -> the tutorials answer, a turn late, and the relationship dropped

Her question was graded as a bad answer to the relationship slot. Because
nothing answered it, it stayed the salient question in the history -- so the
next turn answered it and threw away the relationship. The application could
move in neither direction.

The other half of this file matters just as much: what a registration form asks
for looks EXACTLY like the messages the teaching escape treats as bids to
leave. "I am her grandmother" is `i\\s+am`. "My child is seven" is
`my\\s+child`. Those are answers, and they must stay in the form.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.classify import (
    REGISTRATION_AGENTS,
    Classification,
    apply_stickiness,
)

ALLOWED = [*REGISTRATION_AGENTS, "qa_agent_public"]


def _state(active: str, message: str):
    return {
        "active_agent": active,
        "allowed_agents": ALLOWED,
        "session_id": "t",
        "messages": [type("M", (), {"type": "human", "content": message})()],
    }


def _weak(agent: str = "qa_agent_public") -> Classification:
    """A proposal well under the 0.75 stickiness threshold."""
    return Classification(agent=agent, confidence=0.30, reason="x")


class TestTheGuardianGetsAnAnswer:
    @pytest.mark.parametrize(
        "message",
        [
            "Are there tutorials to help me sign up my child?",
            "What documents do I need?",
            "How long does this take?",
            "Why do you need her birth certificate?",
            "Who can I call about this?",
            "Which branch is open on Saturday?",
            # The form is offered in three languages, so the exit must be too.
            "¿Qué documentos necesito?",
            "Combien de temps cela prend-il ?",
        ],
    )
    def test_a_question_is_not_read_as_a_slot_answer(self, message: str):
        out = apply_stickiness(_weak(), _state("register_agent_step1", message))
        assert out.agent == "qa_agent_public", (
            f"{message!r} was held in the form and graded as an answer"
        )
        assert not out.sticky


class TestTheFormKeepsWhatBelongsToIt:
    @pytest.mark.parametrize(
        "message",
        [
            # The reported turn: the relationship slot's own answer.
            "Grandmother",
            "Mother",
            "legal guardian",
            "Abuela",
            "Grand-mère",
            # `_ABOUT_THE_READER` matches every one of these. They are answers.
            "I am her grandmother",
            "I have two children",
            "My child is seven",
            "We are her legal guardians",
            # `_ASKS_SOMETHING` opens on `will`. This is a child's name.
            "Will",
            "Am",
            "Constance",
            # Free-text slots.
            "14 Cayon Street, Basseterre",
            "7",
        ],
    )
    def test_an_answer_stays_in_the_form(self, message: str):
        out = apply_stickiness(_weak(), _state("register_agent_step1", message))
        assert out.agent == "register_agent_step1", (
            f"{message!r} was let out of the form it was answering"
        )
        assert out.sticky


class TestTheExitIsStillEarned:
    def test_a_confident_proposal_never_needed_the_escape(self):
        strong = Classification(agent="qa_agent_public", confidence=0.95, reason="x")
        out = apply_stickiness(strong, _state("register_agent_step1", "Grandmother"))
        assert out.agent == "qa_agent_public"

    def test_the_question_decides_even_when_the_form_was_proposed(self):
        """The proposal is not the test. The question is.

        This is the reported turn exactly. Against the real classifier on
        23 August 2026 her question came back as

            register_agent@0.40 'asking for tutorials, not applying'

        -- the model had understood her, said so in its own reason, and still
        named an agent that cannot answer. An earlier version of this rule read
        `decision.agent not in REGISTRATION_AGENTS` and let that straight
        through, which is the whole defect surviving its own fix.
        """
        weak = _weak("register_agent")
        out = apply_stickiness(
            weak, _state("register_agent_step1", "What documents do I need?")
        )
        assert out.agent == "qa_agent_public"

    def test_there_is_no_exit_when_nothing_can_answer(self):
        state = _state("register_agent_step1", "What documents do I need?")
        state["allowed_agents"] = list(REGISTRATION_AGENTS)
        out = apply_stickiness(_weak("register_agent"), state)
        assert out.agent in REGISTRATION_AGENTS


class TestTheFormTakesItsAnswerBack:
    """The other half. See `_resume_registration`.

    Letting her out is only useful if she can get back in. Measured against the
    real classifier on 23 August 2026, with the tutorials question answered and
    the relationship slot still open, the reply the interface offers as a CHIP
    did not get her back:

        "Grandmother"           -> qa_agent_public  0.40
        "I am her grandmother"  -> register_agent   0.90

    One of those is a button in the product.
    """

    def _parked(self, message: str, awaiting: str = "guardian.relationship"):
        state = _state("qa_agent_public", message)
        state["registration"] = {"application_id": "a1", "filled": [], "awaiting": awaiting}
        return state

    @pytest.mark.parametrize(
        "message", ["Grandmother", "Mother", "legal guardian", "Abuela", "Will", "7"]
    )
    def test_a_weak_turn_goes_back_to_the_form(self, message: str):
        out = apply_stickiness(_weak(), self._parked(message))
        assert out.agent in REGISTRATION_AGENTS, (
            f"{message!r} left the guardian stranded in QA with the form open"
        )

    def test_a_question_is_still_answered_rather_than_swallowed(self):
        out = apply_stickiness(_weak(), self._parked("What documents do I need?"))
        assert out.agent == "qa_agent_public"

    def test_a_confident_change_of_subject_wins(self):
        strong = Classification(agent="games_agent", confidence=0.92, reason="x")
        state = self._parked("play a game")
        state["allowed_agents"] = [*ALLOWED, "games_agent"]
        out = apply_stickiness(strong, state)
        assert out.agent == "games_agent"

    def test_a_lesson_is_never_interrupted_by_a_waiting_form(self):
        """A quiz answer is not a question either. It must stay in the lesson."""
        state = _state("learn_agent", "Saving")
        state["allowed_agents"] = [*ALLOWED, "learn_agent"]
        state["registration"] = {"application_id": "a1", "filled": [], "awaiting": "guardian.relationship"}
        out = apply_stickiness(_weak(), state)
        assert out.agent == "learn_agent", "a waiting form pulled the reader out of a lesson"

    def test_nothing_happens_without_an_open_application(self):
        out = apply_stickiness(_weak(), _state("qa_agent_public", "Grandmother"))
        assert out.agent == "qa_agent_public"

    def test_nothing_happens_when_the_form_is_not_allowed(self):
        state = self._parked("Grandmother")
        state["allowed_agents"] = ["qa_agent_public"]
        out = apply_stickiness(_weak(), state)
        assert out.agent == "qa_agent_public"
