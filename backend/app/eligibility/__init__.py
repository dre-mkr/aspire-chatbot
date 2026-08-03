"""The guided ASPIRE eligibility pre-check.

Two questions people arrive with — "can I join?" and "how do I apply?" — turned
from prose into a short tapped flow that ends in one of three outcomes and a
document list personalised to the answers.

The whole feature sits behind `eligibility_enabled()`. Nothing outside this
package reaches past `ELIGIBILITY_TOOLS` and the router: the agent gets one tool
that opens the card, and the engine keeps the flow, the rules and the verdict.

Every rule in `rules.py` cites the knowledge-base row it came from. That is not
a documentation habit, it is the constraint the feature was built under — see
the module docstring there.
"""

from app.eligibility.config import EligibilitySettings, get_eligibility_settings
from app.eligibility.models import Criterion, Language, Verdict
from app.eligibility.router import router as eligibility_router
from app.eligibility.tools import ELIGIBILITY_TOOLS

__all__ = [
    "ELIGIBILITY_TOOLS",
    "Criterion",
    "EligibilitySettings",
    "Language",
    "Verdict",
    "eligibility_enabled",
    "eligibility_router",
    "get_eligibility_settings",
]


def eligibility_enabled() -> bool:
    return get_eligibility_settings().eligibility_enabled
