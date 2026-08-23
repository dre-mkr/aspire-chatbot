"""The servicing agent answers instead of deflecting, and is reachable."""

from __future__ import annotations

import pytest

from app.agents.servicing.copy import (
    ACCOUNT_ELSEWHERE,
    ACCOUNT_ELSEWHERE_BRIEF,
    CHIPS,
)
from app.agents.servicing.graph import build_servicing_graph
from app.graph.access import allowed_agents
from app.graph.nodes.classify import routable
from app.graph.nodes.safety_out import over_cap
from app.messages import text_of

pytestmark = pytest.mark.asyncio

LOCALES = ("en", "es", "fr")


class TestItAnswers:
    @pytest.mark.parametrize("locale", LOCALES)
    async def test_it_names_where_the_account_actually_is(self, locale):
        """Bank, statements, portal, team -- the four real places, every language."""
        graph = build_servicing_graph()
        out = await graph.ainvoke(
            {"messages": [], "locale": locale, "age_band": "adult"}
        )
        said = text_of(out["messages"][-1])

        assert "National Bank" in said
        assert "aspire.gov.kn" in said
        assert "aspire@gov.kn" in said
        assert "667-5566" in said
        assert out["active_agent"] == "servicing_agent"

    async def test_an_unknown_locale_still_gets_an_answer(self):
        graph = build_servicing_graph()
        out = await graph.ainvoke(
            {"messages": [], "locale": "pt", "age_band": "adult"}
        )
        assert text_of(out["messages"][-1]) == ACCOUNT_ELSEWHERE["en"]

    @pytest.mark.parametrize("locale", LOCALES)
    async def test_it_is_not_a_dead_end(self, locale):
        graph = build_servicing_graph()
        out = await graph.ainvoke(
            {"messages": [], "locale": locale, "age_band": "adult"}
        )
        assert out["quick_replies"] == CHIPS[locale]

    async def test_every_locale_is_translated_not_copied(self):
        """A missing translation shows up as English sitting in the es/fr slot."""
        assert len({ACCOUNT_ELSEWHERE[locale] for locale in LOCALES}) == 3
        assert len({tuple(CHIPS[locale]) for locale in LOCALES}) == 3


class TestItIsReachable:
    """The regression that made the answer above unreachable for months."""

    async def test_the_router_may_choose_it(self):
        granted = allowed_agents("aurora", "adult", "beneficiary", user_id="u")
        assert "servicing_agent" in granted, "the matrix must still grant it"
        assert "servicing_agent" in routable(granted), (
            "servicing_agent has a builder, so `routable` must offer it. While it "
            "was excluded, 'what is my balance' went to qa_agent and was answered "
            "from the corpus -- general facts about ASPIRE accounts, to someone "
            "asking about their own."
        )

    async def test_it_has_a_builder_so_it_is_never_the_placeholder(self):
        import app.graph.main_graph as main_graph

        main_graph.register_all()
        assert "servicing_agent" in main_graph.AGENT_BUILDERS


class TestItFitsTheReadersCap:
    """A guardian's cap follows their child's band, and the answer must survive it."""

    BANDS = ("5-8", "9-12", "13-15", "16-18", "adult")

    @pytest.mark.parametrize("band", BANDS)
    @pytest.mark.parametrize("locale", LOCALES)
    async def test_the_answer_is_never_truncated(self, band, locale):
        graph = build_servicing_graph()
        out = await graph.ainvoke(
            {"messages": [], "locale": locale, "age_band": band}
        )
        said = text_of(out["messages"][-1])
        assert not over_cap(said, band, "servicing_agent"), (
            f"{band}/{locale} exceeds its cap, so safety_out will truncate it -- "
            "and this answer front-loads what it cannot do and back-loads where "
            "to go, so truncation keeps the apology and cuts the answer."
        )

    @pytest.mark.parametrize("band", BANDS)
    @pytest.mark.parametrize("locale", LOCALES)
    async def test_a_way_to_reach_a_person_always_survives(self, band, locale):
        """The one thing a parent chasing a missing payment came for."""
        graph = build_servicing_graph()
        out = await graph.ainvoke(
            {"messages": [], "locale": locale, "age_band": band}
        )
        said = text_of(out["messages"][-1])
        assert "aspire@gov.kn" in said
        assert "667-5566" in said

    @pytest.mark.parametrize("locale", LOCALES)
    async def test_the_tight_bands_get_the_short_form_not_a_cut_one(self, locale):
        graph = build_servicing_graph()
        out = await graph.ainvoke(
            {"messages": [], "locale": locale, "age_band": "5-8"}
        )
        assert text_of(out["messages"][-1]) == ACCOUNT_ELSEWHERE_BRIEF[locale]

    @pytest.mark.parametrize("locale", LOCALES)
    async def test_an_adult_still_gets_the_full_answer(self, locale):
        graph = build_servicing_graph()
        out = await graph.ainvoke(
            {"messages": [], "locale": locale, "age_band": "adult"}
        )
        assert text_of(out["messages"][-1]) == ACCOUNT_ELSEWHERE[locale]

    async def test_the_short_form_is_translated_not_copied(self):
        assert len({ACCOUNT_ELSEWHERE_BRIEF[locale] for locale in LOCALES}) == 3
