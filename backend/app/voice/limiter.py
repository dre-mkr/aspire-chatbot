"""Per-session sliding-window rate limiting.

IMPORTANT: this is abuse dampening, not a security boundary. The chat endpoint
has no authentication, so the only session identifier available is the client's
own thread_id, which anyone can regenerate. It exists to stop a stuck retry loop
or a demo laptop from draining the ElevenLabs account, not to stop an attacker.
A real per-user limit needs real auth.

In-memory and therefore per-process: with several uvicorn workers each holds its
own window, so the effective limit is the configured number times the worker
count.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.voice.config import VoiceSettings, get_voice_settings


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int


class SlidingWindowLimiter:
    def __init__(self, settings: VoiceSettings | None = None) -> None:
        self._settings = settings or get_voice_settings()
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, session: str, limit: int) -> RateDecision:
        window = self._settings.rate_window_seconds
        now = time.monotonic()
        key = (bucket, session)

        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()

            if len(hits) >= limit:
                # Room frees up when the oldest hit falls out of the window.
                retry_after = max(1, int(window - (now - hits[0])) + 1)
                return RateDecision(False, retry_after)

            hits.append(now)
            return RateDecision(True, 0)

    def check_transcription(self, session: str) -> RateDecision:
        return self.check("stt", session, self._settings.max_transcriptions_per_window)

    def check_speech(self, session: str) -> RateDecision:
        return self.check("tts", session, self._settings.max_speech_per_window)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter: SlidingWindowLimiter | None = None


def get_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter()
    return _limiter
