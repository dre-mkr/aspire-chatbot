"""What the watcher keeps in Neon: last-seen pages, and rows awaiting a yes.

Persistence lives here and not in the graph because the graph also has to run
in tests, where there is no database and the fakes stand in for these four
functions. Everything degrades the same way the rest of the app does: no
DATABASE_URL means every call is a quiet no-op, logged once.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.db import database_enabled, session
from app.db.models import PendingKbRow, SiteSnapshot

logger = logging.getLogger(__name__)


async def load_snapshot(url: str) -> SiteSnapshot | None:
    if not database_enabled():
        return None
    async with session() as db:
        if db is None:
            return None
        return await db.get(SiteSnapshot, url)


async def save_snapshot(url: str, content_hash: str, content: str) -> None:
    if not database_enabled():
        logger.warning("watcher: no database; snapshot for %s not kept", url)
        return
    async with session() as db:
        if db is None:
            return
        existing = await db.get(SiteSnapshot, url)
        if existing is None:
            db.add(SiteSnapshot(url=url, content_hash=content_hash, content=content))
        else:
            existing.content_hash = content_hash
            existing.content = content
        await db.commit()


async def queue_rows(drafts: list[dict[str, Any]]) -> int:
    """Insert drafted rows as pending. Returns how many were queued."""
    if not drafts or not database_enabled():
        return 0
    async with session() as db:
        if db is None:
            return 0
        for row in drafts:
            db.add(PendingKbRow(
                id=uuid.uuid4(),
                kb_id=row["kb_id"],
                category=row.get("category", ""),
                subcategory=row.get("subcategory", ""),
                question=row["question"],
                answer=row["answer"],
                keywords=row.get("keywords", ""),
                audience=row.get("audience", "general"),
                source_url=row["source_url"],
                as_of=row["as_of"],
                why=row.get("why", ""),
            ))
        await db.commit()
        return len(drafts)


async def pending_rows() -> list[PendingKbRow]:
    """Every row still waiting, oldest first, for `export` to hand a reviewer."""
    if not database_enabled():
        return []
    async with session() as db:
        if db is None:
            return []
        result = await db.execute(
            select(PendingKbRow)
            .where(PendingKbRow.status == "pending")
            .order_by(PendingKbRow.created_at)
        )
        return list(result.scalars())


async def mark_exported(kb_ids: list[str]) -> int:
    """Exported rows leave the queue; the review CSV is theirs now."""
    if not kb_ids or not database_enabled():
        return 0
    async with session() as db:
        if db is None:
            return 0
        result = await db.execute(select(PendingKbRow).where(PendingKbRow.kb_id.in_(kb_ids)))
        rows = list(result.scalars())
        for row in rows:
            row.status = "exported"
        await db.commit()
        return len(rows)
