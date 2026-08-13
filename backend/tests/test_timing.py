"""The instrumentation has to be right, or every later phase optimises a lie."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app import timing
from app.timing import (
    ABSENT_REASONS,
    D_BUFFER_HOLD,
    D_MODEL_CALL,
    AUXILIARY_STAGES,
    DURATION_STAGES,
    MILESTONE_STAGES,
    STAGES,
    T_AGENT_FIRST_DELTA,
    T_AGENT_FIRST_TOOL,
    T_EMBED,
    T_HISTORY,
    T_IDENTITY,
    T_LANG,
    T_OPEN_CONVERSATION,
    T_PROMPT_BUILD,
    T_RETRIEVE,
    T_RETRIEVE_KICKOFF,
    T_RETRIEVE_TOTAL,
    T_RETRIEVE_WAIT,
    T_SESSION_WAIT,
    T_CONCURRENT_WAIT,
    T_TOTAL,
    T_TTFT,
    TimingRing,
    TurnTimings,
    percentile,
)


def _turn(**stages: float) -> TurnTimings:
    turn = TurnTimings(request_id="test", t0=0.0)
    for name, value in stages.items():
        turn.record(name, value)
    return turn


# --- percentiles ---------------------------------------------------------


def test_percentile_is_nearest_rank_not_interpolated():
    """p95 must be a request that really happened, not a number between two."""
    values = [float(n) for n in range(1, 31)]
    assert percentile(values, 50) == 15.0
    assert percentile(values, 95) == 29.0
    assert percentile(values, 99) == 30.0
    assert all(percentile(values, p) in values for p in (50, 95, 99))


def test_percentile_rejects_an_empty_sample():
    with pytest.raises(ValueError):
        percentile([], 95)


# --- absent vs zero ------------------------------------------------------


def test_a_stage_that_never_ran_is_absent_not_zero():
    """The whole point: `t_lang` must never appear as 0.0 ms."""
    payload = _turn(**{T_TTFT: 1000.0}).payload()
    assert T_LANG not in payload
    assert payload["t_ttft"] == 1000.0


def test_absent_stages_are_reported_with_a_reason():
    ring = TimingRing(capacity=4)
    ring.add(_turn(**{T_TTFT: 1000.0}))
    entry = ring.summary()["stages"][T_LANG]
    assert entry["count"] == 0
    assert entry["reason"] == ABSENT_REASONS[T_LANG]
    assert "supplied by the client" in entry["reason"]


def test_a_stage_explicitly_recorded_as_zero_is_reported():
    """`record(stage, 0.0)` means "it ran and cost nothing", which is a fact."""
    ring = TimingRing(capacity=4)
    ring.add(_turn(**{T_IDENTITY: 0.0, T_TTFT: 1000.0}))
    assert ring.summary()["stages"][T_IDENTITY]["count"] == 1


# --- derived durations ---------------------------------------------------


def test_the_model_call_excludes_every_pre_model_stage():
    payload = _turn(
        **{
            T_RETRIEVE_KICKOFF: 0.2,
            # The owner lookup and the window read, overlapped (P13-007).
            T_SESSION_WAIT: 710.0,
            T_CONCURRENT_WAIT: 850.0,
            T_PROMPT_BUILD: 1.0,
            T_AGENT_FIRST_DELTA: 2500.0,
        }
    ).payload()
    # 2500 cumulative, less the 1561.2 accounted for ahead of the model.
    assert payload[D_MODEL_CALL] == pytest.approx(938.8)


def test_the_model_call_does_not_subtract_the_concurrent_session_reads():
    """The owner lookup and the window read overlap, so only the WAIT is on the path."""
    payload = _turn(
        **{
            T_SESSION_WAIT: 700.0,
            T_IDENTITY: 300.0,
            T_HISTORY: 690.0,
            T_AGENT_FIRST_DELTA: 2000.0,
        }
    ).payload()
    # 2000 - 700 = 1300.
    assert payload[D_MODEL_CALL] == pytest.approx(1300.0)


def test_the_model_call_does_not_subtract_concurrent_retrieval():
    """Retrieval overlaps the database work, so only the WAIT is off the path."""
    payload = _turn(
        **{
            T_CONCURRENT_WAIT: 820.0,
            T_OPEN_CONVERSATION: 800.0,
            T_RETRIEVE_WAIT: 810.0,
            T_EMBED: 500.0,
            T_RETRIEVE: 450.0,
            T_RETRIEVE_TOTAL: 950.0,
            T_AGENT_FIRST_DELTA: 2000.0,
        }
    ).payload()
    # 2000 - 820 = 1180.
    assert payload[D_MODEL_CALL] == pytest.approx(1180.0)


def test_the_model_call_stops_at_the_delta_so_the_buffer_hold_is_not_double_counted():
    """Ending the model call at `t_ttft` would swallow `d_buffer_hold`."""
    payload = _turn(
        **{
            T_CONCURRENT_WAIT: 800.0,
            T_AGENT_FIRST_DELTA: 2000.0,
            T_TTFT: 2500.0,
        }
    ).payload()
    assert payload[D_MODEL_CALL] == pytest.approx(1200.0)
    assert payload[D_BUFFER_HOLD] == pytest.approx(500.0)
    # Together with the pre-model work they must bridge request to first token.
    assert 800.0 + payload[D_MODEL_CALL] + payload[D_BUFFER_HOLD] == pytest.approx(
        payload[T_TTFT]
    )


def test_retrieve_is_the_retriever_span_less_the_embedding():
    payload = _turn(**{T_EMBED: 500.0, T_RETRIEVE_TOTAL: 506.0}).payload()
    assert payload[T_RETRIEVE] == pytest.approx(6.0)


def test_buffer_hold_is_the_gap_between_a_token_existing_and_being_sent():
    payload = _turn(**{T_AGENT_FIRST_DELTA: 4000.0, T_TTFT: 4250.0}).payload()
    assert payload[D_BUFFER_HOLD] == pytest.approx(250.0)


def test_derived_durations_are_never_negative():
    """Measured stages exceeding the milestone must not publish -900 ms."""
    payload = _turn(**{T_AGENT_FIRST_DELTA: 100.0, T_SESSION_WAIT: 1000.0}).payload()
    assert payload[D_MODEL_CALL] == 0.0


def test_derivation_is_skipped_when_its_inputs_are_missing():
    payload = _turn(**{T_TTFT: 1000.0}).payload()
    assert D_MODEL_CALL not in payload


def test_a_card_turn_derives_no_model_call():
    """A card turn produces no text, so there is no first delta to measure to."""
    payload = _turn(
        **{T_OPEN_CONVERSATION: 800.0, T_AGENT_FIRST_TOOL: 1500.0, T_TOTAL: 3000.0}
    ).payload()
    assert D_MODEL_CALL not in payload
    assert D_BUFFER_HOLD not in payload


def test_the_ttft_budget_reconstructs_ttft():
    """The durations must account for TTFT, or the table misleads."""
    turn = _turn(
        **{
            T_RETRIEVE_KICKOFF: 0.2,
            T_IDENTITY: 0.0,
            T_HISTORY: 680.0,
            T_CONCURRENT_WAIT: 845.0,
            T_PROMPT_BUILD: 0.2,
            T_OPEN_CONVERSATION: 830.0,
            T_RETRIEVE_WAIT: 840.0,
            T_EMBED: 480.0,
            T_RETRIEVE_TOTAL: 930.0,
            T_AGENT_FIRST_DELTA: 3000.0,
            T_TTFT: 3000.4,
        }
    )
    payload = turn.payload()
    accounted = sum(payload[name] for name in DURATION_STAGES if name in payload)
    assert accounted == pytest.approx(payload[T_TTFT], abs=0.01)


def test_concurrent_retrieval_is_not_in_the_ttft_budget():
    """Embed and retrieve must be auxiliary, or the shares over-sum."""
    assert T_EMBED not in DURATION_STAGES
    assert T_RETRIEVE not in DURATION_STAGES
    assert T_EMBED in AUXILIARY_STAGES
    assert T_RETRIEVE in AUXILIARY_STAGES
    assert T_CONCURRENT_WAIT in DURATION_STAGES
    # The write and the search overlap, so only the single `t_concurrent_wait` is a budget line.
    assert T_OPEN_CONVERSATION in AUXILIARY_STAGES
    assert T_RETRIEVE_WAIT in AUXILIARY_STAGES


# --- first write wins, and repeats ---------------------------------------


def test_first_write_wins_so_a_second_retrieval_cannot_overwrite_ttft():
    turn = _turn(**{T_EMBED: 500.0})
    turn.record(T_EMBED, 9999.0)
    assert turn.stages[T_EMBED] == 500.0


def test_a_repeated_retrieval_is_reported():
    turn = _turn(**{T_EMBED: 500.0})
    turn.record(T_EMBED, 480.0)
    assert turn.payload()["repeated_stages"] == 1


def test_marking_a_milestone_repeatedly_is_not_counted_as_a_repeat():
    """`mark` is called once per streamed chunk on purpose."""
    turn = TurnTimings(request_id="test", t0=0.0)
    for _ in range(100):
        turn.mark(T_AGENT_FIRST_TOOL)
    assert "repeated_stages" not in turn.payload()


# --- the context var ------------------------------------------------------


def test_stage_outside_a_turn_is_a_no_op():
    """Instrumented code must stay callable from ingest, evals and tests."""
    assert timing.current() is None
    with timing.stage(T_EMBED):
        pass
    timing.record_stage(T_EMBED, 5.0)
    timing.mark_stage(T_TTFT)
    timing.annotate(cache_hit=True)
    assert timing.current() is None


def test_a_bound_turn_is_visible_to_code_that_did_not_receive_it():
    """The ContextVar is how `rag.py` finds the turn from inside langgraph."""
    with timing.bind(timing.begin(endpoint="/test")) as turn:
        assert timing.current() is turn
        timing.record_stage(T_EMBED, 42.0)
    assert turn.stages[T_EMBED] == 42.0
    assert timing.current() is None


def test_a_turn_is_visible_inside_langchains_worker_thread():
    """The turn must survive the hop into the thread the retriever runs in."""
    from langchain_core.runnables.config import run_in_executor

    async def scenario() -> TurnTimings:
        with timing.bind(timing.begin(endpoint="/test")) as turn:
            await run_in_executor(None, timing.record_stage, T_EMBED, 7.0)
        return turn

    assert asyncio.run(scenario()).stages[T_EMBED] == 7.0


def test_a_turn_is_visible_inside_asyncio_to_thread():
    """`asyncio.to_thread` copies the context too -- as `synthesise` relies on."""

    async def scenario() -> TurnTimings:
        with timing.bind(timing.begin(endpoint="/test")) as turn:
            await asyncio.to_thread(timing.record_stage, T_EMBED, 11.0)
        return turn

    assert asyncio.run(scenario()).stages[T_EMBED] == 11.0


def test_finish_on_exit_false_leaves_the_turn_open():
    ring = TimingRing(capacity=4)
    original, timing.RING = timing.RING, ring
    try:
        turn = timing.begin(endpoint="/test")
        with timing.bind(turn, finish_on_exit=False):
            pass
        assert ring.summary()["turns"] == 0
        with timing.bind(turn):
            pass
        assert ring.summary()["turns"] == 1
    finally:
        timing.RING = original


def test_a_turn_that_raises_is_still_emitted():
    ring = TimingRing(capacity=4)
    original, timing.RING = timing.RING, ring
    try:
        with pytest.raises(RuntimeError):
            with timing.bind(timing.begin(endpoint="/test")):
                timing.record_stage(T_HISTORY, 5.0)
                raise RuntimeError("model call died")
        summary = ring.summary()
        assert summary["turns"] == 1
        assert summary["stages"][T_HISTORY]["count"] == 1
        assert summary["stages"][T_TOTAL]["count"] == 1
    finally:
        timing.RING = original


# --- cold start ----------------------------------------------------------


def test_cold_start_is_true_once_and_then_never():
    timing.reset_cold_start()
    assert timing.take_cold_start() is True
    assert timing.take_cold_start() is False
    assert timing.take_cold_start() is False


# --- the ring ------------------------------------------------------------


def test_the_ring_is_bounded_and_keeps_the_most_recent():
    ring = TimingRing(capacity=3)
    for value in (1.0, 2.0, 3.0, 4.0, 5.0):
        ring.add(_turn(**{T_TTFT: value}))
    summary = ring.summary()
    assert summary["turns"] == 3
    assert summary["capacity"] == 3
    assert summary["stages"][T_TTFT]["min"] == 3.0
    assert summary["stages"][T_TTFT]["max"] == 5.0


def test_the_ring_can_report_a_window_of_its_most_recent_turns():
    ring = TimingRing(capacity=100)
    for value in range(1, 61):
        ring.add(_turn(**{T_TTFT: float(value)}))
    assert ring.summary(last=30)["stages"][T_TTFT]["min"] == 31.0


def test_the_ring_counts_cold_starts_and_cache_hits():
    ring = TimingRing(capacity=4)
    cold = _turn(**{T_TTFT: 1.0})
    cold.cold_start = True
    hit = _turn(**{T_TTFT: 2.0})
    hit.cache_hit = True
    ring.add(cold)
    ring.add(hit)
    summary = ring.summary()
    assert summary["cold_starts"] == 1
    assert summary["cache_hits"] == 1


def test_every_stage_appears_in_a_summary():
    """A stage that is defined but never rendered is a stage nobody reads."""
    summary = TimingRing(capacity=1).summary()
    assert set(summary["stages"]) == set(STAGES)


def test_duration_and_milestone_stages_do_not_overlap():
    """The share-of-TTFT column is only valid if these stay disjoint."""
    assert not set(DURATION_STAGES) & set(MILESTONE_STAGES)


# --- the log line ---------------------------------------------------------


def test_the_log_line_is_one_json_object_with_the_required_labels(caplog):
    turn = TurnTimings(
        request_id="abc123",
        t0=0.0,
        persona="stella",
        lang="fr",
        input_token_count=38,
        output_token_count=47,
        retrieved_chunk_count=4,
        cold_start=True,
        endpoint="/chat/stream",
    )
    turn.record(T_TTFT, 4400.0)

    with caplog.at_level(logging.INFO, logger="aspire.timing"):
        timing.emit(turn)

    assert len(caplog.records) == 1
    line = caplog.records[0].getMessage()
    assert "\n" not in line, "must stay one grep-able line"
    body = json.loads(line)
    for field in (
        "request_id",
        "persona",
        "lang",
        "input_token_count",
        "output_token_count",
        "retrieved_chunk_count",
        "cache_hit",
        "cold_start",
    ):
        assert field in body, field
    assert body["request_id"] == "abc123"
    assert body["cache_hit"] is False
    assert body["cold_start"] is True


# --- the endpoint gate ---------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_the_endpoint_gate_defaults_to_closed(monkeypatch, value, expected):
    monkeypatch.setenv("TIMINGS_ENDPOINT_ENABLED", value)
    assert timing.timings_endpoint_enabled() is expected


def test_the_endpoint_gate_is_closed_when_unset(monkeypatch):
    monkeypatch.delenv("TIMINGS_ENDPOINT_ENABLED", raising=False)
    assert timing.timings_endpoint_enabled() is False
