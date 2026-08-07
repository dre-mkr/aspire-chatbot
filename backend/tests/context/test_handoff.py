"""A handoff carries facts, and the receiver cannot re-ask what it was given.

C.3. The QA-to-registration handoff passed `active_agent` and nothing else
(`agents/qa/tools.py:308`), so the receiving agent restarted its slot walk from
the top with no knowledge of anything already said.

The enforcement tests are the ones that matter. `do_not_reask` is required to be
structural: not an instruction in a prompt that the slot loop never reads, but a
value the loop cannot produce.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.handoff import Handoff, filter_slots, from_state, to_state
from app.agents.register.graph import pick_slot
from app.agents.register.schema import GUARDIAN_SLOTS, next_missing
from app.agents.register.store import Draft


def _handoff(**overrides) -> Handoff:
    fields = {
        "from_agent": "qa_agent",
        "reason": "the reader asked to apply",
        "user_intent": "register my daughter for ASPIRE",
        "facts_established": {"relationship": "mother", "parish": "Saint George"},
        "do_not_reask": ["guardian.relationship"],
    }
    fields.update(overrides)
    return Handoff(**fields)


def _draft() -> Draft:
    return Draft(application_id="APP-1", resume_token="tok")


class TestTheContract:
    def test_every_field_is_required(self):
        for missing in ("from_agent", "reason", "user_intent"):
            fields = {
                "from_agent": "qa_agent",
                "reason": "r",
                "user_intent": "i",
            }
            fields.pop(missing)
            with pytest.raises(ValidationError):
                Handoff(**fields)  # type: ignore[arg-type]

    def test_it_is_frozen_and_forbids_extras(self):
        handoff = _handoff()
        with pytest.raises(ValidationError):
            handoff.reason = "something else"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            Handoff(from_agent="a", reason="r", user_intent="i", priority="high")  # type: ignore[call-arg]

    def test_it_survives_a_checkpoint_round_trip(self):
        handoff = _handoff()
        state = {"safety_flags": {}}
        state.update(to_state(handoff, state))

        assert from_state(state) == handoff

    def test_an_unusable_payload_is_discarded_rather_than_raised(self):
        """A handoff that has been through a checkpoint has not been through the
        validator. A malformed one must not kill the turn."""
        assert from_state({"safety_flags": {"handoff": {"nonsense": True}}}) is None
        assert from_state({"safety_flags": {}}) is None


class TestFactsCannotCarryPII:
    """A handoff is checkpointed, which is FINDINGS.md F1's failure surface."""

    @pytest.mark.parametrize(
        "key",
        [
            "guardian.national_id",
            "guardian.date_of_birth",
            "child.0.full_name",
            "dob",
            "guardian.address_line1",
            "birth_certificate",
            "guardian.phone",
        ],
    )
    def test_pii_shaped_keys_are_refused(self, key):
        with pytest.raises(ValidationError, match="looks like PII"):
            _handoff(facts_established={key: "whatever"})

    def test_ordinary_facts_are_allowed(self):
        handoff = _handoff(
            facts_established={
                "relationship": "mother",
                "parish": "Saint George",
                "child_count": 2,
                "already_has_account": False,
            }
        )
        assert handoff.facts_established["child_count"] == 2


class TestDoNotReaskIsStructural:
    """The acceptance clause: enforced in code, never in a prompt."""

    def test_a_barred_slot_is_never_offered(self):
        barred = "guardian.relationship"
        without = pick_slot(_draft(), handoff=_handoff(do_not_reask=[barred]))

        assert without is not None
        assert without.path != barred

    def test_the_same_slot_IS_offered_without_a_handoff(self):
        """Proves the previous test is measuring the filter and not slot order."""
        paths = []
        draft = _draft()
        for _ in range(len(GUARDIAN_SLOTS)):
            slot = pick_slot(draft)
            if slot is None:
                break
            paths.append(slot.path)
            draft.values[slot.path] = "answered"

        assert "guardian.relationship" in paths

    def test_the_walk_continues_past_a_barred_slot(self):
        """A withheld slot must not end the application. The first draft of this
        filtered after the walk and wrote a sentinel into `draft.values` to get
        past one -- which `_persist_state` would have checkpointed and `submit`
        would have sent as a real answer."""
        draft = _draft()
        handoff = _handoff(do_not_reask=["guardian.relationship"])

        asked = []
        for _ in range(len(GUARDIAN_SLOTS) + 2):
            slot = pick_slot(draft, handoff=handoff)
            if slot is None:
                break
            asked.append(slot.path)
            draft.values[slot.path] = "answered"

        assert "guardian.relationship" not in asked
        assert len(asked) >= 2, "the walk stopped instead of skipping"
        assert "__established_elsewhere" not in draft.values.values()
        assert not any(str(v).startswith("__") for v in draft.values.values())

    def test_barring_everything_ends_the_walk_cleanly(self):
        every = [slot.path for slot in GUARDIAN_SLOTS]
        draft = _draft()
        slot = pick_slot(draft, handoff=_handoff(do_not_reask=every))

        # Guardian section exhausted, so the walk moves to the child section
        # rather than returning None or looping.
        assert slot is None or slot.path.startswith("child.")

    def test_next_missing_takes_the_barred_set_directly(self):
        """The enforcement lives inside the walk, not around it."""
        first = next_missing({}, barred=frozenset())
        barred_first = next_missing({}, barred=frozenset({first.path}))

        assert barred_first is not None
        assert barred_first.path != first.path

    def test_filter_slots_passes_through_objects_with_no_path(self):
        """Its job is removing named slots, not filtering arbitrary objects.
        Silently dropping something it did not understand would be the worse bug.
        """
        sentinel = object()
        assert filter_slots([sentinel], _handoff(do_not_reask=["anything"])) == [sentinel]

    def test_no_handoff_means_no_filtering(self):
        assert len(filter_slots(GUARDIAN_SLOTS, None)) == len(GUARDIAN_SLOTS)
