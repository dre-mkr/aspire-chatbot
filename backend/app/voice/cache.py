"""On-disk MP3 cache for synthesised speech.

Greetings, affirmations, quiz prompts and error lines are fixed strings played
over and over. Synthesising them on every play is money spent to get the same
bytes back.

The cache is per-process for its size bookkeeping but the files are shared, so
several workers can read each other's entries safely.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

from elevenlabs.types import VoiceSettings as ElevenVoiceSettings

from app.voice.config import VoiceSettings, get_voice_settings

logger = logging.getLogger(__name__)


def cache_key(
    text: str, voice_id: str, model_id: str, settings: ElevenVoiceSettings
) -> str:
    """Identity of a rendering. Any change to voice or delivery is a new entry."""
    payload = "\x1f".join(
        [
            text,
            voice_id,
            model_id,
            f"{settings.stability}",
            f"{settings.similarity_boost}",
            f"{settings.style}",
            f"{settings.speed}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class VoiceCache:
    def __init__(self, settings: VoiceSettings | None = None) -> None:
        self._settings = settings or get_voice_settings()
        self.directory = self._settings.resolved(self._settings.voice_cache_dir)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        return self.directory / f"{key}.mp3"

    def get(self, key: str) -> bytes | None:
        path = self.path_for(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning("Unreadable cache entry %s", key, exc_info=True)
            return None

        # Touch so the LRU sweep keeps what is actually being played.
        try:
            os.utime(path, None)
        except OSError:
            pass
        return data

    def put(self, key: str, audio: bytes) -> None:
        path = self.path_for(key)
        try:
            # Write to a temp file in the same directory and replace, so a reader
            # never sees a half-written MP3.
            with tempfile.NamedTemporaryFile(
                dir=self.directory, suffix=".part", delete=False
            ) as handle:
                handle.write(audio)
                temp = Path(handle.name)
            temp.replace(path)
        except OSError:
            logger.warning("Could not write cache entry %s", key, exc_info=True)
            return
        self.evict_if_needed()

    def evict_if_needed(self) -> None:
        """Drop the least recently used entries until back under the cap."""
        limit = self._settings.voice_cache_max_bytes
        try:
            entries = [(p, p.stat()) for p in self.directory.glob("*.mp3")]
        except OSError:
            return

        total = sum(stat.st_size for _, stat in entries)
        if total <= limit:
            return

        for path, stat in sorted(entries, key=lambda item: item[1].st_mtime):
            if total <= limit:
                break
            try:
                path.unlink()
                total -= stat.st_size
            except OSError:
                continue
        logger.info("Voice cache trimmed to %.1f MB", total / 1_048_576)

    def stats(self) -> dict[str, int]:
        try:
            sizes = [p.stat().st_size for p in self.directory.glob("*.mp3")]
        except OSError:
            return {"entries": 0, "bytes": 0}
        return {"entries": len(sizes), "bytes": sum(sizes)}


_cache: VoiceCache | None = None


def get_cache() -> VoiceCache:
    global _cache
    if _cache is None:
        _cache = VoiceCache()
    return _cache
