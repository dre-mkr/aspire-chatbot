"""The watcher as an arq cron entry, mirroring `retention_job`."""

from __future__ import annotations

import logging

from app.watcher.graph import build_watcher_graph

logger = logging.getLogger(__name__)


async def watcher_job(ctx: dict) -> str:
    """The nightly entry point, for arq."""
    result = await build_watcher_graph().ainvoke({})
    summary = (f"pages={len(result.get('pages', []))} "
               f"changes={len(result.get('changes', []))} queued={result.get('queued', 0)}")
    logger.info("watcher: %s", summary)
    return summary
