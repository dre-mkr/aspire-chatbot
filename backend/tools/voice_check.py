"""Prove the guide voices work. Run it AFTER setting ELEVENLABS_API_KEY.

    BASE=https://aspire.eccugenai.app python3 tools/voice_check.py

"Almost certainly the key" is not a completed action. This asks the running
server the six questions that decide whether an audience will hear Skye and
Zion or the operating system's robot: is the module on, does the server admit
it has a native voice, do the four persona/language pairs on the demo path
actually return audio, and does the fallback still catch a failure if the
provider goes down mid-showcase.

It buys nothing on credit: four short lines, cached by the server afterwards.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:8010").rstrip("/")
HEADERS = {"content-type": "application/json", "user-agent": "aspire-voice-check/1.0"}

#: The pairs a showcase actually plays: the youngest guide, and the teenager
#: in all three languages.
CASES: tuple[tuple[str, str, str], ...] = (
    ("stella", "en", "Saving means keeping some money for later."),
    ("orion", "en", "Saving is keeping part of what you earn."),
    ("orion", "es", "Ahorrar es guardar parte de tu dinero para después."),
    ("orion", "fr", "Économiser, c'est garder une partie de ton argent."),
)


def _get(path: str):
    request = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def _post(path: str, body: dict, token: str | None = None):
    headers = dict(HEADERS)
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), response.headers.get("content-type", "")


def main() -> int:
    failures: list[str] = []

    print(f"Asking {BASE} whether it can speak.\n")

    # ── 1. the module, and whether it admits to having a voice ──
    try:
        config = _get("/api/voice/config")
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        print(f"  FAIL  /api/voice/config did not answer: {exc}")
        return 1

    enabled = bool(config.get("enabled"))
    native = config.get("native_voice")
    personas = [entry["persona"] for entry in config.get("personas", [])]

    print(f"  {'ok  ' if enabled else 'FAIL'}  voice module enabled: {enabled}")
    if not enabled:
        failures.append("VOICE_ENABLED is not true on the server.")

    if native is None:
        print("  note  this server predates `native_voice`; deploy first.")
    else:
        print(f"  {'ok  ' if native else 'FAIL'}  server has a native voice key: {native}")
        if not native:
            failures.append(
                "ELEVENLABS_API_KEY is not set: every guide voice will fall back "
                "to the browser's own."
            )

    print(f"  ok    guides configured: {', '.join(personas) or 'none'}")
    print(f"  note  realtime voice: {config.get('realtime_enabled')} "
          "(unbuilt stretch goal; 501 either way)\n")

    # ── 2. the pairs a showcase plays ──
    token = json.loads(
        _post(
            "/v2/session",
            {
                "session_id": f"voicecheck-{int(time.time())}",
                "persona": "orion",
                "age_band": "16-18",
            },
        )[0]
    )["token"]

    for persona, language, text in CASES:
        label = f"{persona}/{language}"
        try:
            audio, content_type = _post(
                "/api/voice/speak",
                {"text": text, "persona": persona, "language": language},
                token,
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:120]
            print(f"  FAIL  {label:12} HTTP {exc.code} {detail}")
            failures.append(f"{label} cannot speak.")
            continue

        # An MP3 starts with an ID3 tag or a frame sync. Anything else is not audio.
        looks_like_audio = audio[:3] == b"ID3" or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
        if looks_like_audio and "audio" in content_type:
            print(f"  ok    {label:12} {len(audio):,} bytes of {content_type}")
        else:
            print(f"  FAIL  {label:12} answered {content_type} that is not audio")
            failures.append(f"{label} returned something that is not audio.")
        time.sleep(2)

    # ── 3. the fallback, which must survive the provider going down ──
    print()
    print("  note  the browser fallback cannot be proved from here: it lives in "
          "the client.\n        Check it by hand -- with the key REMOVED the Play "
          "button must still\n        speak in the device voice, and the mic must "
          "disappear rather than error.")

    print()
    if failures:
        print(f"{len(failures)} problem(s):")
        for problem in failures:
            print(f"  - {problem}")
        return 1
    print("Every guide voice on the demo path returned real audio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
