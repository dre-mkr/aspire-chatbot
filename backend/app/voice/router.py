"""HTTP surface for the voice layer."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from app.timing import annotate as annotate_timings, turn as timed_turn
from app.voice.cache import cache_key, get_cache
from app.voice.client import VoiceUnavailable, get_client
from app.voice.config import ALLOWED_AUDIO_MIME, get_voice_settings
from app.voice.limiter import get_limiter
from app.voice.registry import Language, Persona, build_registry, resolve_profile
from app.voice.schemas import (
    PersonaVoice,
    SpeakRequest,
    TranscriptionResponse,
    VoiceConfigResponse,
    VoiceLimits,
)
from app.voice.speakable import has_many_numbers, speakable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

# What the client shows instead of a dead button when we cannot serve audio.
_FALLBACK = {"error": "voice_unavailable", "fallback": "browser"}


def _session_key(request: Request, thread_id: str | None) -> str:
    """Bucket for rate limiting: the caller's thread, else its address."""
    if thread_id:
        return f"thread:{thread_id}"
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


def _base_mime(raw: str | None) -> str:
    """The bare media type, without its RFC 2045 parameters."""
    return (raw or "").split(";", 1)[0].strip().lower()


@router.get("/config", response_model=VoiceConfigResponse)
def voice_config() -> VoiceConfigResponse:
    """Everything the client UI needs so it does not hardcode drifting numbers."""
    settings = get_voice_settings()
    registry = build_registry(settings)

    personas: list[PersonaVoice] = []
    for persona in Persona:
        languages = [lang for lang in Language if (persona, lang) in registry]
        if not languages:
            continue
        profile = registry[(persona, languages[0])]
        personas.append(
            PersonaVoice(
                persona=persona,
                languages=languages,
                speed=profile.settings.speed or 1.0,
                stability=profile.settings.stability or 0.5,
            )
        )

    return VoiceConfigResponse(
        enabled=settings.voice_enabled,
        personas=personas,
        languages=list(Language),
        limits=VoiceLimits(
            max_duration_seconds=settings.max_duration_seconds,
            max_file_size_bytes=settings.max_upload_bytes,
            allowed_mime_types=sorted(ALLOWED_AUDIO_MIME),
            max_transcriptions_per_window=settings.max_transcriptions_per_window,
            max_speech_per_window=settings.max_speech_per_window,
            rate_window_seconds=settings.rate_window_seconds,
        ),
        realtime_enabled=settings.voice_realtime_enabled,
    )


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    voice_consent: bool = Form(...),
    language: str | None = Form(default=None),
    persona: str | None = Form(default=None),
    thread_id: str | None = Form(default=None),
) -> TranscriptionResponse:
    settings = get_voice_settings()

    # Consent first: Stella's audience starts at five years old, so a recording without explicit consent is not som…
    if not voice_consent:
        raise HTTPException(
            status_code=403,
            detail="Voice consent is required before audio can be transcribed.",
        )

    if _base_mime(file.content_type) not in ALLOWED_AUDIO_MIME:
        raise HTTPException(
            status_code=415,
            # The unparsed value, so the log names exactly what the browser sent.
            detail=(
                f"Unsupported audio type {file.content_type!r}. "
                f"Supported: {', '.join(sorted(ALLOWED_AUDIO_MIME))}."
            ),
        )

    audio = await file.read()
    size = len(audio)
    if size == 0:
        raise HTTPException(status_code=400, detail="The audio file is empty.")
    if size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds the {settings.max_upload_bytes // 1_048_576} MB limit.",
        )
    # Byte proxy for the duration cap.
    if size > settings.duration_guard_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Audio is longer than the {settings.max_duration_seconds:.0f} second limit.",
        )

    decision = get_limiter().check_transcription(_session_key(request, thread_id))
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many voice requests. Please wait a moment.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    hint = Language(language).value if language in {l.value for l in Language} else None

    try:
        transcript = await get_client().transcribe(
            audio, file.filename or "audio.webm", hint
        )
    except VoiceUnavailable:
        raise HTTPException(status_code=503, detail=_FALLBACK) from None
    finally:
        # Drop the reference promptly; nothing else ever held it.
        del audio

    # Deliberately no transcript text and no persona in the log.
    logger.info(
        "transcribe ok bytes=%d duration=%.1fs language=%s p=%.2f",
        size,
        transcript.duration_seconds,
        transcript.language_code,
        transcript.language_probability,
    )

    if (
        transcript.duration_seconds
        and transcript.duration_seconds > settings.max_duration_seconds
    ):
        raise HTTPException(
            status_code=413,
            detail=f"Audio is longer than the {settings.max_duration_seconds:.0f} second limit.",
        )

    # The transcript is a user message and nothing more.
    return TranscriptionResponse(
        text=transcript.text,
        language_code=transcript.language_code,
        language_probability=transcript.language_probability,
        duration_seconds=transcript.duration_seconds,
    )


@router.post("/speak")
async def speak(request: Request, body: SpeakRequest) -> Response:
    """Text to audio."""
    with timed_turn(
        endpoint="/voice/speak",
        persona=body.persona.value,
        lang=body.language.value,
    ):
        return await _speak(request, body)


async def _speak(request: Request, body: SpeakRequest) -> Response:
    settings = get_voice_settings()

    if body.format.lower() != "mp3":
        raise HTTPException(
            status_code=400, detail=f"Unsupported format {body.format!r}. Use 'mp3'."
        )

    spoken = speakable(body.text, body.language, max_chars=settings.max_speakable_chars)
    if not spoken:
        raise HTTPException(status_code=400, detail="Nothing to say once the text was cleaned.")

    profile = resolve_profile(body.persona, body.language)
    # Figure-heavy lines go to the higher-quality model, which reads numbers better.
    model_id = (
        settings.tts_model_quality if has_many_numbers(body.text) else profile.model_id
    )

    key = cache_key(spoken, profile.voice_id, model_id, profile.settings)
    cache = get_cache()
    # `aget`/`aput`, not `get`/`put`: this is an async handler, and reading or writing a whole MP3 on the event loo…
    if (cached := await cache.aget(key)) is not None:
        annotate_timings(cache_hit=True)
        return Response(
            content=cached,
            media_type="audio/mpeg",
            headers={"X-Voice-Cache": "hit", "Cache-Control": "private, max-age=86400"},
        )

    decision = get_limiter().check_speech(_session_key(request, body.thread_id))
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many voice requests. Please wait a moment.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    try:
        audio = await get_client().synthesise(
            spoken, profile.voice_id, model_id, profile.settings
        )
    except VoiceUnavailable:
        raise HTTPException(status_code=503, detail=_FALLBACK) from None

    await cache.aput(key, audio)
    logger.info(
        "speak ok persona=%s language=%s chars=%d model=%s bytes=%d",
        body.persona.value,
        body.language.value,
        len(spoken),
        model_id,
        len(audio),
    )

    return StreamingResponse(
        iter((audio,)),
        media_type="audio/mpeg",
        headers={"X-Voice-Cache": "miss", "Cache-Control": "private, max-age=86400"},
    )


@router.post("/speak-stream")
async def speak_stream(request: Request, body: SpeakRequest) -> Response:
    """Text to audio, first byte before the last is synthesised (P14-C)."""
    with timed_turn(
        endpoint="/voice/speak-stream",
        persona=body.persona.value,
        lang=body.language.value,
    ):
        settings = get_voice_settings()

        if body.format.lower() != "mp3":
            raise HTTPException(
                status_code=400, detail=f"Unsupported format {body.format!r}. Use 'mp3'."
            )

        spoken = speakable(body.text, body.language, max_chars=settings.max_speakable_chars)
        if not spoken:
            raise HTTPException(
                status_code=400, detail="Nothing to say once the text was cleaned."
            )

        profile = resolve_profile(body.persona, body.language)
        model_id = (
            settings.tts_model_quality
            if has_many_numbers(body.text)
            else profile.model_id
        )

        headers = {
            "Cache-Control": "private, max-age=86400",
            # nginx buffers proxied responses by default, which would turn this back into exactly the wait it exists to rem…
            "X-Accel-Buffering": "no",
        }

        key = cache_key(spoken, profile.voice_id, model_id, profile.settings)
        cache = get_cache()
        if (cached := await cache.aget(key)) is not None:
            annotate_timings(cache_hit=True)
            return Response(
                content=cached,
                media_type="audio/mpeg",
                headers={**headers, "X-Voice-Cache": "hit"},
            )

        decision = get_limiter().check_speech(_session_key(request, body.thread_id))
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many voice requests. Please wait a moment.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

        # The first chunk is awaited HERE, before the response object exists, because a StreamingResponse has already c…
        stream = get_client().synthesise_stream(
            spoken, profile.voice_id, model_id, profile.settings
        )
        try:
            first = await anext(stream)
        except VoiceUnavailable:
            raise HTTPException(status_code=503, detail=_FALLBACK) from None
        except StopAsyncIteration:
            raise HTTPException(status_code=503, detail=_FALLBACK) from None

        async def body_and_cache():
            # Teed as it flows: the reader hears chunks now, the cache gets the whole file after -- but only when the strea…
            collected = [first]
            clean = False
            try:
                yield first
                async for chunk in stream:
                    collected.append(chunk)
                    yield chunk
                clean = True
            finally:
                if clean:
                    audio = b"".join(collected)
                    await cache.aput(key, audio)
                    logger.info(
                        "speak-stream ok persona=%s language=%s chars=%d model=%s bytes=%d",
                        body.persona.value,
                        body.language.value,
                        len(spoken),
                        model_id,
                        len(audio),
                    )

        return StreamingResponse(
            body_and_cache(),
            media_type="audio/mpeg",
            headers={**headers, "X-Voice-Cache": "miss"},
        )


@router.post("/realtime-token")
async def realtime_token() -> Response:
    """Stretch goal, disabled by default."""
    if not get_voice_settings().voice_realtime_enabled:
        raise HTTPException(
            status_code=501,
            detail="Realtime voice is not enabled. Set VOICE_REALTIME_ENABLED=true.",
        )
    raise HTTPException(status_code=501, detail="Realtime token issuance is not implemented yet.")
