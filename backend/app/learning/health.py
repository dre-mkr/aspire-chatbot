"""What the learning agent did over the last 24 hours, and whether it is well."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: Thresholds from §12 of the Track L brief. Above these is a regression.
TEACH_FALLBACK_MAX = 0.02
WIDGET_GATE_FAILED_MAX = 0.15
RESOLUTION_NONE_MAX = 0.08

#: How many hours of counters are kept.
RETENTION_HOURS = 48

_PREFIX = "learn:health"


def _hour_key(moment: datetime | None = None) -> str:
    now = moment or datetime.now(timezone.utc)
    return now.strftime("%Y%m%d%H")


@dataclass(slots=True)
class TurnMetrics:
    """One learning turn, as numbers."""

    concept_id: str | None = None
    resolution_source: str = "none"
    similarity: float = 0.0
    move: str = ""
    band: str = "9-12"
    locale: str = "en"
    prose_words: int = 0
    teach_retry: bool = False
    teach_fallback: str = "none"
    widget_kind: str | None = None
    widget_gate_failed: str | None = None
    widget_cache_hit: bool = False
    widget_latency_ms: int = 0
    ttft_ms: int = 0
    total_ms: int = 0
    mastery_before: int = 0
    mastery_after: int = 0
    escalated: bool = False

    def counters(self) -> dict[str, int]:
        """The increments this turn contributes."""
        counts: dict[str, int] = {"turns": 1}
        if self.teach_fallback == "template":
            counts["teach_fallback"] = 1
        if self.teach_retry:
            counts["teach_retry"] = 1
        if self.resolution_source == "none":
            counts["resolution_none"] = 1
        if self.resolution_source == "rag":
            counts["resolution_rag"] = 1
        if self.prose_words == 0:
            # No rate, no tolerance. See the module docstring.
            counts["zero_prose"] = 1
        if self.widget_kind:
            counts["widget_emitted"] = 1
        if self.widget_gate_failed and self.widget_gate_failed != "none":
            counts["widget_gate_failed"] = 1
            counts[f"gate:{self.widget_gate_failed}"] = 1
        if self.widget_cache_hit:
            counts["widget_cache_hit"] = 1
        if self.escalated:
            counts["escalated"] = 1
        counts[f"band:{self.band}"] = 1
        counts[f"move:{self.move}"] = 1
        if self.concept_id:
            counts[f"concept:{self.concept_id}"] = 1
        # Latency is summed and divided rather than sampled into buckets.
        counts["ttft_ms_total"] = self.ttft_ms
        counts["total_ms_total"] = self.total_ms
        return counts


async def record(metrics: TurnMetrics) -> None:
    """Add one turn to the current hour. Never raises, never blocks meaningfully."""
    try:
        from app.cache import get_client

        client = get_client()
        if client is None:
            return
        key = f"{_PREFIX}:{_hour_key()}"
        pipeline = client.pipeline()
        for field_name, amount in metrics.counters().items():
            pipeline.hincrby(key, field_name, amount)
        pipeline.expire(key, RETENTION_HOURS * 3600)
        await pipeline.execute()
    except Exception:
        logger.debug("Could not record learning health metrics.", exc_info=True)


async def _read_window(hours: int = 24) -> dict[str, int]:
    """Every counter over the last `hours`, summed."""
    from app.cache import get_client

    client = get_client()
    if client is None:
        return {}

    from datetime import timedelta

    now = datetime.now(timezone.utc)
    keys = [f"{_PREFIX}:{_hour_key(now - timedelta(hours=offset))}" for offset in range(hours)]

    totals: dict[str, int] = {}
    pipeline = client.pipeline()
    for key in keys:
        pipeline.hgetall(key)
    for bucket in await pipeline.execute():
        for field_name, value in (bucket or {}).items():
            name = field_name.decode() if isinstance(field_name, bytes) else str(field_name)
            try:
                totals[name] = totals.get(name, 0) + int(value)
            except (TypeError, ValueError):
                continue
    return totals


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


@dataclass(slots=True)
class Health:
    window_hours: int
    turns: int
    teach_fallback_rate: float
    teach_retry_rate: float
    widget_drop_rate: float
    widget_cache_hit_rate: float
    resolution_none_rate: float
    resolution_rag_rate: float
    zero_prose_turns: int
    escalated_turns: int
    mean_ttft_ms: int
    mean_total_ms: int
    gate_failures: dict[str, int] = field(default_factory=dict)
    concept_coverage: list[dict[str, Any]] = field(default_factory=list)
    band_mix: dict[str, int] = field(default_factory=dict)
    move_mix: dict[str, int] = field(default_factory=dict)
    breaches: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.breaches


async def snapshot(hours: int = 24) -> Health:
    """The health surface. Breaches are computed here, not left to the reader."""
    try:
        totals = await _read_window(hours)
    except Exception:
        logger.warning("Could not read learning health counters.", exc_info=True)
        totals = {}

    turns = totals.get("turns", 0)
    widgets_attempted = totals.get("widget_emitted", 0) + totals.get("widget_gate_failed", 0)

    health = Health(
        window_hours=hours,
        turns=turns,
        teach_fallback_rate=_rate(totals.get("teach_fallback", 0), turns),
        teach_retry_rate=_rate(totals.get("teach_retry", 0), turns),
        widget_drop_rate=_rate(totals.get("widget_gate_failed", 0), widgets_attempted),
        widget_cache_hit_rate=_rate(totals.get("widget_cache_hit", 0), widgets_attempted),
        resolution_none_rate=_rate(totals.get("resolution_none", 0), turns),
        resolution_rag_rate=_rate(totals.get("resolution_rag", 0), turns),
        zero_prose_turns=totals.get("zero_prose", 0),
        escalated_turns=totals.get("escalated", 0),
        mean_ttft_ms=int(totals.get("ttft_ms_total", 0) / turns) if turns else 0,
        mean_total_ms=int(totals.get("total_ms_total", 0) / turns) if turns else 0,
        gate_failures={
            name[len("gate:") :]: count
            for name, count in totals.items()
            if name.startswith("gate:")
        },
        concept_coverage=sorted(
            (
                {"concept_id": name[len("concept:") :], "turns": count}
                for name, count in totals.items()
                if name.startswith("concept:")
            ),
            key=lambda entry: -entry["turns"],
        )[:40],
        band_mix={
            name[len("band:") :]: count
            for name, count in totals.items()
            if name.startswith("band:")
        },
        move_mix={
            name[len("move:") :]: count
            for name, count in totals.items()
            if name.startswith("move:")
        },
    )

    # Breaches are only meaningful with turns behind them.
    if turns >= 20:
        if health.teach_fallback_rate > TEACH_FALLBACK_MAX:
            health.breaches.append(
                f"teach_fallback_rate {health.teach_fallback_rate:.1%} exceeds "
                f"{TEACH_FALLBACK_MAX:.0%}"
            )
        if health.resolution_none_rate > RESOLUTION_NONE_MAX:
            health.breaches.append(
                f"resolution_none_rate {health.resolution_none_rate:.1%} exceeds "
                f"{RESOLUTION_NONE_MAX:.0%} -- learners are asking about concepts "
                "nobody has authored"
            )
    if widgets_attempted >= 20 and health.widget_drop_rate > WIDGET_GATE_FAILED_MAX:
        health.breaches.append(
            f"widget_drop_rate {health.widget_drop_rate:.1%} exceeds "
            f"{WIDGET_GATE_FAILED_MAX:.0%}"
        )
    if health.zero_prose_turns:
        # No minimum turn count. One is a regression.
        health.breaches.append(
            f"{health.zero_prose_turns} turn(s) emitted NO PROSE -- this is a P0"
        )

    return health
