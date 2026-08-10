"""The guided ASPIRE eligibility pre-check."""

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
