"""Fire 30 representative questions at `/chat/stream` and report where the time went."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
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

# The console here is cp1252 by default, and box-drawing characters would kill the report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - not a real tty
        pass

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "golden.yaml"

#: Ten per language, and within a language the personas are filled round-robin in this order.
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
        # Round-robin until the quota is met.
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


def graph_session(
    base_url: str,
    *,
    thread_id: str | None = None,
    token: str | None = None,
    timeout: float = 20.0,
) -> tuple[str, str]:
    """Mint a graph session token."""
    body = {"session_id": thread_id or str(uuid.uuid4())}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v2/session",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        minted = json.loads(response.read())
    return minted["token"], minted["session_id"]


def ask(base_url: str, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One turn."""
    # A fresh session per case, so every probe turn is an opening turn.
    token, _ = graph_session(base_url, timeout=timeout)

    payload = json.dumps({"message": case["q"]}).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v2/chat/stream",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    characters = 0
    error: str | None = None

    # The v2 wire, not AG-UI: `event:` names the kind and `data:` is the body.
    kind = ""
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("event:"):
                kind = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if kind == "token":
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                characters += len(event.get("t", ""))
            elif kind == "error":
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
        # Only the duration stages get a share, and only against TTFT.
        if not budget:
            return "—"
        # And only when the stage covers at least the turns TTFT was measured on.
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

    # Whether the budget actually adds up.
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

    # How many turns the server had already recorded.
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

    # The label is checked against what the server actually saw.
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

    # Written BEFORE anything is printed.
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
