"""A concept row must be able to say something, or the tutor cannot teach.

Measured on production, 27 Aug: six concept rows loaded and
`concepts_teachable` was zero at every band. `seed_curriculum` wrote eight
metadata columns and no body, so `teachable_at` -- which ends on
`body_for(band) is not None` -- was False everywhere. The tutor could never
claim a turn, and every "how does saving work?" fell through to the lesson
machine and came back as a check question about something nobody asked, for
every persona and every band.

The words to fix it were already in the curriculum. These tests hold the
seeder to composing them.
"""

from __future__ import annotations

import pytest

from app.curriculum.schema import load_all
from app.curriculum.seed import _BANDS, teaching_payload
from app.learning.concepts import CheckItem, TeachingConcept


@pytest.fixture(scope="module")
def by_concept():
    book = load_all()
    index: dict[str, list] = {}
    for lesson in book.lessons.values():
        index.setdefault(lesson.concept_id, []).append(lesson)
    assert index, "the curriculum teaches no concepts at all"
    return index


def _concept(cid: str, payload: dict) -> TeachingConcept:
    """The row as the store would rebuild it."""
    return TeachingConcept.from_row(
        {
            "id": cid, "slug": cid, "locale": "en", "title": cid.title(),
            "domain": "money", "band_min": "5-8", "band_max": "adult",
            "status": "approved", **payload,
            "check_bank": payload["check_bank"],
        }
    )


class TestEveryConceptCanSpeak:
    def test_the_curriculum_covers_the_three_areas(self, by_concept):
        """Money mindset, savings and budgeting, as authored."""
        assert set(by_concept) >= {"save", "spend", "goal", "need", "budget", "habit"}

    @pytest.mark.parametrize("cid", ["save", "spend", "goal", "need", "budget", "habit"])
    def test_every_band_gets_a_body(self, by_concept, cid):
        payload = teaching_payload(by_concept[cid])
        concept = _concept(cid, payload)
        for band in _BANDS:
            body = concept.body_for(band)
            assert body and len(body) > 40, f"{cid} has nothing to say at {band}"

    @pytest.mark.parametrize("cid", ["save", "spend", "goal", "need", "budget", "habit"])
    def test_every_band_is_teachable(self, by_concept, cid):
        """The property the production failure turned on."""
        concept = _concept(cid, teaching_payload(by_concept[cid]))
        for band in _BANDS:
            assert concept.teachable_at(band) is True, f"{cid} is not teachable at {band}"

    @pytest.mark.parametrize("cid", ["save", "goal", "need", "budget", "habit"])
    def test_a_concept_that_teaches_can_also_ask(self, by_concept, cid):
        """A body with no check explains and never verifies."""
        concept = _concept(cid, teaching_payload(by_concept[cid]))
        assert concept.check_bank, f"{cid} has no checks"
        for band in ("5-8", "9-12", "13-15", "16-18"):
            assert concept.checks_for(band), f"{cid} cannot ask anything at {band}"

    def test_the_words_are_the_authors_not_ours(self, by_concept):
        """Composed from the curriculum, never invented."""
        lessons = by_concept["save"]
        payload = teaching_payload(lessons)
        authored = " ".join(
            str(p) for points in lessons[0].teach_points.values() for p in points
        )
        first = str(lessons[0].teach_points["5-8"][0])
        assert first in payload["body_5_8"], "the 5-8 body is not the authored text"
        assert authored, "no teach points to compose from"

    def test_checks_carry_their_hint_ladder(self, by_concept):
        concept = _concept("save", teaching_payload(by_concept["save"]))
        hinted = [c for c in concept.check_bank if c.hints]
        assert hinted, "no check kept its hints, so scaffolding is gone"
        assert all(isinstance(c, CheckItem) for c in concept.check_bank)
