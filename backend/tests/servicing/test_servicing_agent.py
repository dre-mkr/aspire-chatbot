"""The servicing agent answers instead of deflecting, and is reachable."""

from __future__ import annotations

import pytest

from app.agents.servicing.copy import ACCOUNT_ELSEWHERE, CHIPS
from app.agents.servicing.graph import build_servicing_graph
from app.graph.access import allowed_agents
from app.graph.nodes.classify import routable
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
