"""The "Explain it simply" control, end to end through the layers it touches.

This feature shipped as a no-op. The button rendered a convincing pressed state,
the setting persisted in the URL and survived navigation, and every layer from
the composer down to `streamAspire` carried the value correctly -- and then the
transport's destructure dropped it, so nothing ever crossed the wire.
`SIMPLE_MODE_INSTRUCTIONS` had been written for it and was imported by nothing.

So these tests are deliberately about the JOIN rather than about the wording:
each one pins a link that was, or could silently become, disconnected again.
"""

from __future__ import annotations

import pytest

from app.agents.qa.nodes import _simple_mode_instruction, _generation_messages
from app.cache import cache_key, semantic_shelf_key
from app.context.session_context import SessionContext
from app.graph.identity import CLIENT_FORBIDDEN_FIELDS, mint_session_token
from app.graph.nodes.hydrate import make_hydrate
from app.graph.state import KBChunk
from app.prompts import SIMPLE_MODE_INSTRUCTIONS


def _context(**overrides) -> SessionContext:
    fields = {
        "persona": "orion",
        "age_band": "13-15",
        "locale": "en",
        "account_status": "prospect",
    }
    fields.update(overrides)
    return SessionContext(**fields)


def _token() -> str:
    return mint_session_token(
        session_id="s-simple-mode",
        user_id=None,
        device_id="d-1",
        persona="orion",
        age_band="13-15",
        account_status="prospect",
        locale="en",
    )


class TestTheFlagReachesGraphState:
    """`hydrate` is the only node handed the raw body."""

    def test_a_body_flag_becomes_state(self):
        update = make_hydrate(_token(), {"message": "hi", "simple_mode": True})({})
        assert update["simple_mode"] is True

    def test_its_absence_is_false_and_not_missing(self):
        """A downstream `state.get("simple_mode")` must never read as None."""
        update = make_hydrate(_token(), {"message": "hi"})({})
        assert update["simple_mode"] is False

    def test_it_is_rewritten_every_turn(self):
        """Turning it off must take effect, not linger in the checkpoint."""
        update = make_hydrate(_token(), {"message": "hi", "simple_mode": False})(
            {"simple_mode": True}
        )
        assert update["simple_mode"] is False

    def test_it_is_not_an_identity_field(self):
        """It shapes an answer, so the body is allowed to set it."""
        assert "simple_mode" not in CLIENT_FORBIDDEN_FIELDS

    def test_it_does_not_trip_the_spoof_warning(self):
        update = make_hydrate(_token(), {"message": "hi", "simple_mode": True})({})
        assert not update["safety_flags"]


class TestTheInstructionReachesThePrompt:
    def test_off_adds_nothing(self):
        assert _simple_mode_instruction({}) is None
        assert _simple_mode_instruction({"simple_mode": False}) is None

    def test_on_carries_the_shared_wording(self):
        instruction = _simple_mode_instruction({"simple_mode": True})
        assert instruction is not None
        assert SIMPLE_MODE_INSTRUCTIONS.strip() in instruction

    def test_on_also_protects_what_a_grounded_answer_cannot_lose(self):
        """`ground_check` declines an answer with no citation."""
        instruction = _simple_mode_instruction({"simple_mode": True})
        assert "[ASP-xxx]" in instruction
        assert "not fewer facts" in instruction

    @pytest.mark.parametrize("flag", [True, False])
    def test_the_layered_prompt_carries_it_only_when_set(self, flag):
        state = {"context": _context(), "simple_mode": flag, "age_band": "13-15"}
        chunks = [KBChunk(kb_id="ASP-001", content="The seed is EC$500.", score=0.9)]
        rendered = "\n".join(str(m.content) for m in _generation_messages(state, "q", chunks))
        assert ("simplest possible explanation" in rendered) is flag

    def test_a_broken_context_still_honours_the_reader(self):
        """The fallback prompt is reached when the layers fail to build.

        That is a reason to lose the layering, not a reason to lose the request
        the reader actually made.
        """
        state = {"context": object(), "simple_mode": True, "age_band": "13-15"}
        chunks = [KBChunk(kb_id="ASP-001", content="The seed is EC$500.", score=0.9)]
        rendered = "\n".join(str(m.content) for m in _generation_messages(state, "q", chunks))
        assert "simplest possible explanation" in rendered


class TestTheCacheCannotServeTheWrongVersion:
    """The cache is consulted before anything is generated, so it decides this."""

    KEY = {
        "language": "en",
        "persona": "orion",
        "account_status": "prospect",
        "age_band": "13-15",
    }

    def test_simple_and_full_answers_get_different_keys(self):
        assert cache_key("what is aspire", **self.KEY, simple_mode=True) != cache_key(
            "what is aspire", **self.KEY, simple_mode=False
        )

    def test_the_ordinary_key_is_unchanged_by_the_new_field(self):
        """Existing entries stay valid: the flag is absent when it is false."""
        assert cache_key("what is aspire", **self.KEY) == cache_key(
            "what is aspire", **self.KEY, simple_mode=False
        )

    def test_the_semantic_shelf_is_separated_too(self):
        """Otherwise a near-paraphrase fetches the version that was turned off."""
        assert semantic_shelf_key(**self.KEY, simple_mode=True) != semantic_shelf_key(
            **self.KEY, simple_mode=False
        )
