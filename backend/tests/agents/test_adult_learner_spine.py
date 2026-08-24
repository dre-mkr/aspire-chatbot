"""The Adult Learner spine: a grown reader learning for themselves.

Distinct from the Educator Spine (`teacher`/`educator`). A teacher asks what to
do with a class; an adult learner asks what to do with their own money. Before
this, `ROLES` already admitted `learner` and `_ROLE_TO_AUDIENCE` mapped it, but
`_ROLE_INSTRUCTION` had no entry -- so an adult self-learner got no register at
all and fell through to whatever the persona defaulted to.

"Across the board": the register is chosen by the ROLE the reader is in, not by
their persona, so Guest, Imani (aurora) and Azuri (nova) all reach it when the
message says they are learning for themselves.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.agents.qa.nodes import _ROLE_INSTRUCTION, _role_instruction


def _routed(role: str):
    """A state whose router read `role` off this message."""
    return {"safety_flags": {"route": {"role": role}}, "messages": []}


class TestTheRegisterExists:
    def test_learner_has_its_own_register(self):
        assert "learner" in _ROLE_INSTRUCTION
        assert _role_instruction(_routed("learner"))

    def test_it_is_not_the_educator_register(self):
        assert _ROLE_INSTRUCTION["learner"] != _ROLE_INSTRUCTION["teacher"]
        assert _ROLE_INSTRUCTION["learner"] != _ROLE_INSTRUCTION["educator"]

    def test_every_role_still_resolves(self):
        for role in ("teacher", "educator", "parent", "learner"):
            assert _role_instruction(_routed(role)), role


class TestTheRegisterSaysWhatItShould:
    def test_it_speaks_to_behaviour_not_only_knowledge(self):
        text = _ROLE_INSTRUCTION["learner"].lower()
        assert "habit" in text or "behaviour" in text

    def test_it_refuses_to_gate_behind_a_quiz(self):
        text = _ROLE_INSTRUCTION["learner"].lower()
        assert "quiz" in text
        assert "adult" in text
