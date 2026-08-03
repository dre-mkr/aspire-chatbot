"""The one thing this feature writes to Postgres.

Four columns: which of the three verdicts, which criterion it turned on, which
language, and when. That is the whole row.

What is deliberately **not** here, and must not be added without a decision from
whoever owns the privacy position:

* **No thread id, and no foreign key to `conversations`.** A join key would tie
  this row to a transcript, and a transcript identifies a person far better than
  an age band does. Without one, these rows are a histogram and nothing else.
* **No answers.** Not the age band, not the island, not the school status. The
  function signature cannot carry them: it takes an `Outcome`, which has no
  field they could occupy.
* **No island, ever, alongside anything else.** Saint Kitts and Nevis is a
  federation of about fifty thousand people. "Nevis, under 5, not in school" is
  not anonymous there, however it is stored.

The write is fire-and-forget. An insight row is worth less than the answer the
person is reading, so a database failure here is logged and swallowed. That is
also why `eligibility_outcomes` is not in `db.engine.REQUIRED_TABLES`: an
unmigrated analytics table must not switch off conversation persistence.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import database_enabled, session
from app.db.models import EligibilityOutcome
from app.eligibility.config import get_eligibility_settings
from app.eligibility.models import Outcome

logger = logging.getLogger(__name__)


async def record(outcome: Outcome) -> None:
    """Append one anonymised outcome, or do nothing at all.

    Silent no-op when the database is off or `ELIGIBILITY_RECORD_OUTCOMES` is
    false, so the flow works identically with no analytics whatsoever.
    """
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
