"""The Tin only ever fills, and it fills in the reader's language."""

from __future__ import annotations

from app.graph.tin import MILESTONES, tin_award


class TestTheTin:
    def test_coins_accumulate(self):
        out = tin_award({"tin": {"coins": 7}}, 2, "en")
        assert out["tin"] == {"coins": 9}
        d = out["ui_directives"][0]
        assert d.t == "tin" and d.delta == 2 and d.coins == 9

    def test_the_first_coin_starts_the_tin(self):
        assert tin_award({}, 3, "en")["tin"] == {"coins": 3}

    def test_milestones_are_crossings_not_totals(self):
        assert tin_award({"tin": {"coins": 9}}, 2, "en")["ui_directives"][0].milestone
        assert not tin_award({"tin": {"coins": 10}}, 2, "en")["ui_directives"][0].milestone

    def test_the_caption_speaks_the_language(self):
        assert "alcancía" in tin_award({}, 2, "es")["ui_directives"][0].caption
        assert "tirelire" in tin_award({}, 2, "fr")["ui_directives"][0].caption

    def test_zero_awards_nothing(self):
        assert tin_award({}, 0, "en") == {}

    def test_milestones_are_ordered(self):
        assert list(MILESTONES) == sorted(MILESTONES)


class TestLessonCoins:
    async def _teach(self, learning_over=None):
        import sys

        sys.path.insert(0, "tests")
        from learning.test_teach import run_teach

        from app.curriculum.schema import load_all

        cur = load_all(refresh=False)
        return await run_teach(
            invoke=None, curriculum=cur,
            **({"learning": learning_over} if learning_over else {}),
        )

    async def test_the_first_teach_pays_two(self, anyio_backend):
        out = await self._teach()
        tins = [d for d in out.get("ui_directives", []) if d.t == "tin"]
        assert tins and tins[0].delta == 2
        assert out["learning"]["coined_lessons"]

    async def test_the_same_lesson_never_pays_twice(self, anyio_backend):
        first = await self._teach()
        coined = first["learning"]["coined_lessons"]
        again = await self._teach({**first["learning"], "coined_lessons": coined})
        assert not [d for d in again.get("ui_directives", []) if d.t == "tin"]


import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio
