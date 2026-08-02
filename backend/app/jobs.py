"""Background work, on arq.

One job so far: regenerating a conversation's running summary. It lives here
rather than in the request because compressing older turns costs a model call,
and paying for it while the user waits would move the latency rather than
remove it.

Run the worker alongside the API:

    arq app.jobs.WorkerSettings
"""

from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.agent import summarise_conversation
from app.cache import valkey_url
from app.config import get_settings
from app.db import Conversation, database_enabled, session
from app.db.repository import save_summary, turns_awaiting_summary

logger = logging.getLogger(__name__)

SUMMARISE_TASK = "summarise_conversation_job"


async def summarise_conversation_job(ctx: dict, conversation_id: str) -> str | None:
    """Fold everything that has fallen out of the window into the summary.

    Idempotent on purpose. The trigger fires on a message count, retries happen,
    and two workers can pick up the same conversation; `save_summary` refuses to
    move `summarized_through_seq` backwards, so the worst case is wasted work
    rather than lost context.
    """
    settings = get_settings()
    if not database_enabled():
        return None

    async with session() as db:
        if db is None:
            return None

        pending = await turns_awaiting_summary(
            db, conversation_id, window_turns=settings.memory_window_turns
        )
        if len(pending) < settings.memory_summary_after_turns:
            return None

        conversation = await db.get(Conversation, conversation_id)
        previous = conversation.summary if conversation else None
        through = pending[-1].seq
        turns = [(message.role, message.content) for message in pending]

    # The model call happens outside the session: a summary can take seconds,
    # and holding a pooled Neon connection open across it would waste the pool.
    summary = await summarise_conversation(turns, previous)
    if not summary:
        return None

    async with session() as db:
        if db is None:
            return None
        await save_summary(db, conversation_id, summary=summary, through_seq=through)

    logger.info(
        "summarised conversation=%s through_seq=%d turns=%d chars=%d",
        conversation_id,
        through,
        len(turns),
        len(summary),
    )
    return summary


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

    functions = [summarise_conversation_job]
    # Summarisation is best effort and the next turn triggers it again, so a
    # long retry chain would only pile up duplicate model calls for a
    # conversation nobody is waiting on.
    max_tries = 2
    job_timeout = 120


# arq reads `redis_settings` as an ATTRIBUTE, not as a callable. A
# `@staticmethod` here type-checks, imports cleanly, and then hands arq the
# descriptor object itself -- the worker dies on startup with
# "'staticmethod' object has no attribute 'host'", which names neither Valkey
# nor this class.
#
# Assigned after the class body rather than inside it so that importing this
# module without VALKEY_URL set -- which `app.main` does, for `enqueue_summary`
# -- cannot raise. Without Valkey there is no worker to configure anyway.
if get_settings().valkey_url:
    WorkerSettings.redis_settings = _redis_settings()


async def enqueue_summary(conversation_id: str) -> bool:
    """Ask for a summary refresh. Never blocks and never raises.

    A queue that is unreachable must not fail the answer the user is reading:
    the conversation keeps its previous summary and the next turn tries again.
    """
    if not get_settings().valkey_url:
        return False

    try:
        from arq import create_pool

        pool = await create_pool(_redis_settings())
        try:
            # Keyed by conversation, so a burst of turns coalesces into one job
            # rather than queueing a model call per message.
            await pool.enqueue_job(
                SUMMARISE_TASK,
                conversation_id,
                _job_id=f"summary:{conversation_id}",
            )
        finally:
            await pool.aclose()
        return True
    except Exception:
        logger.warning("Could not enqueue the summary job.", exc_info=True)
        return False
