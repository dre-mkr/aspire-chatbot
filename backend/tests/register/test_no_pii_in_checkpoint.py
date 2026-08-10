"""The checkpoint holds pointers."""

from __future__ import annotations

import json

import pytest

from app.agents.register.graph import PRESENT, _draft, _persist_state
from app.agents.register.schema import GUARDIAN_SLOTS
from app.agents.register.store import Draft

#: Values a completed guardian section would hold.
ANSWERS = {
    "guardian.full_name": "Marcia Weekes",
    "guardian.national_id": "A12345678",
    "guardian.date_of_birth": "1989-04-11",
    "guardian.phone": "869-555-0147",
    "guardian.email": "marcia@example.com",
    "guardian.address_line1": "12 Bay Road, Basseterre",
    "guardian.relationship": "mother",
    "child.0.full_name": "Ana Weekes",
    "child.0.date_of_birth": "2015-03-02",
}


def _filled_draft() -> Draft:
    draft = Draft(application_id="11111111-1111-1111-1111-111111111111", resume_token="tok-1")
    draft.values.update(ANSWERS)
    draft.values["__awaiting"] = "child.0.date_of_birth"
    return draft


def _serialised() -> str:
    """What actually reaches the blob table."""
    return json.dumps(_persist_state(_filled_draft()), default=str)


class TestNoAnswerReachesTheCheckpoint:
    @pytest.mark.parametrize(("slot", "value"), sorted(ANSWERS.items()))
    def test_no_collected_value_is_serialised(self, slot, value):
        assert value not in _serialised(), f"{slot} leaked its value into the checkpoint"

    def test_the_values_key_is_gone_entirely(self):
        """Not emptied -- absent."""
        assert "values" not in _persist_state(_filled_draft())

    def test_what_remains_is_pointers_and_scalars(self):
        persisted = _persist_state(_filled_draft())

        assert set(persisted) == {
            "application_id",
            "resume_token",
            "filled",
            "child_index",
            "children_complete",
            "status",
            "pending_corrections",
            "awaiting",
            # Slot keys the parent declined.
            "skipped",
        }

    def test_filled_carries_paths_not_answers(self):
        """"guardian.national_id" is a field name."""
        persisted = _persist_state(_filled_draft())

        assert "guardian.national_id" in persisted["filled"]
        assert "A12345678" not in json.dumps(persisted["filled"])

    def test_skipped_carries_keys_not_answers(self):
        """A decline is recorded as which field was declined, never as a value."""
        from app.agents.register import store

        draft = _filled_draft()
        draft.skipped = ["guardian.email", "child.0.school"]

        persisted = _persist_state(draft)

        assert persisted["skipped"] == ["guardian.email", "child.0.school"]
        assert "@" not in json.dumps(persisted["skipped"])

    def test_the_awaiting_pointer_is_a_path(self):
        assert _persist_state(_filled_draft())["awaiting"] == "child.0.date_of_birth"

    def test_internal_keys_are_not_published_as_filled_slots(self):
        """`__awaiting` is bookkeeping."""
        assert not any(
            path.startswith("__") for path in _persist_state(_filled_draft())["filled"]
        )


class TestTheRoundTripStillDrivesTheWalk:
    """Removing the values must not break the thing they were being kept for."""

    def test_a_rehydrated_draft_knows_which_slots_are_answered(self):
        state = {"registration": _persist_state(_filled_draft())}
        draft = _draft(state)

        for path in ANSWERS:
            assert draft.values.get(path) == PRESENT, f"{path} lost its filled status"

    def test_a_rehydrated_draft_holds_no_real_answer(self):
        state = {"registration": _persist_state(_filled_draft())}
        draft = _draft(state)

        blob = json.dumps(draft.values, default=str)
        for value in ANSWERS.values():
            assert value not in blob

    def test_the_walk_moves_past_answered_slots(self):
        """The presence map is enough for `next_missing`, which only ever asks whether a slot is empty."""
        from app.agents.register.graph import pick_slot

        state = {"registration": _persist_state(_filled_draft())}
        chosen = pick_slot(_draft(state))

        assert chosen is None or chosen.path not in ANSWERS

    def test_an_empty_draft_still_starts_at_the_first_slot(self):
        empty = Draft(application_id="22222222-2222-2222-2222-222222222222", resume_token="t")
        state = {"registration": _persist_state(empty)}

        from app.agents.register.graph import pick_slot

        assert pick_slot(_draft(state)).path == GUARDIAN_SLOTS[0].path

    def test_the_awaiting_pointer_survives_the_round_trip(self):
        """`extract` reads it to know which question is being answered."""
        state = {"registration": _persist_state(_filled_draft())}
        assert _draft(state).values.get("__awaiting") == "child.0.date_of_birth"
