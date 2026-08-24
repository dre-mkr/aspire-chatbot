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
