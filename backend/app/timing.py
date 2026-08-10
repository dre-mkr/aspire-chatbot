"""Per-stage latency instrumentation for one chat turn."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aspire.timing")

# --- Stage names --------------------------------------------------------- Spelled as constants so a typo is a…

T_LANG = "t_lang"
T_PERSONA = "t_persona"
T_ACCOUNT = "t_account"
T_HISTORY = "t_history"
T_EMBED = "t_embed"
T_RETRIEVE = "t_retrieve"
T_RETRIEVE_TOTAL = "t_retrieve_total"
T_PROMPT_BUILD = "t_prompt_build"
T_TTFT = "t_ttft"
T_TOTAL = "t_total"
T_TTS_FIRST_BYTE = "t_tts_first_byte"

#: The two database round trips that run before the agent does.
T_IDENTITY = "t_identity"
T_OPEN_CONVERSATION = "t_open_conversation"

#: Wall time waiting for the identity lookup and the history window read, which P13-007 made concurrent (P13-005…
T_SESSION_WAIT = "t_session_wait"

#: What the reader waits for the response-cache lookup (P13-006).
T_CACHE_LOOKUP = "t_cache_lookup"

#: Cost of *starting* the concurrent corpus search, not of running it (P13-005).
T_RETRIEVE_KICKOFF = "t_retrieve_kickoff"

#: Wall time waiting for everything that runs concurrently before the model: the corpus search and the conversat…
T_CONCURRENT_WAIT = "t_concurrent_wait"

#: Of that concurrent block, how long the corpus search specifically took to arrive.
T_RETRIEVE_WAIT = "t_retrieve_wait"

#: The layer-2 semantic cache's shelf read and comparison (P14-B), NOT counting the wait for the query embedding…
T_SEMANTIC_LOOKUP = "t_semantic_lookup"

#: Two stages the brief does not name, added because without them the table measures everything except the thing…
T_AGENT_FIRST_TOOL = "t_agent_first_tool"
#: First raw delta out of the agent, before `TurnBuffer` decides whether it may be forwarded.
T_AGENT_FIRST_DELTA = "t_agent_first_delta"

#: Durations derived by subtraction, because the model calls cannot be timed directly from out here -- the agent…
D_MODEL_CALL = "d_model_call"
D_BUFFER_HOLD = "d_buffer_hold"

#: Measured elapsed time for one piece of work.
DURATION_STAGES: tuple[str, ...] = (
    T_LANG,
    T_PERSONA,
    T_ACCOUNT,
    T_RETRIEVE_KICKOFF,
    T_CACHE_LOOKUP,
    T_SESSION_WAIT,
    T_CONCURRENT_WAIT,
    T_PROMPT_BUILD,
    D_MODEL_CALL,
    D_BUFFER_HOLD,
)

#: The stages that make up the pre-model critical path, in order.
PRE_MODEL_STAGES: tuple[str, ...] = (
    T_RETRIEVE_KICKOFF,
    T_CACHE_LOOKUP,
    T_SESSION_WAIT,
    T_CONCURRENT_WAIT,
    T_PROMPT_BUILD,
)

#: Cumulative stamps, measured from "request received".
MILESTONE_STAGES: tuple[str, ...] = (
    T_AGENT_FIRST_TOOL,
    T_AGENT_FIRST_DELTA,
    T_TTFT,
    T_TOTAL,
)

#: Reported, but part of no budget.
AUXILIARY_STAGES: tuple[str, ...] = (
    T_IDENTITY,
    T_HISTORY,
    T_OPEN_CONVERSATION,
    T_RETRIEVE_WAIT,
    T_SEMANTIC_LOOKUP,
    T_EMBED,
    T_RETRIEVE,
    T_RETRIEVE_TOTAL,
    T_TTS_FIRST_BYTE,
)

#: Every stage this module can report, in the order a table should show them.
STAGES: tuple[str, ...] = DURATION_STAGES + MILESTONE_STAGES + AUXILIARY_STAGES

#: Why a stage is expected to be missing or near-zero, printed beside `n/a` so the baseline explains itself with…
ABSENT_REASONS: dict[str, str] = {
    T_LANG: "no detection: `language` is supplied by the client (ChatRequest.language)",
    T_PERSONA: "no resolution: `persona` is forwarded to the agent config unread",
    T_ACCOUNT: "no lookup: `account_status` arrives on the request; nothing reads it",
    T_TTS_FIRST_BYTE: "voice path only; /voice/speak is a separate request",
}

#: Printed under a stage name so a table explains its own arithmetic.
STAGE_NOTES: dict[str, str] = {
    T_IDENTITY: "concurrent: Neon owner-id lookup (overlaps the window read)",
    T_OPEN_CONVERSATION: "concurrent: Neon upsert + question write (off the critical path)",
    T_HISTORY: "concurrent: Neon window read + running summary (overlaps the owner lookup)",
    T_SESSION_WAIT: "what the reader waits for the owner lookup AND the window read, overlapped",
    T_CACHE_LOOKUP: "Valkey: response-cache read (the whole turn on a hit)",
    T_RETRIEVE_KICKOFF: "local: asyncio.create_task for the concurrent search",
    T_CONCURRENT_WAIT: "what the reader waits for the search AND the write, overlapped",
    T_RETRIEVE_WAIT: "of that block, the search alone (overlaps the write)",
    T_SEMANTIC_LOOKUP: "concurrent: Valkey semantic-shelf read + compare (off the critical path)",
    T_PROMPT_BUILD: "local: assemble messages, count tokens (tiktoken)",
    D_MODEL_CALL: "derived: the one answering call, less every pre-model stage",
    T_EMBED: "concurrent: OpenAI embedding round trip (off the critical path)",
    T_RETRIEVE: "concurrent: Neon cosine scan over 706 rows (off the critical path)",
    D_BUFFER_HOLD: "derived: TurnBuffer holding text before releasing it",
    T_AGENT_FIRST_TOOL: "cumulative from request received",
    T_AGENT_FIRST_DELTA: "cumulative from request received",
    T_TTFT: "cumulative: request received -> first token to client",
    T_TOTAL: "cumulative: request received -> last token to client",
    T_RETRIEVE_TOTAL: "t_embed + t_retrieve; excluded from the budget to avoid double-counting",
}


def _ms(start: float, end: float) -> float:
    return (end - start) * 1000.0


@dataclass
class TurnTimings:
    """Every span recorded for one request, plus the facts that label them."""

    request_id: str
    #: `perf_counter` at the moment the request was accepted.
    t0: float
    persona: str | None = None
    lang: str | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None
    retrieved_chunk_count: int | None = None
    cache_hit: bool = False
    #: Which layer answered a hit: "exact" or "semantic" (P14-B). None on a miss.
    cache_layer: str | None = None
    #: The provider's own count of the prompt, and how much of it was served from its prefix cache (P14-A).
    provider_input_tokens: int | None = None
    provider_cached_input_tokens: int | None = None
    #: The query embedding came from Valkey rather than the provider (P14-D).
    embed_cache_hit: bool = False
    cold_start: bool = False
    endpoint: str = ""
    stages: dict[str, float] = field(default_factory=dict)

    def record(self, stage: str, milliseconds: float, *, count_repeat: bool = True) -> None:
        """Store a span."""
        if stage in self.stages:
            if count_repeat:
                self.stages["_repeats"] = self.stages.get("_repeats", 0.0) + 1
            return
        self.stages[stage] = round(milliseconds, 3)

    def mark(self, stage: str) -> None:
        """Record a stage as `now - t0`, for the point-in-time measurements."""
        self.record(stage, _ms(self.t0, time.perf_counter()), count_repeat=False)

    def has(self, stage: str) -> bool:
        return stage in self.stages

    def _derive(self) -> None:
        """Fill in the stages that are differences between other stages."""
        got = self.stages

        # The retriever span contains the embedding call, because Chroma embeds the query inside `similarity_search` an…
        if T_RETRIEVE_TOTAL in got and T_EMBED in got:
            got.setdefault(T_RETRIEVE, max(0.0, round(got[T_RETRIEVE_TOTAL] - got[T_EMBED], 3)))

        # The answering model call: from the request arriving to text existing, less every pre-model stage we measured…
        if T_AGENT_FIRST_DELTA in got:
            before_model = sum(got.get(stage, 0.0) for stage in PRE_MODEL_STAGES)
            got.setdefault(
                D_MODEL_CALL, max(0.0, round(got[T_AGENT_FIRST_DELTA] - before_model, 3))
            )

        # What `TurnBuffer` cost by holding text back until a tool had run.
        if T_TTFT in got and T_AGENT_FIRST_DELTA in got:
            got.setdefault(
                D_BUFFER_HOLD, max(0.0, round(got[T_TTFT] - got[T_AGENT_FIRST_DELTA], 3))
            )

    def payload(self) -> dict[str, Any]:
        """The structured log line for this turn."""
        body: dict[str, Any] = {
            "event": "turn_timing",
            "request_id": self.request_id,
            "endpoint": self.endpoint,
            "persona": self.persona,
            "lang": self.lang,
            "input_token_count": self.input_token_count,
            "output_token_count": self.output_token_count,
            "retrieved_chunk_count": self.retrieved_chunk_count,
            "cache_hit": self.cache_hit,
            "cache_layer": self.cache_layer,
            "provider_input_tokens": self.provider_input_tokens,
            "provider_cached_input_tokens": self.provider_cached_input_tokens,
            "embed_cache_hit": self.embed_cache_hit,
            "cold_start": self.cold_start,
        }
        self._derive()
        body.update({stage: self.stages[stage] for stage in STAGES if stage in self.stages})
        if "_repeats" in self.stages:
            body["repeated_stages"] = int(self.stages["_repeats"])
        return body


# The turn currently being served.
_CURRENT: contextvars.ContextVar[TurnTimings | None] = contextvars.ContextVar(
    "aspire_turn_timings", default=None
)


def current() -> TurnTimings | None:
    return _CURRENT.get()


def begin(
    *,
    endpoint: str,
    persona: str | None = None,
    lang: str | None = None,
    request_id: str | None = None,
) -> TurnTimings:
    """Start the clock for one turn, without publishing it yet."""
    return TurnTimings(
        request_id=request_id or uuid.uuid4().hex[:12],
        t0=time.perf_counter(),
        endpoint=endpoint,
        persona=persona,
        lang=lang,
        cold_start=take_cold_start(),
    )


@contextmanager
def bind(timings: TurnTimings, *, finish_on_exit: bool = True) -> Iterator[TurnTimings]:
    """Publish a turn for the duration of the block, then finish it."""
    _CURRENT.set(timings)
    try:
        yield timings
    finally:
        _CURRENT.set(None)
        if finish_on_exit:
            finish(timings)


def finish(timings: TurnTimings) -> None:
    """Close a turn: stamp `t_total`, emit the line, keep it for `/debug/timings`."""
    timings.mark(T_TOTAL)
    emit(timings)
    RING.add(timings)


@contextmanager
def turn(
    *,
    endpoint: str,
    persona: str | None = None,
    lang: str | None = None,
    request_id: str | None = None,
) -> Iterator[TurnTimings]:
    """`begin` + `bind`, for the ordinary case of a turn served in one frame."""
    with bind(
        begin(endpoint=endpoint, persona=persona, lang=lang, request_id=request_id)
    ) as timings:
        yield timings


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Time a block and record it against the active turn."""
    timings = _CURRENT.get()
    if timings is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        timings.record(name, _ms(start, time.perf_counter()))


def record_stage(name: str, milliseconds: float) -> None:
    """Record a span measured by the caller. No-op outside a turn."""
    timings = _CURRENT.get()
    if timings is not None:
        timings.record(name, milliseconds)


def mark_stage(name: str) -> None:
    """Record `now - request start`. No-op outside a turn."""
    timings = _CURRENT.get()
    if timings is not None:
        timings.mark(name)


def annotate(**facts: Any) -> None:
    """Attach labels (token counts, chunk count, cache_hit) to the active turn."""
    timings = _CURRENT.get()
    if timings is None:
        return
    for key, value in facts.items():
        if hasattr(timings, key):
            setattr(timings, key, value)


# --- Cold start ---------------------------------------------------------- True for the first measured turn in…
_cold_start_pending = True
_cold_lock = threading.Lock()


def take_cold_start() -> bool:
    global _cold_start_pending
    with _cold_lock:
        was_cold, _cold_start_pending = _cold_start_pending, False
    return was_cold


def reset_cold_start() -> None:
    """Test and probe hook: pretend this process has served nothing yet."""
    global _cold_start_pending
    with _cold_lock:
        _cold_start_pending = True


# --- Emission ------------------------------------------------------------


def emit(timings: TurnTimings) -> None:
    """One structured JSON line per turn."""
    try:
        logger.info(json.dumps(timings.payload(), separators=(",", ":"), default=str))
    except Exception:  # pragma: no cover - logging must never fail a request
        logger.warning("Failed to emit turn timings", exc_info=True)


# --- Ring buffer ---------------------------------------------------------


class TimingRing:
    """The last N turns, in memory, for `/debug/timings`."""

    def __init__(self, capacity: int = 500) -> None:
        self._turns: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._turns.maxlen or 0

    def add(self, timings: TurnTimings) -> None:
        with self._lock:
            self._turns.append(timings.payload())

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._turns)

    def summary(self, last: int | None = None) -> dict[str, Any]:
        """p50/p95/p99 per stage over the most recent `last` turns."""
        turns = self.snapshot()
        if last is not None and last > 0:
            turns = turns[-last:]

        stages: dict[str, Any] = {}
        for name in STAGES:
            values = sorted(
                turn[name] for turn in turns if isinstance(turn.get(name), (int, float))
            )
            if not values:
                stages[name] = {"count": 0, "reason": ABSENT_REASONS.get(name, "not recorded")}
                continue
            stages[name] = {
                "count": len(values),
                "p50": percentile(values, 50),
                "p95": percentile(values, 95),
                "p99": percentile(values, 99),
                "min": round(values[0], 3),
                "max": round(values[-1], 3),
            }

        return {
            "turns": len(turns),
            "capacity": self.capacity,
            "cold_starts": sum(1 for turn in turns if turn.get("cold_start")),
            "cache_hits": sum(1 for turn in turns if turn.get("cache_hit")),
            "stages": stages,
        }


def percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    if not sorted_values:
        raise ValueError("percentile of an empty sample")
    if pct <= 0:
        return round(sorted_values[0], 3)
    rank = -(-int(pct) * len(sorted_values) // 100)  # ceil division
    index = min(max(rank - 1, 0), len(sorted_values) - 1)
    return round(sorted_values[index], 3)


#: Capacity is read from the environment rather than Settings because this is diagnostic plumbing that must be u…
RING = TimingRing(capacity=int(os.environ.get("TIMINGS_RING_CAPACITY", "500") or 500))


def timings_endpoint_enabled() -> bool:
    """Whether `/debug/timings` is mounted."""
    return os.environ.get("TIMINGS_ENDPOINT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
