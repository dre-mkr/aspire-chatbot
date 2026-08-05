"""First-audio-byte: the buffered path against the streaming path (P14-C).

`/voice/speak` joins the whole MP3 server-side before the first byte crosses
the wire; `/voice/speak-stream` passes each vendor chunk through as it exists.
This fires the same texts at both and reports client-observed first byte and
total, per language -- which is also the live verification that the flash tier
actually serves EN, ES and FR.

    python -m scripts.voice_probe --base-url http://127.0.0.1:8014

Texts are distinct per (endpoint, language, run) -- a repeat would hit the
voice cache and measure Valkey rather than ElevenLabs. Runs alternate between
endpoints rather than batching, so vendor drift lands on both sides evenly.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import string
import time
import urllib.request

TEXTS = {
    "en": "Saving a little every month adds up faster than you might think. "
    "Your ASPIRE account keeps it safe while it grows, and you can watch "
    "the balance climb with every deposit you make.",
    "es": "Ahorrar un poco cada mes suma más rápido de lo que piensas. Tu "
    "cuenta ASPIRE lo mantiene seguro mientras crece, y puedes ver cómo "
    "sube el saldo con cada depósito que haces.",
    "fr": "Économiser un peu chaque mois s'additionne plus vite que tu ne le "
    "penses. Ton compte ASPIRE le garde en sécurité pendant qu'il grandit, "
    "et tu peux voir le solde monter à chaque dépôt.",
}


def one(base_url: str, endpoint: str, language: str, text: str, timeout: float) -> dict:
    payload = json.dumps(
        {"text": text, "persona": "nova", "language": language, "format": "mp3"}
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/api/voice/{endpoint}",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    first_at = None
    total_bytes = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            if first_at is None:
                first_at = time.perf_counter()
            total_bytes += len(chunk)
    finished = time.perf_counter()
    return {
        "endpoint": endpoint,
        "language": language,
        "first_byte_ms": round((first_at - started) * 1000.0, 1) if first_at else None,
        "total_ms": round((finished - started) * 1000.0, 1),
        "bytes": total_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8014")
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    rows: list[dict] = []
    for run in range(args.runs):
        for language, text in TEXTS.items():
            for endpoint in ("speak", "speak-stream"):
                # Unique tail per (endpoint, run): each request misses the
                # voice cache and pays the vendor, which is the thing measured.
                # LETTERS ONLY -- a digit in the salt trips `has_many_numbers`
                # and silently reroutes the request to the quality tier, which
                # is exactly what the first run of this probe measured without
                # meaning to (every row came back model=eleven_multilingual_v2).
                salt = "".join(random.choices(string.ascii_lowercase, k=6))
                salted = f"{text} Nota {salt}."
                try:
                    row = one(base, endpoint, language, salted, args.timeout)
                except Exception as error:  # noqa: BLE001 - report, keep going
                    row = {
                        "endpoint": endpoint,
                        "language": language,
                        "error": f"{type(error).__name__}: {error}",
                    }
                rows.append(row)
                print(row, flush=True)

    print("\n| endpoint | language | n | first byte p50 (ms) | first byte max | total p50 (ms) |")
    print("|---|---|---:|---:|---:|---:|")
    for endpoint in ("speak", "speak-stream"):
        for language in TEXTS:
            sample = [
                r for r in rows
                if r.get("endpoint") == endpoint
                and r.get("language") == language
                and r.get("first_byte_ms")
            ]
            if not sample:
                print(f"| {endpoint} | {language} | 0 | — | — | — |")
                continue
            fb = sorted(r["first_byte_ms"] for r in sample)
            tt = sorted(r["total_ms"] for r in sample)
            print(
                f"| {endpoint} | {language} | {len(sample)} "
                f"| {statistics.median(fb):.0f} | {fb[-1]:.0f} "
                f"| {statistics.median(tt):.0f} |"
            )


if __name__ == "__main__":
    main()
