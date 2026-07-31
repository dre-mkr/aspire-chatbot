"""Endpoint tests against a mocked ElevenLabs client.

No test in this file touches the network or the real API.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.voice.cache as cache_module
import app.voice.client as client_module
import app.voice.limiter as limiter_module
import app.voice.registry as registry_module
import app.voice.router as router_module
from app.voice.client import VoiceClient
from app.voice.config import VoiceSettings
from app.voice.limiter import SlidingWindowLimiter
from app.voice.router import router

WEBM = "audio/webm"


class FakeSTTResponse:
    def __init__(self):
        self.text = "How do I join ASPIRE?"
        self.language_code = "en"
        self.language_probability = 0.98
        self.duration = 3.2


class FakeSDK:
    """Stands in for elevenlabs.client.ElevenLabs."""

    def __init__(self, *, stt_error=None, tts_error=None, audio=b"ID3-fake-mp3"):
        self.stt_error = stt_error
        self.tts_error = tts_error
        self.audio = audio
        self.stt_calls: list[dict] = []
        self.tts_calls: list[dict] = []
        outer = self

        class SpeechToText:
            def convert(self, **kwargs):
                outer.stt_calls.append(kwargs)
                if outer.stt_error:
                    raise outer.stt_error
                return FakeSTTResponse()

        class TextToSpeech:
            def convert(self, **kwargs):
                outer.tts_calls.append(kwargs)
                if outer.tts_error:
                    raise outer.tts_error
                return iter([outer.audio])

        self.speech_to_text = SpeechToText()
        self.text_to_speech = TextToSpeech()


@pytest.fixture
def settings(tmp_path) -> VoiceSettings:
    return VoiceSettings(
        _env_file=None,
        # The fixture mounts the router, so this app is in the enabled state.
        # The default is False; see config.py for why.
        voice_enabled=True,
        elevenlabs_api_key="test-key",
        voice_stella="v-stella",
        voice_orion="v-orion",
        voice_aurora="v-aurora",
        voice_nova="v-nova",
        voice_cache_dir=tmp_path / "voice_cache",
        max_transcriptions_per_window=3,
        # Deliberately above breaker_failure_threshold (3) so the breaker test
        # exercises the breaker rather than tripping the rate limit first.
        max_speech_per_window=10,
    )


@pytest.fixture
def sdk() -> FakeSDK:
    return FakeSDK()


@pytest.fixture
def client(settings, sdk, monkeypatch) -> TestClient:
    """A minimal app carrying only the voice router, wired to the fake SDK."""
    monkeypatch.setattr(router_module, "get_voice_settings", lambda: settings)
    monkeypatch.setattr(cache_module, "get_voice_settings", lambda: settings)
    monkeypatch.setattr(registry_module, "get_voice_settings", lambda: settings)

    registry_module.get_registry.cache_clear()
    monkeypatch.setattr(
        registry_module, "get_registry", lambda: registry_module.build_registry(settings)
    )
    monkeypatch.setattr(router_module, "resolve_profile", registry_module.resolve_profile)

    cache_module._cache = None
    limiter_module._limiter = SlidingWindowLimiter(settings)
    monkeypatch.setattr(router_module, "get_limiter", lambda: limiter_module._limiter)

    client_module.set_client(VoiceClient(settings=settings, client=sdk))

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)

    client_module.set_client(None)
    cache_module._cache = None
    limiter_module._limiter = None


def upload(audio=b"fake-audio-bytes", mime=WEBM, consent="true", **extra):
    data = {"voice_consent": consent, **extra}
    return {"files": {"file": ("clip.webm", audio, mime)}, "data": data}


# --- transcribe ----------------------------------------------------------


def test_transcribe_happy_path(client, sdk):
    response = client.post("/api/voice/transcribe", **upload())
    assert response.status_code == 200

    body = response.json()
    assert body["text"] == "How do I join ASPIRE?"
    assert body["language_code"] == "en"
    assert body["language_probability"] == pytest.approx(0.98)
    assert body["duration_seconds"] == pytest.approx(3.2)


def test_transcribe_sends_the_right_stt_options(client, sdk):
    client.post("/api/voice/transcribe", **upload(language="en"))
    call = sdk.stt_calls[0]

    assert call["model_id"] == "scribe_v2"
    # Upstream default is True; a transcript of "(laughter)" is not a message.
    assert call["tag_audio_events"] is False
    assert call["diarize"] is False
    assert "ASPIRE" in call["keyterms"]
    assert call["language_code"] == "en"


def test_missing_consent_is_rejected(client, sdk):
    response = client.post("/api/voice/transcribe", **upload(consent="false"))
    assert response.status_code == 403
    assert not sdk.stt_calls, "nothing may reach the paid API without consent"


def test_bad_mime_is_rejected_before_the_api(client, sdk):
    response = client.post("/api/voice/transcribe", **upload(mime="application/zip"))
    assert response.status_code == 415
    assert not sdk.stt_calls


@pytest.mark.parametrize(
    "mime",
    [
        "audio/webm;codecs=opus",  # Chrome, Edge
        "audio/webm; codecs=opus",  # same, with the optional space
        "audio/ogg;codecs=opus",  # Firefox
        "audio/mp4",  # Safari
        "AUDIO/WEBM",  # media types are case-insensitive
    ],
)
def test_recorder_mime_with_codec_parameter_is_accepted(client, sdk, mime):
    """What browsers actually send.

    `MediaRecorder.mimeType` carries the codec parameter, and that string
    becomes the blob type and then the upload's Content-Type. Matching the whole
    string against the allowlist rejected every recording Chrome produced, which
    is a 415 on the real path while every test here passed on a bare
    `audio/webm`.
    """
    response = client.post("/api/voice/transcribe", **upload(mime=mime))
    assert response.status_code == 200, response.text
    assert len(sdk.stt_calls) == 1


def test_mime_parameters_do_not_smuggle_a_disallowed_type(client, sdk):
    """Only the leading type counts — a parameter cannot launder the type."""
    response = client.post(
        "/api/voice/transcribe", **upload(mime="application/zip;codecs=opus")
    )
    assert response.status_code == 415
    assert not sdk.stt_calls


def test_oversize_upload_is_rejected_before_the_api(client, settings, sdk):
    big = b"x" * (settings.duration_guard_bytes + 1)
    response = client.post("/api/voice/transcribe", **upload(audio=big))
    assert response.status_code == 413
    assert not sdk.stt_calls


def test_empty_upload_is_rejected(client, sdk):
    response = client.post("/api/voice/transcribe", **upload(audio=b""))
    assert response.status_code == 400
    assert not sdk.stt_calls


def test_transcribe_upstream_failure_returns_503_fallback(client, settings, sdk):
    sdk.stt_error = RuntimeError("upstream 500")
    response = client.post("/api/voice/transcribe", **upload())
    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "voice_unavailable", "fallback": "browser"}


def test_transcribe_rate_limit_returns_429_with_retry_after(client, settings):
    for _ in range(settings.max_transcriptions_per_window):
        assert client.post("/api/voice/transcribe", **upload()).status_code == 200

    limited = client.post("/api/voice/transcribe", **upload())
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


# --- speak ---------------------------------------------------------------


def speak_body(**overrides):
    return {"text": "ASPIRE is free.", "persona": "nova", "language": "en", **overrides}


def test_speak_returns_mp3(client, sdk):
    response = client.post("/api/voice/speak", json=speak_body())
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3-fake-mp3"
    assert response.headers["X-Voice-Cache"] == "miss"


def test_speak_sanitises_before_synthesis(client, sdk):
    client.post(
        "/api/voice/speak",
        json=speak_body(text="## Cost [ASP-011]\n\nIt is **$500** at https://aspire.gov.kn."),
    )
    sent = sdk.tts_calls[0]["text"]
    assert "##" not in sent and "[ASP-011]" not in sent
    assert "http" not in sent
    assert "five hundred dollars" in sent


def test_speak_uses_the_persona_voice_and_settings(client, sdk):
    client.post("/api/voice/speak", json=speak_body(persona="stella"))
    call = sdk.tts_calls[0]
    assert call["voice_id"] == "v-stella"
    assert call["voice_settings"].speed == pytest.approx(0.90)


def test_number_heavy_text_uses_the_quality_model(client, settings, sdk):
    client.post("/api/voice/speak", json=speak_body(text="EC$500 for ages 5-18 in 2023."))
    assert sdk.tts_calls[0]["model_id"] == settings.tts_model_quality


def test_second_identical_request_is_served_from_cache(client, sdk):
    first = client.post("/api/voice/speak", json=speak_body())
    second = client.post("/api/voice/speak", json=speak_body())

    assert first.headers["X-Voice-Cache"] == "miss"
    assert second.headers["X-Voice-Cache"] == "hit"
    assert len(sdk.tts_calls) == 1, "a cache hit must not call the paid API"
    assert second.content == first.content


def test_speak_upstream_failure_returns_503_fallback(client, sdk):
    sdk.tts_error = RuntimeError("upstream 500")
    response = client.post("/api/voice/speak", json=speak_body())
    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "voice_unavailable", "fallback": "browser"}


def test_unsupported_format_is_rejected(client):
    assert client.post("/api/voice/speak", json=speak_body(format="wav")).status_code == 400


def test_unknown_persona_is_rejected_by_validation(client):
    assert client.post("/api/voice/speak", json=speak_body(persona="gandalf")).status_code == 422


def test_text_that_cleans_to_nothing_is_rejected(client, sdk):
    response = client.post("/api/voice/speak", json=speak_body(text="[ASP-001] https://a.gov.kn"))
    assert response.status_code == 400
    assert not sdk.tts_calls


# --- circuit breaker -----------------------------------------------------


def test_breaker_opens_after_three_failures_and_stops_calling(client, sdk):
    sdk.tts_error = RuntimeError("upstream down")
    for _ in range(3):
        assert client.post("/api/voice/speak", json=speak_body()).status_code == 503

    calls_before = len(sdk.tts_calls)
    assert client.post("/api/voice/speak", json=speak_body()).status_code == 503
    assert len(sdk.tts_calls) == calls_before, "breaker must short-circuit, not retry"


# --- config --------------------------------------------------------------


def test_config_reports_personas_languages_and_limits(client, settings):
    body = client.get("/api/voice/config").json()

    assert body["enabled"] is True
    assert {p["persona"] for p in body["personas"]} == {"stella", "orion", "aurora", "nova"}
    assert body["languages"] == ["en", "es", "fr"]
    assert body["limits"]["max_duration_seconds"] == settings.max_duration_seconds
    assert body["limits"]["max_file_size_bytes"] == settings.max_upload_bytes
    assert "audio/webm" in body["limits"]["allowed_mime_types"]
    assert body["realtime_enabled"] is False


def test_realtime_token_is_disabled_by_default(client):
    assert client.post("/api/voice/realtime-token").status_code == 501


# --- privacy -------------------------------------------------------------


def test_no_audio_is_written_to_the_cache_directory(client, settings):
    client.post("/api/voice/transcribe", **upload())
    cache_dir = settings.resolved(settings.voice_cache_dir)
    if cache_dir.exists():
        assert not list(cache_dir.glob("*.webm"))
        assert not list(cache_dir.glob("*.wav"))


def test_transcript_text_is_never_logged(client, caplog):
    with caplog.at_level("INFO"):
        client.post("/api/voice/transcribe", **upload())
    assert "How do I join ASPIRE?" not in caplog.text
