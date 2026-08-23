"""A question is never scored as an answer to a quiz nobody started.

`apply_stickiness` makes a move INTO teaching exempt from the confidence
threshold and a move OUT of it subject to one. That asymmetry is deliberate and
right -- teaching is the flow this product is for. What it had no exit for was a
reader inside a lesson who asks about something else entirely: below the
threshold they stayed in the tutor, and the tutor read their question as an
attempt at its last check question.

Measured on aspire.eccugenai.app, 23 August 2026, signed out:

    Azuri  "What have you got for my Form 3 class?"
           -> "You move EC$25 into your account instead of spending it this
              week. What is that?"                    [Saving | Spending]

    Azuri  "What are my safeguarding obligations?"
           -> "Close. Ask yourself whether the money left your account or moved
              within it."                  [Let me try again | Show me the answer]

    Imani  "Is my money safe?"   -> the same EC$25 quiz question.

A teacher asking about child safeguarding was told "Close." Both adult personas
were worst hit, because a parent and a teacher ask the most questions that are
not lessons.
"""

from __future__ import annotations

import pytest

from app.graph.nodes.classify import (
    TEACHING_AGENTS,
    Classification,
    apply_stickiness,
)


def _state(active: str, message: str, allowed=None):
    return {
        "active_agent": active,
        "allowed_agents": allowed or list(TEACHING_AGENTS) + ["qa_agent_public"],
        "session_id": "t",
        "messages": [type("M", (), {"type": "human", "content": message})()],
    }


class TestAQuestionLeavesTheTutor:
    @pytest.mark.parametrize(
        "message",
        [
            "What are my safeguarding obligations?",
            "What have you got for my Form 3 class?",
            "Is my money safe?",
            "How do I register my daughter?",
            "Who funds ASPIRE?",
        ],
    )
    def test_the_reader_is_not_held_in_a_lesson(self, message: str):
        low = Classification(agent="qa_agent_public", confidence=0.30, reason="x")
        out = apply_stickiness(low, _state("learning_sample", message))
        assert out.agent == "qa_agent_public", (
            f"{message!r} was scored as a quiz answer"
        )

    @pytest.mark.parametrize(
        "message", ["Saving", "Spending", "true", "I think a loan", "EC$25", "b"]
    )
    def test_an_actual_answer_still_stays_in_the_lesson(self, message: str):
        """The lesson under way is protected exactly as before."""
        low = Classification(agent="qa_agent_public", confidence=0.30, reason="x")
        out = apply_stickiness(low, _state("learning_sample", message))
        assert out.agent == "learning_sample", (
            f"{message!r} is a quiz answer and must not leave the tutor"
        )

    def test_a_confident_proposal_still_wins_as_it_always_did(self):
        high = Classification(agent="qa_agent_public", confidence=0.95, reason="x")
        out = apply_stickiness(high, _state("learning_sample", "Saving"))
        assert out.agent == "qa_agent_public"

    def test_moving_into_teaching_is_still_never_held_back(self):
        """The original one-way exemption is untouched."""
        low = Classification(agent="learn_agent", confidence=0.10, reason="x")
        out = apply_stickiness(low, _state("qa_agent_public", "how does it grow?"))
        assert out.agent == "learn_agent"

    def test_a_question_between_two_teaching_agents_does_not_trigger_it(self):
        """The escape only fires when leaving teaching ALTOGETHER.

        learning_sample -> learn_agent is a move within teaching, so neither the
        into-teaching exemption (which needs the reader to be outside it) nor
        this escape applies. Ordinary stickiness decides, and at 0.10 it holds
        the lesson -- which is the behaviour that existed before this change and
        is untouched by it.
        """
        low = Classification(agent="learn_agent", confidence=0.10, reason="x")
        out = apply_stickiness(low, _state("learning_sample", "why does that work?"))
        assert out.agent == "learning_sample"

    def test_an_empty_message_is_not_treated_as_a_question(self):
        low = Classification(agent="qa_agent_public", confidence=0.30, reason="x")
        out = apply_stickiness(low, _state("learning_sample", "   "))
        assert out.agent == "learning_sample"
