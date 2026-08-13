"""Per-session sliding-window rate limiting, with the voice settings applied."""

from __future__ import annotations

from app.limits import RateDecision, SlidingWindowLimiter as _Window
from app.voice.config import VoiceSettings, get_voice_settings

__all__ = ["RateDecision", "SlidingWindowLimiter", "get_limiter"]


class SlidingWindowLimiter:
    """The shared limiter, with the window and the caps read from voice settings."""

    def __init__(self, settings: VoiceSettings | None = None) -> None:
        self._settings = settings or get_voice_settings()
        # Its own window, so voice throttling never shares buckets with the chat limiter.
        self._window = _Window()

    def check(self, bucket: str, session: str, limit: int) -> RateDecision:
        return self._window.check(
            bucket,
            session,
            limit=limit,
            window=self._settings.rate_window_seconds,
        )

    def check_transcription(self, session: str) -> RateDecision:
        return self.check("stt", session, self._settings.max_transcriptions_per_window)

    def check_speech(self, session: str) -> RateDecision:
        return self.check("tts", session, self._settings.max_speech_per_window)

    def reset(self) -> None:
        self._window.reset()


_limiter: SlidingWindowLimiter | None = None


def get_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter()
    return _limiter
