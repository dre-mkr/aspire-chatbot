"""Fire 30 representative questions at `/chat/stream` and report where the time went.

Run:
    # terminal 1 -- the endpoint is off unless asked for, and one probe run spends
    # the entire default chat rate-limit window (30 messages / 600s), so a warm run
    # straight after a cold one is otherwise 30 x HTTP 429.
    #
    # The limiter is a FastAPI dependency that runs to completion before the turn
    # begins, so raising it cannot move any figure this script reports.
    TIMINGS_ENDPOINT_ENABLED=1 CHAT_MESSAGES_PER_WINDOW=200 \
        uvicorn app.main:app --port 8001

    # terminal 2 -- cold means "against a process that has served nothing yet",
    # so restart the server before the cold run and do not restart before the warm.
    python -m scripts.latency_probe --base-url http://127.0.0.1:8001 --label cold
    python -m scripts.latency_probe --base-url http://127.0.0.1:8001 --label warm

This SPENDS MODEL CALLS. Thirty turns, each one an agent run with a retrieval
tool call and a follow-up chip call, against whatever `CHAT_MODEL` points at.
It is not a unit test and does not belong in CI.

## Why the questions come out of `evals/golden.yaml`

Hardcoding 30 strings here would create a second, unversioned question set that
drifts from the corpus the moment a row changes. The golden set is already
verified against `data/knowledge_base.csv` (`python -m evals.run --verify-ids`)
and already carries the `lang` and `persona` labels this needs, so the probe
selects from it and asserts its own coverage instead.

Only `grounded` and `exact` cases are used. `refuse` and `ambiguous` turns have a
different latency *shape*, not merely a different duration -- a turn that never
calls the retriever is never released early by `app.streaming.TurnBuffer`, so its
TTFT collapses into its total generation time. Mixing those into a p95 would
produce a number describing no real population. They deserve their own
measurement; see docs/latency-baseline.md.

## Sequential on purpose

`--workers 1` is what this service runs, and concurrent probing would measure
queueing behind the event loop rather than the stages themselves. One at a time
is slower to run and is the only thing that makes a per-stage share meaningful.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.timing import (  # noqa: E402
    ABSENT_REASONS,
    AUXILIARY_STAGES,
    DURATION_STAGES,
    MILESTONE_STAGES,
    STAGE_NOTES,
    T_TTFT,
    percentile,
)

# The console this runs on is cp1252 by default, and a table full of box-drawing
# characters killed the first real run *after* all thirty model calls had been
# paid for. Reconfiguring is cheaper than an ASCII-only table.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - not a real tty
        pass

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "golden.yaml"

#: Ten per language, and within a language the personas are filled round-robin in
#: this order. `stella` is scarcest in the golden set, so it leads: a fixed order
#: starting with the scarce persona is what guarantees all four appear in every
#: language rather than merely on average.
PERSONA_ORDER = ("stella", "orion", "aurora", "nova")
LANGUAGES = ("en", "es", "fr")
PER_LANGUAGE = 10
USABLE_KINDS = frozenset({"grounded", "exact"})


def load_cases() -> list[dict[str, Any]]:
    """Pick a balanced, deterministic 30 out of the golden set."""
    raw = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["cases"]

    pools: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for case in raw:
        if case.get("kind") in USABLE_KINDS:
            pools[(case["lang"], case.get("persona", "nova"))].append(case)

    selected: list[dict[str, Any]] = []
    for lang in LANGUAGES:
        taken: list[dict] = []
        cursors = {persona: 0 for persona in PERSONA_ORDER}
        # Round-robin until the quota is met. Stops if every pool is exhausted,
        # so a shrunken golden set produces a short run and a loud assertion
        # rather than an infinite loop.
        while len(taken) < PER_LANGUAGE:
            progressed = False
            for persona in PERSONA_ORDER:
                if len(taken) >= PER_LANGUAGE:
                    break
                pool = pools.get((lang, persona), [])
                index = cursors[persona]
                if index < len(pool):
                    taken.append(pool[index])
                    cursors[persona] = index + 1
                    progressed = True
            if not progressed:
                break
        selected.extend(taken)

    # The coverage the brief asks for, checked rather than assumed.
    assert len(selected) == PER_LANGUAGE * len(LANGUAGES), (
        f"expected {PER_LANGUAGE * len(LANGUAGES)} cases, selected {len(selected)}"
    )
    for lang in LANGUAGES:
        personas = {case["persona"] for case in selected if case["lang"] == lang}
        assert personas == set(PERSONA_ORDER), f"{lang} covers only {sorted(personas)}"
    return selected


def ask(base_url: str, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One turn. Returns the client's own view of it.

    The client-side TTFT is measured here as well as on the server, and the two
    are reported side by side. They should agree closely; a gap between them is
    framing and transport overhead the server cannot see, and is worth knowing
    about before anybody optimises a stage on the strength of a server number
    alone.
    """
    payload = json.dumps(
        {
            "message": case["q"],
            "persona": case["persona"],
            "language": case["lang"],
            # No thread_id: every probe turn is an opening turn, which is the
            # turn a first-time reader actually waits through.
            "thread_id": None,
        }
    ).encode()

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/stream",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    characters = 0
    error: str | None = None

    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "TEXT_MESSAGE_CONTENT":
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                characters += len(event.get("delta", ""))
            elif kind == "RUN_ERROR":
                error = event.get("message", "unknown")

    finished = time.perf_counter()
    return {
        "id": case["id"],
        "lang": case["lang"],
        "persona": case["persona"],
        "client_ttft_ms": None
        if first_token_at is None
        else round((first_token_at - started) * 1000.0, 3),
        "client_total_ms": round((finished - started) * 1000.0, 3),
        "characters": characters,
        "error": error,
    }


def fetch_summary(base_url: str, last: int) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/debug/timings?last={last}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(
                "/debug/timings returned 404. Start the server with "
                "TIMINGS_ENDPOINT_ENABLED=1."
            ) from None
        raise


def _row(name: str, entry: dict[str, Any], ttft: dict[str, Any], budget: bool) -> list[str]:
    """One stage's row, plus a note row explaining what it is."""
    note = STAGE_NOTES.get(name, "")
    if not entry.get("count"):
        reason = entry.get("reason", ABSENT_REASONS.get(name, "not recorded"))
        return [f"| `{name}` | 0 | n/a | n/a | n/a | — | — | {reason} |"]

    def share(key: str) -> str:
        # Only the duration stages get a share, and only against TTFT. The
        # cumulative milestones already contain each other, so a percentage
        # column spanning both is a column somebody will try to add up.
        if not budget:
            return "—"
        # And only when the stage covers at least the turns TTFT was measured on.
        #
        # `>=` rather than `==`, and the difference matters in both directions.
        # Most pre-model stages run on all 30 turns while only 24 produce a
        # visible token, so requiring equality would suppress every share in the
        # table -- including on the ordinary runs where the figures are sound. A
        # stage measured over a superset is an approximation, noted in the header.
        #
        # What this DOES reject is a stage recorded on fewer turns than TTFT,
        # which on a mixed run means a different population entirely. Measured on
        # the cache-hit run: 24 turns hit the cache and have a ~5 ms TTFT with no
        # model call, while 6 open the eligibility card, are never cached, and have
        # a ~909 ms concurrent wait and no TTFT at all. Dividing one population's
        # p50 by the other's produced a share of 15880.6% and a residual of
        # -874.1 ms.
        if entry.get("count", 0) < ttft.get("count", 0):
            return "n/a"
        total = ttft.get(key)
        value = entry.get(key)
        if not total or value is None:
            return "—"
        return f"{100.0 * value / total:.1f}%"

    return [
        f"| `{name}` | {entry['count']} | {entry['p50']:.1f} | {entry['p95']:.1f} "
        f"| {entry['p99']:.1f} | {share('p50')} | {share('p95')} | {note} |"
    ]


def render(summary: dict[str, Any], observed: list[dict[str, Any]], label: str) -> str:
    """The markdown table that lands in docs/latency-baseline.md."""
    stages = summary["stages"]
    ttft = stages.get(T_TTFT, {})

    lines: list[str] = []
    lines.append(f"### {label} run")
    lines.append("")
    lines.append(
        f"{summary['turns']} turns · cold-start turns: {summary['cold_starts']} · "
        f"cache hits: {summary['cache_hits']} · "
        f"turns with a visible token: {ttft.get('count', 0)}"
    )
    lines.append("")
    header = (
        "| stage | n | p50 (ms) | p95 (ms) | p99 (ms) | share of p50 TTFT "
        "| share of p95 TTFT | what it is |"
    )
    lines.append(header)
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    lines.append(
        "| *`n` is how many turns recorded the stage. A share is shown only when "
        "`n` covers TTFT's turns, and is an approximation when `n` is larger — "
        "which is why one can exceed 100%.* | | | | | | | |"
    )

    lines.append(
        "| **TTFT budget** (durations; these sum to t_ttft) | | | | | | | |"
    )
    for name in DURATION_STAGES:
        lines.extend(_row(name, stages.get(name, {}), ttft, budget=True))

    # Whether the budget actually adds up. A decomposition that silently loses a
    # second is worth catching here rather than in a review of the conclusions.
    #
    # Summed over the stages recorded on the SAME turns as TTFT, for the reason
    # `_row` explains: on a mixed run, adding a stage measured on 6 turns to one
    # measured on 24 produced a residual of -874.1 ms.
    comparable = [
        name
        for name in DURATION_STAGES
        if stages.get(name, {}).get("count", 0) >= ttft.get("count", 0) > 0
    ]
    if ttft.get("p50") and comparable:
        accounted = sum(stages[name]["p50"] for name in comparable)
        residual = ttft["p50"] - accounted
        skipped = [
            name
            for name in DURATION_STAGES
            if stages.get(name, {}).get("count") and name not in comparable
        ]
        note = "framework overhead not inside any measured span"
        if skipped:
            note += (
                f" — excludes {', '.join(f'`{s}`' for s in skipped)}, recorded on "
                "FEWER turns than t_ttft and so on a different population"
            )
        lines.append(
            f"| *unaccounted at p50* | {ttft.get('count', 0)} | {residual:.1f} | | | "
            f"{100.0 * residual / ttft['p50']:.1f}% | | {note} |"
        )
    elif ttft.get("p50"):
        # Nothing shares TTFT's population, so there is no budget to reconcile.
        # Saying so beats printing a residual of 100% and letting a reader
        # conclude the instrumentation lost the whole turn.
        lines.append(
            "| *no budget for this run* | | | | | — | — | every duration stage was "
            "recorded on a different set of turns than `t_ttft`, so the shares are "
            "not computable — see the `n` column |"
        )

    lines.append("| **Milestones** (cumulative from request received) | | | | | | | |")
    for name in MILESTONE_STAGES:
        lines.extend(_row(name, stages.get(name, {}), ttft, budget=False))

    lines.append("| **Auxiliary** | | | | | | | |")
    for name in AUXILIARY_STAGES:
        lines.extend(_row(name, stages.get(name, {}), ttft, budget=False))

    client_ttfts = sorted(
        turn["client_ttft_ms"] for turn in observed if turn["client_ttft_ms"] is not None
    )
    lines.append("")
    if client_ttfts:
        lines.append(
            f"Client-observed TTFT (cross-check, n={len(client_ttfts)}): "
            f"p50 {percentile(client_ttfts, 50):.1f} ms · "
            f"p95 {percentile(client_ttfts, 95):.1f} ms"
        )
    failures = [turn["id"] for turn in observed if turn["error"]]
    empty = [turn["id"] for turn in observed if turn["client_ttft_ms"] is None]
    if failures:
        lines.append("")
        lines.append(f"Errored turns: {', '.join(failures)}")
    if empty:
        lines.append("")
        lines.append(
            f"Turns that yielded no visible token ({len(empty)}): {', '.join(empty)} — "
            "these opened the eligibility card, whose turn is silenced by design "
            "(`SILENT_TOOLS` in app/streaming.py). They have a `t_total` but no "
            "`t_ttft`, and are excluded from every TTFT figure above."
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--label",
        default="warm",
        help="Name for this run in the output. Use 'cold' on a freshly started server.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--out", type=Path, default=None, help="Also write the rendered table here."
    )
    parser.add_argument(
        "--json-out", type=Path, default=None, help="Write the raw summary + per-turn rows here."
    )
    args = parser.parse_args()

    cases = load_cases()

    # How many turns the server had already recorded. Checked again at the end,
    # because `/debug/timings?last=30` happily returns the PREVIOUS run's thirty
    # turns when this run recorded none -- which is exactly what happened the
    # first time the rate limiter rejected a warm run, and it printed a
    # confident, entirely stale table.
    turns_before = fetch_summary(args.base_url, last=1_000_000)["turns"]

    print(
        f"Probing {len(cases)} turns against {args.base_url} "
        f"({args.label}); this spends model calls.",
        file=sys.stderr,
    )

    observed: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        try:
            result = ask(args.base_url, case, args.timeout)
        except Exception as exc:  # a probe that dies on turn 7 should still report 6
            result = {
                "id": case["id"],
                "lang": case["lang"],
                "persona": case["persona"],
                "client_ttft_ms": None,
                "client_total_ms": None,
                "characters": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        observed.append(result)
        print(
            f"  [{index:2d}/{len(cases)}] {result['id']:<6} {result['persona']:<7} "
            f"ttft={result['client_ttft_ms']} total={result['client_total_ms']} "
            f"chars={result['characters']}"
            + (f" ERROR {result['error']}" if result["error"] else ""),
            file=sys.stderr,
        )

    errored = [turn for turn in observed if turn["error"]]
    turns_after = fetch_summary(args.base_url, last=1_000_000)["turns"]
    recorded = turns_after - turns_before
    if recorded < len(cases):
        message = (
            f"Server recorded {recorded} of {len(cases)} turns "
            f"({len(errored)} client errors). Refusing to render: "
            "`--last` would report turns from an earlier run as if they were this one."
        )
        if any("429" in (turn["error"] or "") for turn in errored):
            message += (
                "\nAll-429: CHAT_MESSAGES_PER_WINDOW (default 30 per 600s) is the "
                "limit, and one probe run spends the whole window. Raise it on the "
                "measurement process -- the limiter is a dependency that runs before "
                "any timed work, so it cannot move a stage figure."
            )
        raise SystemExit(message)

    summary = fetch_summary(args.base_url, last=len(cases))

    # The label is checked against what the server actually saw. A run called
    # "cold" against an already-warm process is the easiest way to publish a
    # baseline that quietly means nothing.
    if args.label == "cold" and summary["cold_starts"] == 0:
        print(
            "WARNING: labelled 'cold' but the server reported no cold-start turn. "
            "Restart the server before a cold run.",
            file=sys.stderr,
        )
    if args.label == "warm" and summary["cold_starts"]:
        print(
            "WARNING: labelled 'warm' but a cold-start turn is in this window.",
            file=sys.stderr,
        )

    table = render(summary, observed, args.label)

    # Written BEFORE anything is printed. Thirty turns of model calls have already
    # been paid for by this point, and the first real run of this script threw
    # them away on a console encoding error raised by `print`.
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(table + "\n", encoding="utf-8")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps({"label": args.label, "summary": summary, "turns": observed}, indent=2),
            encoding="utf-8",
        )

    print()
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
