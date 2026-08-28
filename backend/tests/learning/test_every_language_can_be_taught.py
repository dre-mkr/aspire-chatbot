"""A Spanish or French reader must be able to be taught something.

The corpus is English and always has been: `ground_check` localises what a
citation SAYS and leaves what it POINTS AT alone, and an answer is written in
the reader's language from English source. The concept store was the one place
that did not follow that rule. It filtered strictly on locale, and every
authored concept row is English, so `teachable` returned an empty list for
`es` and `fr`. Those readers could not be taught a single concept in either
language -- the tutor could never resolve one, so every lesson request fell
through exactly as it did when the rows had no bodies at all.
"""

from __future__ import annotations

import pytest

from app.learning.concepts import ConceptStore, TeachingConcept

BANDS = ("5-8", "9-12", "13-15", "16-18", "adult")


def _concept(cid: str, locale: str = "en", band: str = "9-12") -> TeachingConcept:
    return TeachingConcept(
        id=cid, slug=cid, locale=locale, title=cid.title(), domain="money",
        band_min="5-8", band_max="adult",
        bodies={band: f"{cid} explained for {band}."}, status="approved",
    )


@pytest.fixture
def english_only():
    store = ConceptStore()
    store.load([_concept("save"), _concept("interest"), _concept("scams")])
    return store


class TestAnEnglishCorpusStillTeaches:
    @pytest.mark.parametrize("locale", ["es", "fr"])
    def test_a_reader_in_another_language_is_not_taught_nothing(self, english_only, locale):
        assert english_only.teachable("9-12", locale), (
            f"a {locale} reader can be taught no concept at all"
        )

    @pytest.mark.parametrize("locale", ["es", "fr"])
    def test_they_get_the_same_concepts_english_readers_get(self, english_only, locale):
        theirs = {c.id for c in english_only.teachable("9-12", locale)}
        ours = {c.id for c in english_only.teachable("9-12", "en")}
        assert theirs == ours

    @pytest.mark.parametrize("locale", ["es", "fr"])
    def test_a_concept_can_be_found_by_slug(self, english_only, locale):
        assert english_only.by_slug("interest", locale) is not None

    def test_english_is_unchanged(self, english_only):
        assert len(english_only.teachable("9-12", "en")) == 3


class TestATranslationWinsWhenThereIsOne:
    """The fallback is a floor, not a ceiling: authored Spanish still wins."""

    def test_a_spanish_concept_is_preferred_over_english(self):
        store = ConceptStore()
        store.load([_concept("save"), _concept("ahorrar", locale="es")])
        found = {c.id for c in store.teachable("9-12", "es")}
        assert found == {"ahorrar"}, "an authored Spanish concept must win"

    def test_english_readers_do_not_see_the_spanish_row(self):
        store = ConceptStore()
        store.load([_concept("save"), _concept("ahorrar", locale="es")])
        assert {c.id for c in store.teachable("9-12", "en")} == {"save"}

    def test_an_empty_store_stays_empty(self):
        """The fallback must not invent a concept where there is none."""
        assert ConceptStore().teachable("9-12", "es") == []
