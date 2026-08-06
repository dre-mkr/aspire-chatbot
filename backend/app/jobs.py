"""Background work, on arq.

One nightly cron job: the retention sweep. Run the worker alongside the API:

    arq app.jobs.WorkerSettings

## The summary job was removed here, and why (P15)

This module used to carry `summarise_conversation_job` and `enqueue_summary`,
which folded a conversation's older turns into `conversations.summary`. Both are
gone, along with the `save_summary` / `turns_awaiting_summary` repository
helpers that only they used.

The rolling summary moved into the CHECKPOINT when the graph became the only
chat path. `conversations.summary` was read by `load_context`, which fed
`build_prompt`, which fed the v1 agent; the graph reads `state["summary"]`
instead, and `turn.summarise_thread` writes it there with `aupdate_state` after
the stream has closed. There is no longer anything on either end of the Postgres
column.

It was not merely unread -- it was unwritten. Measured on the dev database
before removing it: 2,774 conversations, 0 with a summary and 0 with
`summarized_through_seq > 0`, for two reasons stacked:

  * `enqueue_summary` lost its last caller with `POST /chat`, so nothing has
    queued the job since;
  * before that, a backlog of 1,555 `summary:*` jobs sat in Valkey and was never
    consumed. Starting a worker during verification drained all of them as
    `expired` -- queued while `/chat` existed, never claimed, aged out in place.

The column was empty for the whole life of the feature: first because nothing
ran the queue, then because nothing filled it.

Deleting it rather than leaving it wired to nothing, because a registered job
that is never enqueued is indistinguishable from a broken one: the worker starts
clean, reports itself healthy, and processes nothing forever. The column itself
is left in place -- it holds no data, and this branch's migrations are additive
only.
"""

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

    # Empty, and correctly so: this worker is cron-only now. Nothing in the
    # product enqueues an on-demand job -- see the module docstring for what
    # used to be here. arq requires the attribute to exist.
    functions = []
    # Nightly, at 03:15, off the request path. A read-time sweep would put a
    # delete in front of somebody waiting for an answer, and would only ever
    # tidy up the identities that came back — which is the set that does not
    # need tidying.
    cron_jobs = [
        cron(retention_job, hour=3, minute=15, run_at_startup=False),
    ]
    max_tries = 2
    job_timeout = 120


# arq reads `redis_settings` as an ATTRIBUTE, not as a callable. A
# `@staticmethod` here type-checks, imports cleanly, and then hands arq the
# descriptor object itself -- the worker dies on startup with
# "'staticmethod' object has no attribute 'host'", which names neither Valkey
# nor this class.
#
# Assigned after the class body rather than inside it so that importing this
# module without VALKEY_URL set cannot raise. Without Valkey there is no worker
# to configure anyway.
if get_settings().valkey_url:
    WorkerSettings.redis_settings = _redis_settings()
