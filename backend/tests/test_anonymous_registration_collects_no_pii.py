"""An unauthenticated caller must never be asked for PII."""

from __future__ import annotations

import pytest

from app.agents.register.schema import (
    CHILD_SLOTS,
    GUARDIAN_SLOTS,
    SLOTS,
    child_key,
    next_missing,
)


def _walk(*, allow_sensitive: bool) -> list[str]:
    """Every slot the walk asks for, filling each as it goes."""
    filled: dict[str, object] = {}
    asked: list[str] = []
    for _ in range(len(SLOTS) + 5):
        slot = next_missing(filled, allow_sensitive=allow_sensitive)
        if slot is None:
            break
        key = child_key(slot.path, 0) if slot.path.startswith("child.") else slot.path
        assert key not in filled, f"{slot.path} asked twice; the walk is not advancing"
        asked.append(slot.path)
        filled[key] = "x"
    else:
        pytest.fail("the walk never completed")
    return asked


def test_the_anonymous_walk_never_asks_for_a_sensitive_slot():
    """The whole finding, in one assertion."""
    from app.agents.register.schema import slot_for

    for path in _walk(allow_sensitive=False):
        slot = slot_for(path)
        assert slot is not None and not slot.sensitive, (
            f"{path} is marked sensitive and was asked of an unauthenticated "
            "caller, who is band 5-8 by default"
        )


def test_full_name_and_national_id_are_the_two_that_regressed():
    """Named explicitly, because these are the two the repro actually saw."""
    asked = _walk(allow_sensitive=False)
    assert "guardian.full_name" not in asked
    assert "guardian.national_id" not in asked


def test_the_authenticated_walk_still_collects_everything():
    """The fix must not have quietly broken registration for a signed-in guardian."""
    asked = _walk(allow_sensitive=True)
    for required in ("guardian.full_name", "guardian.national_id", "guardian.date_of_birth"):
        assert required in asked, f"{required} is no longer collected from a guardian"


def test_the_anonymous_walk_still_collects_something():
    """A filter that returned nothing would 'pass' the test above vacuously."""
    asked = _walk(allow_sensitive=False)
    assert asked, "the anonymous walk collects nothing at all, which is not the intent"
    assert "guardian.relationship" in asked


def test_the_two_agent_names_are_bound_to_different_graphs():
    """The mechanism, not just the outcome."""
    from app.graph.main_graph import AGENT_BUILDERS, register_all

    register_all()
    full = AGENT_BUILDERS.get("register_agent")
    step1 = AGENT_BUILDERS.get("register_agent_step1")
    assert full is not None and step1 is not None
    assert full is not step1, "both names are bound to the same builder again"
    assert getattr(step1, "keywords", {}).get("allow_sensitive") is False
    assert getattr(full, "keywords", {}).get("allow_sensitive") is True


def test_every_sensitive_slot_is_reachable_only_with_permission():
    """Nothing sensitive hides in the non-sensitive walk by another name."""
    anonymous = set(_walk(allow_sensitive=False))
    sensitive = {s.path for s in (*GUARDIAN_SLOTS, *CHILD_SLOTS) if s.sensitive}
    assert not (anonymous & sensitive), f"leaked: {sorted(anonymous & sensitive)}"
