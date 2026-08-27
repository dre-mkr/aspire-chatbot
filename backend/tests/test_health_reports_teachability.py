"""A healthy concept count is not the same as a tutor that can teach.

`concepts` counts rows the store loaded. A row loads when its status is
servable; it can be TAUGHT only when it also carries a body for the band in
front of the reader. Those two come apart precisely when the concepts table
holds metadata shells -- `seed_curriculum` writes eight columns and none of
them is a body -- and when they do, the endpoint added to catch a broken
deployment reports a healthy number for a deployment that cannot teach a
single thing.
"""

from __future__ import annotations

import pytest

from app.learning.concepts import BANDS, CheckItem, ConceptStore, TeachingConcept
from app.main import health

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _check(cid="c1", band="9-12"):
    return CheckItem(
        id=cid, band=band, type="mcq",
        question="You put EC$3 away. What is that called?", answer="Saving",
    )


def _concept(cid, *, bodies=None, checks=(), band_min="5-8", band_max="adult"):
    return TeachingConcept(
        id=cid, slug=cid, locale="en", title=cid.title(), domain="money",
        band_min=band_min, band_max=band_max,
        bodies=bodies or {}, check_bank=tuple(checks), status="approved",
    )


def _store(*concepts):
    store = ConceptStore()
    store.load(list(concepts))
    return store


async def _health_with(store, monkeypatch):
    import app.learning.concepts as concepts_module

    monkeypatch.setattr(concepts_module, "get_store", lambda: store)
    return await health()


class TestTheNumberThatWasAlreadyThere:
    async def test_rows_are_still_counted(self, monkeypatch):
        body = await _health_with(_store(_concept("save"), _concept("spend")), monkeypatch)
        assert body.concepts == 2

    async def test_an_empty_store_is_still_visible(self, monkeypatch):
        body = await _health_with(_store(), monkeypatch)
        assert body.concepts == 0
        assert body.concepts_teachable == dict.fromkeys(BANDS, 0)


class TestShellsAreCountedButNotTeachable:
    """The case this file exists for."""

    async def test_six_shells_report_six_and_teach_nobody(self, monkeypatch):
        shells = [_concept(cid) for cid in
                  ("save", "spend", "goal", "need", "budget", "habit")]
        body = await _health_with(_store(*shells), monkeypatch)

        assert body.concepts == 6, "the old number still looks healthy"
        assert body.concepts_teachable == dict.fromkeys(BANDS, 0), (
            "six rows, nothing teachable -- which is the whole point"
        )
        assert body.concepts_with_checks == 0

    async def test_a_body_makes_it_teachable(self, monkeypatch):
        real = _concept("save", bodies={"9-12": "Saving means keeping money for later."})
        body = await _health_with(_store(real), monkeypatch)
        assert body.concepts_teachable["9-12"] == 1

    async def test_a_body_serves_the_bands_above_it(self, monkeypatch):
        """`body_for` walks down the ladder, so an older reader inherits."""
        real = _concept("save", bodies={"9-12": "Saving means keeping money."})
        body = await _health_with(_store(real), monkeypatch)
        assert body.concepts_teachable["13-15"] == 1
        assert body.concepts_teachable["16-18"] == 1
        assert body.concepts_teachable["5-8"] == 0, "a younger reader inherits nothing"

    async def test_the_band_range_still_applies(self, monkeypatch):
        """A body is necessary, not sufficient: the concept must allow the band."""
        teen_only = _concept(
            "interest", bodies={"13-15": "Interest is what money earns."},
            band_min="13-15", band_max="16-18",
        )
        body = await _health_with(_store(teen_only), monkeypatch)
        assert body.concepts_teachable["13-15"] == 1
        assert body.concepts_teachable["adult"] == 0


class TestChecksAndRankingFailSeparately:
    async def test_a_concept_can_teach_without_being_able_to_ask(self, monkeypatch):
        talker = _concept("save", bodies={"9-12": "Saving means keeping money."})
        body = await _health_with(_store(talker), monkeypatch)
        assert body.concepts_teachable["9-12"] == 1
        assert body.concepts_with_checks == 0, "explains, never verifies"

    async def test_checks_are_counted_when_authored(self, monkeypatch):
        full = _concept(
            "save", bodies={"9-12": "Saving means keeping money."}, checks=[_check()]
        )
        body = await _health_with(_store(full), monkeypatch)
        assert body.concepts_with_checks == 1

    async def test_no_embeddings_means_no_ranking(self, monkeypatch):
        body = await _health_with(_store(_concept("save")), monkeypatch)
        assert body.concepts_ranked is False, (
            "without a matrix an unnamed topic can never reach the tutor"
        )


class TestItStaysCheap:
    async def test_health_asks_the_database_nothing(self, monkeypatch):
        """Liveness must not become a query, or a slow database takes it down."""
        import app.learning.concepts as concepts_module

        def explode():  # pragma: no cover - fails the test if reached
            raise AssertionError("health touched the database")

        monkeypatch.setattr(concepts_module, "_fetch_concepts", explode)
        body = await _health_with(_store(_concept("save")), monkeypatch)
        assert body.status == "ok"
