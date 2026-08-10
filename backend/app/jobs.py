"""Background work, on arq."""

from __future__ import annotations

import logging

from arq import cron
from arq.connections import RedisSettings

from app.cache import valkey_url
from app.config import get_settings

from app.retention import retention_job

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    if not settings.valkey_url:
        raise RuntimeError(
            "VALKEY_URL is not set. The arq worker needs Valkey; set it in "
            "backend/.env."
        )
    return RedisSettings.from_dsn(valkey_url())


class WorkerSettings:
    """Entry point for `arq app.jobs.WorkerSettings`."""

    # Empty, and correctly so: this worker is cron-only now.
    functions = []
    # Nightly, at 03:15, off the request path.
    cron_jobs = [
        cron(retention_job, hour=3, minute=15, run_at_startup=False),
    ]
    max_tries = 2
    job_timeout = 120


# arq reads `redis_settings` as an ATTRIBUTE, not as a callable.
if get_settings().valkey_url:
    WorkerSettings.redis_settings = _redis_settings()
