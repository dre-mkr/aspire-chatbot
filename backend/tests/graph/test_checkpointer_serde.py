"""What may be reconstructed out of a checkpoint row.

langgraph rebuilds a checkpointed object by importing a module and calling a
name out of it, driven by what is stored in the row. Its default is to do that
for any type at all and log

    Deserializing unregistered type app.graph.state.KBChunk from checkpoint.
    This will be blocked in a future version.

`allowed_checkpoint_types` replaces that with an allowlist. These tests exist
because of how the blocked case FAILS: not with an exception, but by returning
the raw payload. A `KBChunk` that is not on the list comes back as a plain dict,
every attribute access one layer downstream starts raising, and nothing names
the checkpoint. `test_an_unlisted_type_degrades_to_a_dict` pins that mechanism
so the rest of the file is testing something real rather than a tautology.

Measured against the live checkpoint tables when the allowlist was written:
2,568 blobs and 3,152 writes decoded with zero blocked types, reconstructing
560 `KBChunk`, 24 `Citation` and 108 `EscalatedDirective`.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.graph.checkpointer import allowed_checkpoint_types  # noqa: E402
from app.graph.state import Citation, KBChunk  # noqa: E402

jsonplus = pytest.importorskip(
    "langgraph.checkpoint.serde.jsonplus",
    reason="the serde lives in the checkpoint library",
)


def _serde(allow=None):
    return jsonplus.JsonPlusSerializer(
        allowed_msgpack_modules=allowed_checkpoint_types() if allow is None else allow
    )


def _roundtrip(value, serde):
    return serde.loads_typed(serde.dumps_typed(value))


# ── the allowlist is enforcing, not decorative ───────────────────────────────


def test_an_unlisted_type_degrades_to_a_dict():
    """The negative control, and the reason the rest of this file matters.

    A blocked type does not raise. It comes back as its payload, so the damage
    surfaces as an AttributeError somewhere else entirely -- `merge_citations`
    doing `citation.kb_id` against a dict, for instance.
    """
    restored = _roundtrip(
        KBChunk(kb_id="ASP-001", content="x"),
        _serde(allow=[("app.graph.state", "Citation")]),
    )

    assert not isinstance(restored, KBChunk)
    assert isinstance(restored, dict), (
        "a blocked type is expected to come back as its raw payload; if this "
        "now raises instead, the silent-failure premise above has changed"
    )


# ── the types that are actually checkpointed ─────────────────────────────────


def test_a_chunk_survives_the_round_trip_as_a_chunk():
    chunk = KBChunk(
        kb_id="ASP-042", title="Eligibility", content="Ages 5 to 18.", relevance=0.87
    )
    restored = _roundtrip(chunk, _serde())

    assert isinstance(restored, KBChunk)
    assert restored.kb_id == "ASP-042"
    assert restored.relevance == pytest.approx(0.87)


def test_a_citation_survives_the_round_trip_as_a_citation():
    restored = _roundtrip(Citation(kb_id="ASP-029", supports="minimum age"), _serde())

    assert isinstance(restored, Citation)
    # `merge_citations` reads this attribute on every turn.
    assert restored.kb_id == "ASP-029"


def test_a_directive_survives_the_round_trip():
    """`EscalatedDirective` was in 108 live checkpoint rows and was not in the
    report's list of two. It was found by counting the database, which is why
    the allowlist is derived rather than transcribed."""
    from app.schemas.directives import EscalatedDirective

    restored = _roundtrip(
        EscalatedDirective(ticket_id="ASP-1234", eta="one working day"), _serde()
    )

    assert isinstance(restored, EscalatedDirective)
    assert restored.ticket_id == "ASP-1234"
    assert restored.eta == "one working day"


def test_the_whole_retrieved_list_round_trips():
    """The shape a real checkpoint holds: a list of chunks under one key."""
    chunks = [KBChunk(kb_id=f"ASP-{n:03d}", content=str(n)) for n in range(5)]
    restored = _roundtrip(chunks, _serde())

    assert [type(c) for c in restored] == [KBChunk] * 5
    assert [c.kb_id for c in restored] == [f"ASP-{n:03d}" for n in range(5)]


# ── drift ────────────────────────────────────────────────────────────────────


def test_every_directive_in_the_union_is_allowlisted():
    """A new directive type must not need anyone to remember this file.

    Derived from the same `UIDirective` union the emitters are typed against, so
    the assertion is that the derivation covers the union rather than that a
    literal was kept up to date.
    """
    from typing import get_args

    from app.schemas.directives import UIDirective

    allowed = set(allowed_checkpoint_types())
    # Annotated[Union[...], Field(discriminator=...)] -- the union is arg 0.
    members = get_args(get_args(UIDirective)[0])
    assert members, "parsed no members out of the UIDirective union"

    missing = [
        m.__name__ for m in members if (m.__module__, m.__name__) not in allowed
    ]
    assert not missing, f"directives missing from the checkpoint allowlist: {missing}"


def test_nested_models_are_reached_too():
    """A widget lives inside `WidgetDirective`, and its panels inside it.

    Nesting is where a hand-written list goes wrong: the outer type is obvious
    and the third level down is not.
    """
    allowed = set(allowed_checkpoint_types())

    for module, name in (
        ("app.schemas.directives", "CitationRef"),  # inside CitationsDirective
        ("app.schemas.directives", "QuickReplyOption"),  # inside QuickRepliesDirective
        ("app.widgets.schemas", "SimulatorWidget"),  # inside WidgetDirective
        ("app.widgets.schemas", "Control"),  # inside a widget
    ):
        assert (module, name) in allowed, f"{module}.{name} is not allowlisted"


def test_the_allowlist_stays_an_allowlist():
    """Not `app.*`, and not everything importable.

    The control only means something if things are left off it. `Settings` is a
    real pydantic model in this codebase that never goes near a checkpoint.
    """
    allowed = set(allowed_checkpoint_types())

    assert ("app.config", "Settings") not in allowed
    assert all(module.startswith("app.") for module, _ in allowed)
