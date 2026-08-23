"""The servicing agent.

One node, no retrieval, no model call. That is not a placeholder -- it is the
whole honest answer. This assistant cannot see an account, so the question
"what is my balance" has exactly one true response: here is where your balance
actually lives. Reaching for the corpus instead produces general facts about
how ASPIRE accounts work, addressed to someone asking about their own.

Why this exists as a registered agent rather than a stub: `classify.routable`
refuses to send anyone to an agent with no builder, on the sound principle that
a placeholder must never be a destination. While this answer sat behind a stub
it was unreachable, and every account question fell through to `qa_agent`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.agents.servicing.copy import (
    ACCOUNT_ELSEWHERE,
    ACCOUNT_ELSEWHERE_BRIEF,
    CHIPS,
)
from app.graph.state import AspireState


def answer_for(locale: str, band: str) -> str:
    """The longest form of the answer this reader's cap can actually hold.

    Choosing here rather than letting `safety_out` truncate is the whole point.
    The full answer opens by saying what cannot be done and closes with where
    to go instead, so a truncator working front-to-back keeps the apology and
    discards the bank, the portal, the email and both phone numbers.
    """
    from app.graph.nodes.safety_out import over_cap

    full = ACCOUNT_ELSEWHERE.get(locale, ACCOUNT_ELSEWHERE["en"])
    if not over_cap(full, band, "servicing_agent"):
        return full
    return ACCOUNT_ELSEWHERE_BRIEF.get(locale, ACCOUNT_ELSEWHERE_BRIEF["en"])


def point_at_the_account(state: AspireState) -> dict[str, Any]:
    """Name the places that hold what was asked for."""
    locale = str(state.get("locale") or "en")
    band = str(state.get("age_band") or "adult")
    return {
        "messages": [AIMessage(content=answer_for(locale, band))],
        "quick_replies": CHIPS.get(locale, CHIPS["en"]),
        "active_agent": "servicing_agent",
    }


def build_servicing_graph():
    graph = StateGraph(AspireState)
    graph.add_node("point_at_the_account", point_at_the_account)
    graph.add_edge(START, "point_at_the_account")
    graph.add_edge("point_at_the_account", END)
    return graph.compile()


def register() -> None:
    from app.graph.main_graph import register_agent

    register_agent("servicing_agent", build_servicing_graph)
