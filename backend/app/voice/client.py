"""The ElevenLabs boundary."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

from elevenlabs.core import RequestOptions
from elevenlabs.types import VoiceSettings as ElevenVoiceSettings

from app.timing import T_TTS_FIRST_BYTE, record_stage
from app.voice.config import ASPIRE_KEYTERMS, VoiceSettings, get_voice_settings

logger = logging.getLogger(__name__)


class VoiceUnavailable(RuntimeError):
    """Upstream failed, timed out, or the breaker is open."""


@dataclass
class Transcript:
    text: str
    language_code: str
    language_probability: float
    duration_seconds: float


class CircuitBreaker:
    """Stop hammering an API that is already failing."""

    def __init__(self, threshold: int, reset_seconds: float) -> None:
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self._reset_seconds:
                # Cool-off elapsed: let the next call through and judge by it.
                self._opened_at = None
                self._failures = 0
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                logger.warning(
                    "Voice circuit breaker opened after %d consecutive failures; "
                    "short-circuiting for %.0fs",
                    self._failures,
                    self._reset_seconds,
                )

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None


class VoiceClient:
    def __init__(self, settings: VoiceSettings | None = None, client=None) -> None:
        self._settings = settings or get_voice_settings()
        self._breaker = CircuitBreaker(
            self._settings.breaker_failure_threshold,
            self._settings.breaker_reset_seconds,
        )
        self._client = client
        if client is None:
            if not self._settings.elevenlabs_api_key:
                raise VoiceUnavailable("ELEVENLABS_API_KEY is not set.")
            from elevenlabs.client import ElevenLabs

            self._client = ElevenLabs(api_key=self._settings.elevenlabs_api_key)

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    async def transcribe(self, audio: bytes, filename: str, language_hint: str | None) -> Transcript:
        """Batch speech-to-text. `audio` is never written anywhere."""
        if self._breaker.is_open:
            raise VoiceUnavailable("Voice temporarily disabled by circuit breaker.")

        # keyterms bias recognition toward local names, at +20% on the call.
        keyterms = list(ASPIRE_KEYTERMS) if self._settings.keyterms_enabled else None

        def call():
            return self._client.speech_to_text.convert(
                file=(filename, audio, "application/octet-stream"),
                model_id=self._settings.stt_model,
                language_code=language_hint,
                # Defaults to True upstream; a transcript full of "(laughter)" is not a user message.
                tag_audio_events=False,
                diarize=False,
                keyterms=keyterms,
                request_options=RequestOptions(
                    timeout_in_seconds=int(self._settings.stt_timeout_seconds)
                ),
            )

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(call), timeout=self._settings.stt_timeout_seconds
            )
        except TimeoutError as exc:
            self._breaker.record_failure()
            raise VoiceUnavailable("Transcription timed out.") from exc
        except Exception as exc:
            self._breaker.record_failure()
            logger.warning("Transcription failed: %s", type(exc).__name__, exc_info=True)
            raise VoiceUnavailable("Transcription failed.") from exc

        self._breaker.record_success()
        return Transcript(
            text=(getattr(raw, "text", "") or "").strip(),
            language_code=getattr(raw, "language_code", None) or "unknown",
            language_probability=float(getattr(raw, "language_probability", 0.0) or 0.0),
            duration_seconds=_duration_of(raw),
        )

    async def synthesise(
        self,
        text: str,
        voice_id: str,
        model_id: str,
        settings: ElevenVoiceSettings,
        output_format: str = "mp3_44100_128",
    ) -> bytes:
        """Text-to-speech, returned whole so it can be cached and replayed."""
        if self._breaker.is_open:
            raise VoiceUnavailable("Voice temporarily disabled by circuit breaker.")

        def call() -> bytes:
            started = time.perf_counter()
            stream = self._client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=model_id,
                output_format=output_format,
                voice_settings=settings,
                # 'auto' is the documented default.
                apply_text_normalization="auto",
                request_options=RequestOptions(
                    timeout_in_seconds=int(self._settings.tts_timeout_seconds)
                ),
            )
            # `t_tts_first_byte` is measured where the first chunk arrives from the vendor -- which is NOT when the caller…
            chunks: list[bytes] = []
            for chunk in stream:
                if not chunk:
                    continue
                if not chunks:
                    record_stage(
                        T_TTS_FIRST_BYTE, (time.perf_counter() - started) * 1000.0
                    )
                chunks.append(chunk)
            return b"".join(chunks)

        try:
            audio = await asyncio.wait_for(
                asyncio.to_thread(call), timeout=self._settings.tts_timeout_seconds
            )
        except TimeoutError as exc:
            self._breaker.record_failure()
            raise VoiceUnavailable("Speech synthesis timed out.") from exc
        except Exception as exc:
            self._breaker.record_failure()
            logger.warning("Synthesis failed: %s", type(exc).__name__, exc_info=True)
            raise VoiceUnavailable("Speech synthesis failed.") from exc

        if not audio:
            self._breaker.record_failure()
            raise VoiceUnavailable("Speech synthesis returned no audio.")

        self._breaker.record_success()
        return audio

    async def synthesise_stream(
        self,
        text: str,
        voice_id: str,
        model_id: str,
        settings: ElevenVoiceSettings,
        output_format: str = "mp3_44100_128",
    ):
        """Text-to-speech, yielded chunk by chunk as the vendor produces it."""
        if self._breaker.is_open:
            raise VoiceUnavailable("Voice temporarily disabled by circuit breaker.")

        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        sentinel_done, sentinel_failed = object(), object()
        #: Set when the consumer walks away -- a disconnect, a cancel -- so the producer stops pulling (and billing) ins…
        abandoned = threading.Event()

        def produce() -> None:
            try:
                # `stream`, NOT `convert`.
                stream = self._client.text_to_speech.stream(
                    voice_id=voice_id,
                    text=text,
                    model_id=model_id,
                    output_format=output_format,
                    voice_settings=settings,
                    apply_text_normalization="auto",
                    request_options=RequestOptions(
                        timeout_in_seconds=int(self._settings.tts_timeout_seconds)
                    ),
                )
                for chunk in stream:
                    if abandoned.is_set():
                        return
                    if chunk:
                        # Blocks when the consumer is slower than the vendor, which is the backpressure keeping memory flat.
                        asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
                asyncio.run_coroutine_threadsafe(queue.put(sentinel_done), loop).result()
            except Exception:
                if abandoned.is_set():
                    return
                logger.warning("Streaming synthesis failed mid-flight.", exc_info=True)
                try:
                    asyncio.run_coroutine_threadsafe(
                        queue.put(sentinel_failed), loop
                    ).result()
                except Exception:  # pragma: no cover - loop torn down under us
                    pass

        worker = loop.run_in_executor(None, produce)

        produced_any = False
        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=self._settings.tts_timeout_seconds
                    )
                except TimeoutError:
                    self._breaker.record_failure()
                    if produced_any:
                        logger.warning("Streaming synthesis stalled; ending early.")
                        return
                    raise VoiceUnavailable("Speech synthesis timed out.") from None

                if item is sentinel_done:
                    break
                if item is sentinel_failed:
                    self._breaker.record_failure()
                    if produced_any:
                        # Bytes are on the wire; a truncated stream is the honest remainder of this turn.
                        return
                    raise VoiceUnavailable("Speech synthesis failed.")

                if not produced_any:
                    record_stage(
                        T_TTS_FIRST_BYTE, (time.perf_counter() - started) * 1000.0
                    )
                    produced_any = True
                yield item
        finally:
            # Orderly on every exit: tell the producer to stop, then drain until it has -- a put blocked on a full queue co…
            abandoned.set()
            while not worker.done():
                while not queue.empty():
                    queue.get_nowait()
                await asyncio.sleep(0.02)
            await worker

        if not produced_any:
            self._breaker.record_failure()
            raise VoiceUnavailable("Speech synthesis returned no audio.")
        self._breaker.record_success()


def _duration_of(raw: object) -> float:
    """Duration is not always on the response; treat absence as unknown."""
    for attribute in ("duration", "audio_duration_seconds", "duration_seconds"):
        value = getattr(raw, attribute, None)
        if isinstance(value, (int, float)):
            return float(value)

    words = getattr(raw, "words", None) or []
    ends = [getattr(w, "end", None) for w in words]
    ends = [e for e in ends if isinstance(e, (int, float))]
    return float(max(ends)) if ends else 0.0


_client: VoiceClient | None = None


def get_client() -> VoiceClient:
    global _client
    if _client is None:
        _client = VoiceClient()
    return _client


def set_client(client: VoiceClient | None) -> None:
    """Test seam: inject a client built around a mock SDK."""
    global _client
    _client = client
