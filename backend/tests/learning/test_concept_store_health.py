"""An empty concept store is a P1, and nothing said so.

Found by asking production a question. Kaleb, band 9-12:

    "how does the interest on my 500 dollars actually work? show me the maths"
    -> "Sure! What do we call money that you keep to use later instead of
        spending now?"

The routing was right -- "how does X work" is a mechanism question and
`learn_agent` owns those. What failed sits under it: `learn/graph._entry` gates
the tutor's ENTIRE claim on `len(get_store())`. An empty store skips every
claim, the turn drops to `phase = "placing"`, and mastery placement answers with
a check question. The reader's question was not answered, deferred or declined.
It was discarded, and the reply read as a deliberate teaching choice.

`learn/graph` has warned about this in the log since before the incident, and
that is how it was diagnosed -- but a log line is for whoever is already looking.
The health surface, which is where somebody looks when the tutor is behaving
oddly, reported six rates and none of them was this. `resolution_none_rate`
would have climbed, and it reads as the tutor choosing badly rather than as the
tutor having nothing to choose from.
"""

from __future__ import annotations

import pytest

from app.learning import health as learning


class _Store:
    def __init__(self, n: int):
        self._n = n

    def __len__(self) -> int:
        return self._n


@pytest.fixture(autouse=True)
def _no_counters(monkeypatch):
    """Isolate the store check from the windowed counters."""
    async def empty(_hours):
        return {}

    monkeypatch.setattr(learning, "_read_window", empty)


async def _snapshot(monkeypatch, count):
    monkeypatch.setattr("app.learning.concepts.get_store", lambda: _Store(count))
    return await learning.snapshot(24)


class TestAnEmptyStoreIsVisible:
    @pytest.mark.asyncio
    async def test_the_count_is_on_the_surface(self, monkeypatch):
        assert (await _snapshot(monkeypatch, 0)).concepts_loaded == 0

    @pytest.mark.asyncio
    async def test_it_is_a_breach(self, monkeypatch):
        health = await _snapshot(monkeypatch, 0)
        assert not health.healthy

    @pytest.mark.asyncio
    async def test_the_breach_says_what_the_reader_experiences(self, monkeypatch):
        """An operator reading this should not have to infer the symptom."""
        health = await _snapshot(monkeypatch, 0)
        breach = next(b for b in health.breaches if "concept store" in b)
        assert "check question the reader did not ask for" in breach
        assert "Seed the concepts" in breach


class TestASeededStoreIsQuiet:
    @pytest.mark.asyncio
    async def test_the_count_is_reported(self, monkeypatch):
        assert (await _snapshot(monkeypatch, 42)).concepts_loaded == 42

    @pytest.mark.asyncio
    async def test_no_breach_is_raised(self, monkeypatch):
        health = await _snapshot(monkeypatch, 42)
        assert not [b for b in health.breaches if "concept store" in b]

    @pytest.mark.asyncio
    async def test_one_concept_is_enough_to_be_servable(self, monkeypatch):
        health = await _snapshot(monkeypatch, 1)
        assert not [b for b in health.breaches if "concept store" in b]


class TestTheCheckCannotTakeTheSurfaceDown:
    @pytest.mark.asyncio
    async def test_an_unreadable_store_reports_zero_rather_than_raising(
        self, monkeypatch
    ):
        """This endpoint is opened BECAUSE something is wrong. It must survive
        the thing that is wrong."""

        def boom():
            raise RuntimeError("no database")

        monkeypatch.setattr("app.learning.concepts.get_store", boom)
        health = await learning.snapshot(24)
        assert health.concepts_loaded == 0
        assert not health.healthy
