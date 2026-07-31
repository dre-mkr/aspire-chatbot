"""The sliding window itself, independent of any endpoint."""

import pytest

from app.voice.config import VoiceSettings
from app.voice.limiter import SlidingWindowLimiter


@pytest.fixture
def limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        VoiceSettings(
            _env_file=None,
            rate_window_seconds=600.0,
            max_transcriptions_per_window=2,
            max_speech_per_window=3,
        )
    )


def test_allows_up_to_the_limit_then_refuses(limiter):
    assert limiter.check_transcription("s1").allowed
    assert limiter.check_transcription("s1").allowed

    decision = limiter.check_transcription("s1")
    assert not decision.allowed
    assert decision.retry_after_seconds > 0


def test_sessions_are_independent(limiter):
    limiter.check_transcription("s1")
    limiter.check_transcription("s1")
    assert not limiter.check_transcription("s1").allowed
    assert limiter.check_transcription("s2").allowed


def test_buckets_are_independent(limiter):
    """Exhausting transcription must not consume the speech allowance."""
    limiter.check_transcription("s1")
    limiter.check_transcription("s1")
    assert not limiter.check_transcription("s1").allowed
    assert limiter.check_speech("s1").allowed


def test_retry_after_is_bounded_by_the_window(limiter):
    limiter.check_speech("s1")
    limiter.check_speech("s1")
    limiter.check_speech("s1")
    decision = limiter.check_speech("s1")
    assert 0 < decision.retry_after_seconds <= 601
