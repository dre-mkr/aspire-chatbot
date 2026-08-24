#!/usr/bin/env python3
"""Hear every persona, in every language, against a running ASPIRE.

    python3 tools/hear_voices.py                      # status only, no audio
    python3 tools/hear_voices.py --play               # save mp3s
    python3 tools/hear_voices.py --play --persona nova --locale fr
    python3 tools/hear_voices.py --play --line "Saving is keeping money"

Why this and not a TypeScript script: `speakStream` is browser code. It uses
`MediaSource` and `URL.createObjectURL`, neither of which exists under node, and
`authHeaders()` reads a token out of browser storage. A dev script has to talk
to the endpoint directly, which is all this does.

Voice ids are NOT set here. They live on the server (`VOICE_STELLA`,
`VOICE_KALEB`, ...) and the registry resolves a language-specific voice before
falling back to the persona's own. Putting them in a client would publish them
in the bundle and give the same value two owners.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.error
import urllib.request

BASE = "https://aspire.eccugenai.app"

#: Cloudflare answers urllib's default agent with 403 error 1010, so say who we
#: are. Nothing here depends on being mistaken for a browser; it just has to be
#: a request the edge will pass through.
HEADERS = {"user-agent": "aspire-dev-tools/1.0 (voice check)"}
PERSONAS = {
    "stella": "5-8", "kaleb": "9-12", "orion": "13-15",
    "aurora": "adult", "nova": "adult", "guest": "adult",
}
LINES = {
    "en": "Saving is keeping money for later instead of spending it now.",
    "es": "Ahorrar es guardar dinero para después en vez de gastarlo ahora.",
    "fr": "Épargner, c'est garder de l'argent pour plus tard au lieu de le dépenser.",
}


def _post(path: str, body: dict, token: str | None = None, raw: bool = False):
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", **HEADERS,
                 **({"authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read()
            return response.status, (payload if raw else json.loads(payload))
    except urllib.error.HTTPError as failed:
        detail = failed.read()
        try:
            return failed.code, json.loads(detail)
        except Exception:
            return failed.code, detail[:200]


def session(persona: str, band: str, locale: str) -> str | None:
    status, body = _post("/v2/session", {
        "session_id": f"t-{int(time.time())}-{persona[:4]}{int(time.time()*1000)%10000}",
        "persona": persona, "age_band": band, "locale": locale,
    })
    return body.get("token") if status == 200 and isinstance(body, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona", choices=[*PERSONAS, "all"], default="all")
    parser.add_argument("--locale", choices=["en", "es", "fr", "all"], default="en")
    parser.add_argument("--play", action="store_true", help="save the audio")
    parser.add_argument("--line", default=None, help="say this instead")
    parser.add_argument("--out", default="/tmp/aspire-voice-tests")
    args = parser.parse_args()

    request = urllib.request.Request(f"{BASE}/api/voice/config", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        config = json.loads(response.read())
    tuning = {p["persona"]: p for p in config.get("personas", [])}
    print(f"voice enabled: {config.get('enabled')}   realtime: {config.get('realtime_enabled')}\n")

    chosen = list(PERSONAS) if args.persona == "all" else [args.persona]
    locales = ["en", "es", "fr"] if args.locale == "all" else [args.locale]
    out = pathlib.Path(args.out)
    if args.play:
        out.mkdir(parents=True, exist_ok=True)
        print(f"audio -> {out}\n")

    failures = 0
    for persona in chosen:
        for locale in locales:
            said = args.line or LINES[locale]
            token = session(persona, PERSONAS[persona], locale)
            if token is None:
                print(f"  {persona:7} {locale}  SESSION FAILED")
                failures += 1
                continue
            status, body = _post("/api/voice/speak-stream", {
                "text": said, "language": locale, "persona": persona, "format": "mp3",
            }, token=token, raw=True)

            speed = tuning.get(persona, {}).get("speed", "?")
            if status == 200 and isinstance(body, (bytes, bytearray)):
                note = f"{len(body) / 1024:.0f} KB"
                if args.play:
                    path = out / f"{persona}-{locale}.mp3"
                    path.write_bytes(body)
                    note += f"  -> {path.name}"
                print(f"  {persona:7} {locale}  200  speed={speed}  {note}")
            else:
                detail = body.get("detail") if isinstance(body, dict) else body
                print(f"  {persona:7} {locale}  {status}  {detail}")
                failures += 1

    print(f"\n{'all voices answered' if not failures else f'{failures} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
