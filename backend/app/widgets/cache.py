"""The sustainability layer: generate a widget once, serve it forever."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

APPROVED = "approved"
REJECTED = "rejected"
CANDIDATE = "candidate"


@dataclass(frozen=True, slots=True)
class CacheKey:
    """All three axes, always. There is no two-axis constructor on purpose."""

    concept_id: str
    age_band: str
    locale: str

    def valkey(self) -> str:
        return f"widget:{self.concept_id}:{self.age_band}:{self.locale}"


@dataclass(frozen=True, slots=True)
class Entry:
    status: str
    payload: dict[str, Any] | None
    generated_at: datetime | None = None
    version: int = 1

    @property
    def servable(self) -> bool:
        return self.status in (APPROVED, CANDIDATE) and self.payload is not None

    def stale(self, *, now: datetime | None = None) -> bool:
        """Whether a CANDIDATE is old enough to regenerate."""
        if self.status != CANDIDATE:
            return False
        if self.generated_at is None:
            return True
        age = (now or datetime.now(timezone.utc)) - self.generated_at
        return age > timedelta(days=get_settings().widget_candidate_ttl_days)


@dataclass
class Stats:
    """What the instrumentation reports. Counted per process, reported on demand."""

    hits: int = 0
    misses: int = 0
    rejected_served: int = 0
    generated: int = 0
    #: Per-gate validation failures, so a rising count says which gate to fix.
    gate_failures: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.gate_failures is None:
            self.gate_failures = {}

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def payload(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 3),
            "rejected_served": self.rejected_served,
            "generated": self.generated,
            # Two model calls per generation, so this is the sustainability number.
            "generations_avoided": self.hits,
            "gate_failures": dict(self.gate_failures),
        }


STATS = Stats()


class WidgetCache:
    """Postgres for the record, Valkey in front of it for approved payloads."""

    async def get(self, key: CacheKey) -> Entry | None:
        cached = await self._from_valkey(key)
        if cached is not None:
            STATS.hits += 1
            return cached

        entry = await self._from_postgres(key)
        if entry is None:
            STATS.misses += 1
            return None

        if entry.status == APPROVED:
            STATS.hits += 1
            await self._to_valkey(key, entry)
        elif entry.status == REJECTED:
            STATS.rejected_served += 1
        else:
            STATS.hits += 1
        return entry

    async def put_candidate(
        self, key: CacheKey, payload: dict[str, Any], *, source_question: str
    ) -> None:
        """Record a freshly generated widget for review."""
        STATS.generated += 1
        from sqlalchemy import text as sql

        from app.db import session

        async with session() as db:
            if db is None:
                return
            await db.execute(
                sql(
                    """
                    INSERT INTO concept_widgets (
                        concept_id, age_band, locale, kind, payload, status,
                        source_question
                    ) VALUES (
                        :concept, :band, :locale, :kind, CAST(:payload AS jsonb),
                        'candidate', :question
                    )
                    ON CONFLICT (concept_id, age_band, locale)
                        WHERE status = 'candidate'
                    DO UPDATE SET
                        payload = EXCLUDED.payload,
                        kind = EXCLUDED.kind,
                        source_question = EXCLUDED.source_question,
                        generated_at = now()
                    """
                ),
                {
                    "concept": key.concept_id,
                    "band": key.age_band,
                    "locale": key.locale,
                    "kind": str(payload.get("kind", "")),
                    "payload": json.dumps(payload),
                    "question": source_question[:500],
                },
            )
            await db.commit()

    async def review(
        self,
        key: CacheKey,
        *,
        status: str,
        reviewed_by: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Approve, reject, or approve-with-an-edit."""
        if status not in (APPROVED, REJECTED):
            raise ValueError(f"{status!r} is not a review outcome")

        from sqlalchemy import text as sql

        from app.db import session

        async with session() as db:
            if db is None:
                return
            await db.execute(
                sql(
                    """
                    UPDATE concept_widgets
                       SET status = :status,
                           reviewed_by = :who,
                           reviewed_at = now(),
                           version = version + 1,
                           payload = COALESCE(CAST(:payload AS jsonb), payload)
                     WHERE concept_id = :concept
                       AND age_band = :band
                       AND locale = :locale
                       AND status = 'candidate'
                    """
                ),
                {
                    "status": status,
                    "who": reviewed_by,
                    "payload": json.dumps(payload) if payload else None,
                    "concept": key.concept_id,
                    "band": key.age_band,
                    "locale": key.locale,
                },
            )
            await db.commit()

        # Dropped rather than updated.
        await self._drop_valkey(key)
        logger.info(
            "widget %s/%s/%s -> %s by %s",
            key.concept_id,
            key.age_band,
            key.locale,
            status,
            reviewed_by,
        )

    # ── the two stores ──────────────────────────────────────────────────────

    async def _from_postgres(self, key: CacheKey) -> Entry | None:
        from sqlalchemy import text as sql

        from app.db import session

        async with session() as db:
            if db is None:
                return None
            row = (
                await db.execute(
                    sql(
                        """
                        SELECT status, payload, generated_at, version
                          FROM concept_widgets
                         WHERE concept_id = :concept
                           AND age_band = :band
                           AND locale = :locale
                         -- approved beats candidate beats rejected, so a
                         -- reviewed row always wins over the candidate it was
                         -- reviewed from.
                         ORDER BY CASE status
                                    WHEN 'approved' THEN 0
                                    WHEN 'rejected' THEN 1
                                    ELSE 2
                                  END
                         LIMIT 1
                        """
                    ),
                    {
                        "concept": key.concept_id,
                        "band": key.age_band,
                        "locale": key.locale,
                    },
                )
            ).first()

        if row is None:
            return None
        return Entry(
            status=row[0], payload=row[1], generated_at=row[2], version=row[3]
        )

    async def _from_valkey(self, key: CacheKey) -> Entry | None:
        try:
            from app import cache as response_cache

            client = response_cache.get_client()
            if client is None:
                return None
            raw = await client.get(response_cache.namespace() + key.valkey())
        except Exception:
            # Never raises.
            return None
        if not raw:
            return None
        try:
            return Entry(status=APPROVED, payload=json.loads(raw))
        except json.JSONDecodeError:
            return None

    async def _to_valkey(self, key: CacheKey, entry: Entry) -> None:
        if entry.payload is None:
            return
        try:
            from app import cache as response_cache

            client = response_cache.get_client()
            if client is None:
                return
            await client.set(
                response_cache.namespace() + key.valkey(),
                json.dumps(entry.payload),
                # A long TTL is safe here BECAUSE a review drops the key explicitly.
                ex=7 * 86_400,
            )
        except Exception:
            return

    async def _drop_valkey(self, key: CacheKey) -> None:
        try:
            from app import cache as response_cache

            client = response_cache.get_client()
            if client is None:
                return
            await client.delete(response_cache.namespace() + key.valkey())
        except Exception:
            return


CACHE = WidgetCache()


async def lookup(
    concept_id: str, age_band: str, locale: str
) -> tuple[str, dict[str, Any] | None]:
    """The lookup order, as one call."""
    key = CacheKey(concept_id, age_band, locale)
    entry = await CACHE.get(key)

    if entry is None:
        return "generate", None
    if entry.status == REJECTED:
        return "prose", None
    if entry.servable and not entry.stale():
        return "serve", entry.payload
    return "generate", None


def stats() -> dict[str, Any]:
    """Cache hit rate, generations avoided, per-gate failure counts."""
    return STATS.payload()


def record_gate_failure(gate: str) -> None:
    STATS.gate_failures[gate] = STATS.gate_failures.get(gate, 0) + 1
