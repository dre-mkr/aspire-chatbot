"""Does this ASPIRE server actually speak? Every guide, every language.

    python3 tools/voice_check.py
    BASE=https://aspire.eccugenai.app python3 tools/voice_check.py
    python3 tools/voice_check.py --quick          # the four a showcase plays
    python3 tools/voice_check.py --persona orion  # one guide
    python3 tools/voice_check.py --language fr    # one language
    python3 tools/voice_check.py --json           # for CI

Run it before a demo and after a deploy. It is the difference between "the
config lists six guides" and "six guides made a sound", and those came apart on
production: `enabled` was true, `ELEVENLABS_API_KEY` was not set, every request
fell back to the browser's own voice, and nothing said so.

WHAT THE THREE FAILURES MEAN, because they need different people to fix them:

    unavailable   The server could not reach a voice at all: no API key, the
                  upstream is down, or the circuit breaker is open after
                  repeated failures. If EVERY cell says this, it is the key.

    uncast        This guide has no native voice in this language. The client's
                  rule is that an English-trained voice never speaks Spanish or
                  French to a reader, so the server refuses rather than fake it.
                  Fixed by casting one: VOICE_{PERSONA}_{ES|FR}, and a restart.
                  A column of these is a casting gap, not an outage.

    limited       The voice rate limiter, not a fault. Wait out the window.

Costs: one short line per pair, and the server caches them, so a second run in
the same window is nearly free. It never writes anything and never uploads audio.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("BASE", "http://127.0.0.1:8010").rstrip("/")
HEADERS = {"content-type": "application/json", "user-agent": "aspire-voice-check/2.0"}

#: One short, ordinary line per language. Short on purpose: this is a liveness
#: check, not a listening test, and a long line spends the caller's budget.
LINES: dict[str, str] = {
    "en": "Saving means keeping some of your money for later.",
    "es": "Ahorrar es guardar parte de tu dinero para después.",
    "fr": "Économiser, c'est garder une partie de ton argent.",
}

#: The pairs a showcase actually plays, for `--quick`.
SHOWCASE: tuple[tuple[str, str], ...] = (
    ("stella", "en"),
    ("orion", "en"),
    ("orion", "es"),
    ("orion", "fr"),
)

#: An MP3 begins with an ID3 tag or a frame sync. Anything else is not audio.
MP3_MAGIC: tuple[bytes, ...] = (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa")

OK, UNCAST, UNAVAILABLE, LIMITED, ERROR, SKIP = (
    "ok", "uncast", "unavailable", "limited", "error", "-"
)

MARK: dict[str, str] = {
    OK: "ok", UNCAST: "UNCAST", UNAVAILABLE: "FAIL", LIMITED: "wait", ERROR: "ERR", SKIP: "-",
}


def _get(path: str) -> Any:
    request = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def _post(path: str, body: dict, token: str | None = None) -> tuple[bytes, dict]:
    headers = dict(HEADERS)
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), dict(response.headers)


def _mint_token() -> str:
    body, _ = _post(
        "/v2/session",
        {
            "session_id": f"voicecheck-{int(time.time())}",
            "persona": "orion",
            "age_band": "16-18",
        },
    )
    return json.loads(body)["token"]


def probe(persona: str, language: str, token: str) -> dict[str, Any]:
    """One pair, and what came back."""
    started = time.perf_counter()
    try:
        audio, headers = _post(
            "/api/voice/speak",
            {"text": LINES[language], "persona": persona, "language": language},
            token,
        )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()[:200]
        if exc.code == 429:
            status = LIMITED
        elif "voice_uncast" in raw:
            status = UNCAST
        elif "voice_unavailable" in raw:
            status = UNAVAILABLE
        else:
            status = ERROR
        return {"persona": persona, "language": language, "status": status,
                "http": exc.code, "detail": raw, "ms": 0, "bytes": 0}
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        return {"persona": persona, "language": language, "status": ERROR,
                "http": 0, "detail": str(exc)[:200], "ms": 0, "bytes": 0}

    ms = int((time.perf_counter() - started) * 1000)
    is_audio = audio.startswith(MP3_MAGIC) and "audio" in headers.get("Content-Type", "")
    return {
        "persona": persona,
        "language": language,
        "status": OK if is_audio else ERROR,
        "http": 200,
        "detail": "" if is_audio else f"not audio: {headers.get('Content-Type')}",
        "ms": ms,
        "bytes": len(audio),
        "cache": headers.get("X-Voice-Cache", ""),
    }


def _matrix(results: list[dict], personas: list[str], languages: list[str]) -> str:
    """The whole answer on one screen."""
    width = max((len(p) for p in personas), default=6) + 2
    by_pair = {(r["persona"], r["language"]): r for r in results}
    head = "guide".ljust(width) + "".join(lang.upper().center(9) for lang in languages)
    rows = [head, "-" * len(head)]
    for persona in personas:
        cells = []
        for language in languages:
            result = by_pair.get((persona, language))
            cells.append(MARK[result["status"] if result else SKIP].center(9))
        rows.append(persona.ljust(width) + "".join(cells))
    return "\n".join(rows)


def _casting_advice(results: list[dict]) -> list[str]:
    """The variables to set, named the way this server actually reads them.

    A persona's BASE id covers every language: `VOICE_KALEB=<id>`. A suffix is
    an override for one language: `VOICE_KALEB_ES=<id>`. So a guide uncast in
    all three needs the base, and a guide uncast in one needs the override --
    telling someone to set `VOICE_KALEB_EN` would have them set a variable this
    server reads for nothing.
    """
    uncast: dict[str, set[str]] = {}
    probed: dict[str, set[str]] = {}
    for result in results:
        probed.setdefault(result["persona"], set()).add(result["language"])
        if result["status"] == UNCAST:
            uncast.setdefault(result["persona"], set()).add(result["language"])

    advice: list[str] = []
    for persona in sorted(uncast):
        if uncast[persona] == probed.get(persona, set()) and len(uncast[persona]) > 1:
            advice.append(f"VOICE_{persona.upper()}=<elevenlabs_voice_id>   # covers all three")
        else:
            for language in sorted(uncast[persona]):
                if language == "en":
                    advice.append(
                        f"VOICE_{persona.upper()}=<elevenlabs_voice_id>   "
                        "# the base id, which English uses"
                    )
                else:
                    advice.append(
                        f"VOICE_{persona.upper()}_{language.upper()}=<elevenlabs_voice_id>"
                    )
    advice.append("...then restart the service and run this again.")
    return advice


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="voice_check",
        description="Prove an ASPIRE server can speak, guide by guide and language by language.",
    )
    parser.add_argument("--quick", action="store_true",
                        help="only the four pairs a showcase plays")
    parser.add_argument("--persona", action="append", default=[],
                        help="limit to a guide (repeatable)")
    parser.add_argument("--language", action="append", default=[],
                        choices=sorted(LINES), help="limit to a language (repeatable)")
    parser.add_argument("--pace", type=float, default=1.5,
                        help="seconds between probes (default 1.5)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    quiet = args.json
    if not quiet:
        print(f"Asking {BASE} whether it can speak.\n")

    # ── what the server says about itself ──
    try:
        config = _get("/api/voice/config")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  /api/voice/config did not answer: {exc}", file=sys.stderr)
        return 2

    enabled = bool(config.get("enabled"))
    native = config.get("native_voice")
    advertised = {
        entry["persona"]: [lang for lang in entry.get("languages", [])]
        for entry in config.get("personas", [])
    }

    # ── the pairs to probe ──
    personas = [p for p in advertised if not args.persona or p in args.persona]
    languages = [lang for lang in sorted(LINES) if not args.language or lang in args.language]
    pairs = [
        (persona, language)
        for persona in personas
        for language in languages
        if language in advertised.get(persona, [])
    ]
    if args.quick:
        pairs = [pair for pair in SHOWCASE if pair in pairs]

    if not quiet:
        print(f"  {'ok  ' if enabled else 'FAIL'}  voice module enabled: {enabled}")
        if native is None:
            print("  note  this server predates `native_voice` -- deploy to see it")
        else:
            print(f"  {'ok  ' if native else 'FAIL'}  ElevenLabs key present: {native}")
        print(f"  ok    guides advertised: {', '.join(personas) or 'none'}")
        print(f"  note  realtime voice: {config.get('realtime_enabled')} "
              "(unbuilt; /realtime-token is 501 either way)")
        print(f"\nProbing {len(pairs)} pair(s), {args.pace}s apart.\n")

    if not pairs:
        print("Nothing to probe: the config advertises no matching pair.", file=sys.stderr)
        return 2

    token = _mint_token()
    results: list[dict[str, Any]] = []
    for index, (persona, language) in enumerate(pairs):
        result = probe(persona, language, token)
        # One retry for the limiter, which is a wait rather than a fault.
        if result["status"] == LIMITED:
            wait = 65
            if not quiet:
                print(f"  wait  {persona}/{language}: rate limited, retrying in {wait}s")
            time.sleep(wait)
            result = probe(persona, language, token)
        results.append(result)
        if not quiet:
            label = f"{persona}/{language}"
            if result["status"] == OK:
                cached = " (cached)" if result.get("cache") == "hit" else ""
                print(f"  ok    {label:14} {result['bytes']:>7,} bytes  {result['ms']:>5}ms{cached}")
            else:
                print(f"  {MARK[result['status']]:5} {label:14} {result['detail'][:70]}")
        if index < len(pairs) - 1:
            time.sleep(args.pace)

    counts = {status: sum(1 for r in results if r["status"] == status) for status in
              (OK, UNCAST, UNAVAILABLE, LIMITED, ERROR)}
    healthy = counts[OK] == len(results)

    if args.json:
        print(json.dumps({
            "base": BASE, "enabled": enabled, "native_voice": native,
            "realtime_enabled": config.get("realtime_enabled"),
            "results": results, "counts": counts, "healthy": healthy,
        }, indent=1))
        return 0 if healthy else 1

    print("\n" + _matrix(results, personas, languages) + "\n")

    if healthy:
        print(f"All {len(results)} pairs returned real audio. This server can speak.")
        return 0

    print(f"{counts[OK]} of {len(results)} pairs speak.")
    if counts[UNAVAILABLE] == len(results):
        print("  Every pair is unavailable, which is the signature of a missing key.")
        print("  Set ELEVENLABS_API_KEY on the server and restart, then run this again.")
    elif counts[UNAVAILABLE]:
        print(f"  {counts[UNAVAILABLE]} unavailable: no key, upstream down, or breaker open.")
    if counts[UNCAST]:
        print(f"  {counts[UNCAST]} uncast -- a casting gap, not an outage.")
        for variable in _casting_advice(results):
            print(f"      {variable}")
    if counts[LIMITED]:
        print(f"  {counts[LIMITED]} still rate limited: wait out the window and re-run.")
    if counts[ERROR]:
        print(f"  {counts[ERROR]} unexpected: see the lines above.")
    print("\n  The browser fallback lives in the client and cannot be proved from here.")
    print("  Check by hand: with no key, Play must still speak in the device voice")
    print("  and the microphone must disappear rather than error.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
