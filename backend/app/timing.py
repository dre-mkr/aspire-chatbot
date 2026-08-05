"""Per-stage latency instrumentation for one chat turn.

Measurement only. Nothing here changes what the assistant says, which stage runs,
or in what order -- every span is a `perf_counter` read on either side of work
that was already happening.

## Why a ContextVar rather than a parameter

Several of the interesting stages are not reachable from the endpoint. The
embedding call and the vector query are recorded by wrappers inside `app.rag`,
which the endpoint reaches through `BaseRetriever.ainvoke` -- and since P13-005
through an `asyncio.Task` as well, so the retrieval happens concurrently with the
database work rather than in the endpoint's own frame. Threading a timer down
through LangChain's internals to get there is not an option, so the active turn is
held in a `ContextVar` and the deep code records into it.

(Until P13-005 the reason was stronger still: retrieval was a *tool* the agent
chose to call, so it happened several frames inside `langgraph`'s executor. That
is gone, but the plumbing is still the right shape -- `create_task` copies the
context, so a turn stays visible to the task it spawns.)

`ContextVar` is also the reason this works when a retriever runs in a worker
thread. LangChain wraps a sync retriever with `run_in_executor`, which copies the
context into the thread -- so the value is visible there. It is a *copy of the
mapping*, though, not of the object, which is why `TurnTimings` is mutated in
place and never rebound: a rebind inside the thread would be invisible to the
request, a mutation is not.

## Absent stages are absent, not zero

Several stages the brief asks for have nothing to time. Language is supplied by
the client, not detected; persona and account status arrive on the request and
nothing on the chat path resolves them. Recording `0.0` for those would put a
real-looking number in a baseline table that later phases would then try to
optimise. So a stage that never ran is simply missing from the payload, the
percentile table prints `n/a`, and the reason is documented next to the name.
"""

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

# --- Stage names ---------------------------------------------------------
# Spelled as constants so a typo is an ImportError rather than a stage that
# silently never appears in the table.

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

#: The two database round trips that run before the agent does. Neither is in the
#: brief's stage list, and leaving them out put roughly a second of Neon latency
#: inside an opaque "first model call" milestone where nobody would look for it.
#: `t_identity` is also the nearest real thing to the brief's `t_account`: there is
#: no account-status lookup on this path, but there is an ownership lookup.
#:
#: Both are auxiliary as of P13-007: `t_identity` now runs concurrently with the
#: window read, so it is no longer time the reader waits -- `t_session_wait` is.
T_IDENTITY = "t_identity"
T_OPEN_CONVERSATION = "t_open_conversation"

#: Wall time waiting for the identity lookup and the history window read, which
#: P13-007 made concurrent (P13-005 did the same for the search and the write).
#:
#: They are independent -- `owner_id_for` needs only the token, `load_context`
#: needs only the thread id -- and were awaited one after the other, so an
#: authenticated caller paid two Neon round trips end to end before the model was
#: called. One `asyncio.gather` makes the pair cost the slower of the two.
#:
#: ONE stage for the pair, for the same reason `t_concurrent_wait` is one stage:
#: summing two overlapping durations is not a budget, it is an over-count. The
#: individual figures stay in the auxiliary block, where comparing them against
#: this one shows how much of the shorter leg the overlap absorbed.
T_SESSION_WAIT = "t_session_wait"

#: What the reader waits for the response-cache lookup (P13-006).
#:
#: On a HIT this is essentially the whole turn: no model call, no retrieval, no
#: history. On a MISS it is pure added cost, which is the trade this phase makes --
#: so it is measured rather than assumed cheap. It overlaps the corpus search, so
#: on a miss most of it should be absorbed.
T_CACHE_LOOKUP = "t_cache_lookup"

#: Cost of *starting* the concurrent corpus search, not of running it (P13-005).
#: Should be microseconds -- it is `asyncio.create_task`. Recorded so that if it
#: ever stops being free, the reason is visible rather than hidden inside the
#: unaccounted residual.
T_RETRIEVE_KICKOFF = "t_retrieve_kickoff"

#: Wall time waiting for everything that runs concurrently before the model: the
#: corpus search and the conversation write. ONE stage for the pair on purpose --
#: they overlap, so counting each separately double-counts the overlap and can
#: make the pre-model total exceed the elapsed time it is a part of. (Measured
#: exactly that on the first cut: `t_open_conversation` 855 ms plus
#: `t_retrieve_wait` 1030 ms against 1534 ms actually elapsed, which clamped the
#: derived model figure to zero.)
#:
#: This is the number the phase is about. Compare it against `t_retrieve_total`
#: and `t_open_conversation` in the auxiliary block to see how much of their cost
#: the overlap actually absorbed.
T_CONCURRENT_WAIT = "t_concurrent_wait"

#: Of that concurrent block, how long the corpus search specifically took to
#: arrive. Diagnostic only -- it overlaps `t_open_conversation`, so it is not a
#: budget line.
T_RETRIEVE_WAIT = "t_retrieve_wait"

#: The layer-2 semantic cache's shelf read and comparison (P14-B), NOT counting
#: the wait for the query embedding it consumes -- that wait overlaps retrieval,
#: which needed the same vector. Auxiliary: the probe runs concurrently and is
#: consulted after the prompt is prepared, so on a miss it costs the reader
#: nothing and on a hit it IS the turn.
T_SEMANTIC_LOOKUP = "t_semantic_lookup"

#: Two stages the brief does not name, added because without them the table
#: measures everything except the thing that dominates it.
#:
#: In a tool-using agent the visible answer cannot begin until the tools have
#: run, and `app.streaming.TurnBuffer` enforces exactly that -- no text is
#: released to the client before a tool call has been seen. So the path to the
#: first token a reader sees is: model call #1 (which emits the tool call),
#: then embed, then the vector query, then model call #2. `t_agent_first_tool`
#: is the cost of that first model call, and it is invisible in every stage
#: above.
T_AGENT_FIRST_TOOL = "t_agent_first_tool"
#: First raw delta out of the agent, before `TurnBuffer` decides whether it may
#: be forwarded. `t_ttft - t_agent_first_delta` is what the suppression rule
#: costs, which is worth knowing separately from what the model costs.
T_AGENT_FIRST_DELTA = "t_agent_first_delta"

#: Durations derived by subtraction, because the model calls cannot be timed
#: directly from out here -- the agent does not announce "I am now waiting on the
#: model", it just goes quiet between a request and a tool call. Each is the gap
#: between two things that ARE measured, and each is named for what happens in it.
#: The one answering model call (P13-005). There used to be two -- one to decide
#: to retrieve, one to write the answer -- and `d_model_call_1` / `d_model_call_2`
#: measured them separately. With the corpus already in the prompt there is a
#: single call, so there is a single figure.
#:
#: Ends at the model's first DELTA, not at the first token the client sees. The
#: gap between those two is `d_buffer_hold`, and ending this span at `t_ttft`
#: instead would swallow it -- the budget would then double-count the hold and
#: quietly overshoot `t_ttft`.
D_MODEL_CALL = "d_model_call"
D_BUFFER_HOLD = "d_buffer_hold"

#: Measured elapsed time for one piece of work. These are the only stages a
#: "share of TTFT" column may be computed for, and they should sum to
#: approximately `t_ttft`.
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

#: The stages that make up the pre-model critical path, in order. `_derive` sums
#: these to work out what the model call itself cost, so anything added to the
#: path ahead of the model belongs here or it will be attributed to the model --
#: and anything that runs CONCURRENTLY must stay out, or the model figure is
#: understated by the overlap.
PRE_MODEL_STAGES: tuple[str, ...] = (
    T_RETRIEVE_KICKOFF,
    T_CACHE_LOOKUP,
    T_SESSION_WAIT,
    T_CONCURRENT_WAIT,
    T_PROMPT_BUILD,
)

#: Cumulative stamps, measured from "request received". A share of TTFT is
#: meaningless for these -- `t_agent_first_tool` already CONTAINS `t_history` --
#: and a table that mixes them into the same percentage column is a table
#: somebody will try to add up.
MILESTONE_STAGES: tuple[str, ...] = (
    T_AGENT_FIRST_TOOL,
    T_AGENT_FIRST_DELTA,
    T_TTFT,
    T_TOTAL,
)

#: Reported, but part of no budget.
#:
#: `t_embed` and `t_retrieve` moved here in P13-005 and the reason is the whole
#: point of that phase: retrieval now runs CONCURRENTLY with the database work, so
#: its duration is no longer time the reader waits. What the reader waits for is
#: `t_retrieve_wait`, which is in the budget. Leaving embed and retrieve in the
#: budget would double-count them against the stages they overlap and make the
#: shares sum to well over TTFT.
#:
#: `t_retrieve_total` is `t_embed` plus `t_retrieve` and would double-count those
#: in turn. TTS is a different request entirely.
#: `t_identity` and `t_history` joined them in P13-007, for exactly the same
#: reason: the pair now runs concurrently, so `t_session_wait` is what the reader
#: waits and these two are the diagnostic breakdown of it.
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

#: Why a stage is expected to be missing or near-zero, printed beside `n/a` so
#: the baseline explains itself without needing this file open next to it.
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
    T_RETRIEVE: "concurrent: Neon cosine scan over 332 rows (off the critical path)",
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
    #: `perf_counter` at the moment the request was accepted. Every `t_*` that
    #: is a point-in-time measurement (TTFT, total) is measured from here.
    t0: float
    persona: str | None = None
    lang: str | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None
    retrieved_chunk_count: int | None = None
    cache_hit: bool = False
    #: Which layer answered a hit: "exact" or "semantic" (P14-B). None on a miss.
    cache_layer: str | None = None
    #: The provider's own count of the prompt, and how much of it was served
    #: from its prefix cache (P14-A). Billed truth, against which
    #: `input_token_count` is our tiktoken estimate.
    provider_input_tokens: int | None = None
    provider_cached_input_tokens: int | None = None
    #: The query embedding came from Valkey rather than the provider (P14-D).
    embed_cache_hit: bool = False
    cold_start: bool = False
    endpoint: str = ""
    stages: dict[str, float] = field(default_factory=dict)

    def record(self, stage: str, milliseconds: float, *, count_repeat: bool = True) -> None:
        """Store a span. First write wins.

        First-write-wins is what makes the `t_*_first_*` stages mean what their
        names say: the agent calls the retriever once per turn in the ordinary
        case but is free to call it twice when the first results are weak, and a
        second call must not overwrite the number that TTFT was actually built
        from.

        `_repeats` then records that it happened, which is a real signal -- a turn
        that embedded and searched twice paid for it -- so it deliberately counts
        only `record` and not `mark`. The milestone marks are called once per
        streamed chunk on purpose, and letting those in buried the one interesting
        case under a hundred-odd routine repeats.
        """
        if stage in self.stages:
            if count_repeat:
                self.stages["_repeats"] = self.stages.get("_repeats", 0.0) + 1
            return
        self.stages[stage] = round(milliseconds, 3)

    def mark(self, stage: str) -> None:
        """Record a stage as `now - t0`, for the point-in-time measurements.

        Safe to call on every chunk: the first call wins and the rest are free.
        """
        self.record(stage, _ms(self.t0, time.perf_counter()), count_repeat=False)

    def has(self, stage: str) -> bool:
        return stage in self.stages

    def _derive(self) -> None:
        """Fill in the stages that are differences between other stages.

        Every one is guarded on its inputs and clamped at zero. A negative
        derived duration means the arithmetic assumed an ordering the run did not
        have -- an agent that answered without calling a tool, for instance -- and
        publishing a negative millisecond count would be worse than publishing
        nothing.
        """
        got = self.stages

        # The retriever span contains the embedding call, because Chroma embeds
        # the query inside `similarity_search` and there is no seam from outside.
        if T_RETRIEVE_TOTAL in got and T_EMBED in got:
            got.setdefault(T_RETRIEVE, max(0.0, round(got[T_RETRIEVE_TOTAL] - got[T_EMBED], 3)))

        # The answering model call: from the request arriving to text existing,
        # less every pre-model stage we measured ourselves along the way.
        #
        # Retrieval is deliberately NOT subtracted here even though it happened in
        # that window. It ran concurrently, so the only part of it the model call
        # waited behind is `t_retrieve_wait` -- which is in `PRE_MODEL_STAGES` and
        # is therefore already out. Subtracting `t_retrieve_total` as well would
        # remove time nothing spent.
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


# The turn currently being served. `None` outside a request, which is what makes
# `record_stage` safe to call from code that also runs in the ingest script, the
# eval harness and the test suite.
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
    """Start the clock for one turn, without publishing it yet.

    Split from `bind` because on the streaming path the two happen in different
    frames: the endpoint knows the persona and the language and must start the
    clock the moment the request arrives, but the turn is only *served* later,
    inside the generator that `StreamingResponse` drives.
    """
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
    """Publish a turn for the duration of the block, then finish it.

    `finish_on_exit=False` publishes without closing, for the streaming path's
    awkward shape: work happens in the endpoint frame *before* the generator that
    serves the turn is ever driven, so the turn has to be visible twice and
    emitted once.

    Cleared by assigning `None` rather than by resetting a token, and that is
    load-bearing rather than lazy. On the streaming path this wraps an async
    generator whose body is resumed once per `asend`, so the set and the clear
    happen in different `Context` objects -- and `ContextVar.reset` raises
    `ValueError` when handed a token from another context. Assigning None has
    the same effect here because turns never nest.

    Finishing in `finally` is deliberate: a turn that raised is exactly the turn
    whose timings are worth having, and this way an exception on the model call
    still leaves a line holding everything measured before it died.
    """
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
    """Time a block and record it against the active turn.

    A no-op when there is no active turn, so instrumented code stays callable
    from the ingest script and the tests without either having to know about
    this module.
    """
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


# --- Cold start ----------------------------------------------------------
# True for the first measured turn in this process and never again. The first
# request pays for lazily-built things the rest inherit -- the OpenAI client's
# TLS handshake and connection pool, Chroma opening its SQLite file, tiktoken
# fetching and caching its encoding -- and averaging that in with warm requests
# hides both numbers.
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
    """One structured JSON line per turn.

    Written through `logging` rather than `print` so it lands in the same stream
    as everything else the service says, and at INFO because a latency line is
    not a warning. `json.dumps` with no spaces keeps it one grep-able line.
    """
    try:
        logger.info(json.dumps(timings.payload(), separators=(",", ":"), default=str))
    except Exception:  # pragma: no cover - logging must never fail a request
        logger.warning("Failed to emit turn timings", exc_info=True)


# --- Ring buffer ---------------------------------------------------------


class TimingRing:
    """The last N turns, in memory, for `/debug/timings`.

    In memory and bounded on purpose: this is a debugging aid, not telemetry.
    Nothing here is persisted, nothing is aggregated across processes, and a
    restart loses it -- all three are acceptable for answering "where did that
    request go" during a latency phase, and none of them are acceptable
    properties for a metric anyone makes decisions from later. A real metrics
    pipeline is a different piece of work and should not be quietly grown here.
    """

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
    """Nearest-rank percentile.

    Nearest-rank rather than interpolating, because at the sample sizes this is
    used with -- 30 requests in a probe run -- an interpolated p95 is a number
    between two measurements that reports a latency nothing actually took. The
    rank is `ceil(pct/100 * n)`, so p95 of 30 samples is the 29th slowest and is
    a request that really happened.
    """
    if not sorted_values:
        raise ValueError("percentile of an empty sample")
    if pct <= 0:
        return round(sorted_values[0], 3)
    rank = -(-int(pct) * len(sorted_values) // 100)  # ceil division
    index = min(max(rank - 1, 0), len(sorted_values) - 1)
    return round(sorted_values[index], 3)


#: Capacity is read from the environment rather than Settings because this is
#: diagnostic plumbing that must be usable in a process where Settings has not
#: been built yet (the ingest script, a test importing this alone).
RING = TimingRing(capacity=int(os.environ.get("TIMINGS_RING_CAPACITY", "500") or 500))


def timings_endpoint_enabled() -> bool:
    """Whether `/debug/timings` is mounted.

    Off unless asked for. The payload is not sensitive -- durations, a persona
    and a language, no message text -- but an unauthenticated endpoint that
    reports how the service is performing is reconnaissance, and this exists to
    be switched on for a measurement run and off again afterwards.
    """
    return os.environ.get("TIMINGS_ENDPOINT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
