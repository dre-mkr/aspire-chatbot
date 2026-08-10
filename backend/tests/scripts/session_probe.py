"""Latency probe for the population `latency_probe.py` deliberately excludes."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

#: Continuing turns, so every one of them reads a real window.
QUESTIONS = [
    "And what about withdrawals?",
    "How much can I put in each month?",
    "What happens when I turn 18?",
    "Can my parents see the balance?",
    "Is there any interest on it?",
    "What if I miss a month?",
    "Can I take some out for school?",
    "Who decides the rules for it?",
    "What paperwork does it need?",
    "Does it cost anything to keep open?",
]


def _post(url: str, payload: dict, *, token: str | None = None, timeout: float = 60.0):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def mint_session(base_url: str) -> str:
    """A real anonymous identity, so `owner_id_for` has a row to go and find."""
    body = _post(
        f"{base_url}/api/auth/anonymous",
        {"device_id": f"probe-{uuid.uuid4().hex[:12]}"},
    )
    token = body.get("token")
    if not token:
        raise SystemExit(f"no token in the session response: {body}")
    return token


def graph_session(
    base_url: str, *, thread_id: str, token: str, timeout: float = 20.0
) -> str:
    """Exchange an ACCOUNT token for a GRAPH session token."""
    request = urllib.request.Request(
        f"{base_url}/v2/session",
        data=json.dumps({"session_id": thread_id}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())["token"]


def ask(
    base_url: str, question: str, *, thread_id: str | None, token: str, timeout: float
) -> dict[str, Any]:
    """One streamed turn, timed from the client as well as the server."""
    thread_id = thread_id or str(uuid.uuid4())
    session_token = graph_session(
        base_url, thread_id=thread_id, token=token, timeout=timeout
    )

    payload = json.dumps({"message": question}).encode()
    request = urllib.request.Request(
        f"{base_url}/v2/chat/stream",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {session_token}",
        },
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    returned_thread: str | None = None
    error: str | None = None

    # The v2 wire: `event:` names the kind, `data:` carries the body, and the two are separate lines -- so the name…
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
            if kind == "token" and first_token_at is None:
                first_token_at = time.perf_counter()
            elif kind == "done":
                returned_thread = (event.get("usage") or {}).get("thread_id")
            elif kind == "error":
                error = event.get("message", "unknown")

    return {
        # The turn echoes the id it ran on.
        "thread_id": returned_thread or thread_id,
        "client_ttft_ms": None
        if first_token_at is None
        else round((first_token_at - started) * 1000.0, 3),
        "error": error,
    }


def fetch_summary(base_url: str, last: int) -> dict[str, Any]:
    url = f"{base_url}/debug/timings?last={last}"
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


#: What this probe exists to report.
REPORTED = (
    "t_session_wait",
    "t_identity",
    "t_history",
    "t_concurrent_wait",
    "t_prompt_build",
    "d_model_call",
    "t_ttft",
    "t_total",
)


def render(summary: dict[str, Any], observed: list[dict], label: str) -> str:
    stages = summary["stages"]
    lines = [
        f"### {label} — authenticated, continuing turns",
        "",
        f"{summary['turns']} turns · every turn on a thread with a past, "
        f"every turn with a real session token",
        "",
        "| stage | n | p50 (ms) | p95 (ms) | p99 (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in REPORTED:
        entry = stages.get(name, {})
        if not entry.get("count"):
            lines.append(f"| `{name}` | 0 | n/a | n/a | n/a |")
            continue
        lines.append(
            f"| `{name}` | {entry['count']} | {entry['p50']:.1f} | "
            f"{entry['p95']:.1f} | {entry['p99']:.1f} |"
        )

    # The sum that the gather is supposed to replace.
    identity = stages.get("t_identity", {})
    history = stages.get("t_history", {})
    if identity.get("count") and history.get("count"):
        lines.append("")
        lines.append(
            f"`t_identity + t_history` (what the pair cost in sequence): "
            f"p50 {identity['p50'] + history['p50']:.1f} ms · "
            f"p95 {identity['p95'] + history['p95']:.1f} ms"
        )

    client = [row["client_ttft_ms"] for row in observed if row["client_ttft_ms"]]
    if client:
        client.sort()
        p50 = client[len(client) // 2]
        p95 = client[min(len(client) - 1, int(len(client) * 0.95))]
        lines.append("")
        lines.append(
            f"Client-observed TTFT (cross-check, n={len(client)}): "
            f"p50 {p50:.1f} ms · p95 {p95:.1f} ms"
        )

    errors = [row for row in observed if row["error"]]
    if errors:
        lines.append("")
        lines.append(f"**{len(errors)} turn(s) errored.** {errors[0]['error']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--label", required=True)
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = mint_session(base_url)

    # One opening turn to bring a conversation into existence.
    seed = ask(
        base_url,
        "What is ASPIRE?",
        thread_id=None,
        token=token,
        timeout=args.timeout,
    )
    thread_id = seed["thread_id"]
    if not thread_id:
        raise SystemExit(f"the seed turn returned no thread id: {seed}")

    observed: list[dict] = []
    for index in range(args.turns):
        question = QUESTIONS[index % len(QUESTIONS)]
        # Suffixed so a repeat of the list is never the identical string twice on one thread, which the model would ans…
        if index >= len(QUESTIONS):
            question = f"{question} (following up again, {index})"
        row = ask(
            base_url,
            question,
            thread_id=thread_id,
            token=token,
            timeout=args.timeout,
        )
        observed.append(row)
        print(f"  {index + 1}/{args.turns} ttft={row['client_ttft_ms']}", flush=True)

    summary = fetch_summary(base_url, args.turns)
    table = render(summary, observed, args.label)
    print()
    print(table)

    if args.out:
        args.out.write_text(table + "\n", encoding="utf-8")
    if args.json_out:
        args.json_out.write_text(
            json.dumps({"summary": summary, "turns": observed}, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
