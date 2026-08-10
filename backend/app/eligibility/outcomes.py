"""The one thing this feature writes to Postgres."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import database_enabled, session
from app.db.models import EligibilityOutcome
from app.eligibility.config import get_eligibility_settings
from app.eligibility.models import Outcome

logger = logging.getLogger(__name__)


async def record(outcome: Outcome) -> None:
    """Append one anonymised outcome, or do nothing at all."""
    if not get_eligibility_settings().record_outcomes or not database_enabled():
        return

    try:
        async with session() as db:
            if db is None:
                return
            await _insert(db, outcome)
    except Exception:
        # Never the reason someone does not get their result.
        logger.warning("Could not record an eligibility outcome.", exc_info=True)


async def _insert(db: AsyncSession, outcome: Outcome) -> None:
    db.add(
        EligibilityOutcome(
            verdict=outcome.verdict.value,
            criterion=outcome.criterion.value,
            language=outcome.language.value,
        )
    )
