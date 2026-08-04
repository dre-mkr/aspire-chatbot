"""On-disk MP3 cache for synthesised speech.

Greetings, affirmations, quiz prompts and error lines are fixed strings played
over and over. Synthesising them on every play is money spent to get the same
bytes back.

The cache is per-process for its size bookkeeping but the files are shared, so
several workers can read each other's entries safely.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import time
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


#: How long a full sweep is trusted for.
#:
#: Eviction used to run on every `put`: a `glob` across the cache directory and
#: a `stat` on every entry, on the event loop, per synthesis. That is O(entries)
#: syscalls for one write, growing as the cache fills -- the opposite of what a
#: cache should do -- and under `--workers 1` it serialised against live chat
#: turns.
#:
#: The size is tracked incrementally between sweeps instead, and a sweep only
#: happens when the running total says the cap is breached or the estimate has
#: gone stale. Sixty seconds because the estimate drifts: another worker sharing
#: this directory can add or remove files this process never saw.
_SWEEP_INTERVAL_SECONDS = 60.0


class VoiceCache:
    def __init__(self, settings: VoiceSettings | None = None) -> None:
        self._settings = settings or get_voice_settings()
        self.directory = self._settings.resolved(self._settings.voice_cache_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        #: Bytes on disk as far as this process knows. `-1` means "never
        #: measured", which forces a sweep on the first write.
        self._known_bytes = -1
        self._last_sweep = 0.0

    # ── async wrappers ────────────────────────────────────────────────────
    #
    # `speak` is an async handler, so every blocking call below would otherwise
    # run on the event loop. Reading a whole MP3 and writing one are both real
    # I/O; a thread costs far less than stalling every other request behind it.

    async def aget(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self.get, key)

    async def aput(self, key: str, audio: bytes) -> None:
        await asyncio.to_thread(self.put, key, audio)

    async def astats(self) -> dict[str, int]:
        return await asyncio.to_thread(self.stats)

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

        # Count what was just written rather than re-measuring the directory.
        if self._known_bytes >= 0:
            self._known_bytes += len(audio)
        self.evict_if_needed()

    def _sweep_due(self) -> bool:
        """Whether the directory is worth walking again.

        Three reasons to look: nothing has ever been measured, the running total
        says the cap is breached, or the total is old enough that another worker
        sharing this directory could have changed it underneath us.
        """
        if self._known_bytes < 0:
            return True
        if self._known_bytes > self._settings.voice_cache_max_bytes:
            return True
        return (time.monotonic() - self._last_sweep) >= _SWEEP_INTERVAL_SECONDS

    def evict_if_needed(self) -> None:
        """Drop the least recently used entries until back under the cap."""
        if not self._sweep_due():
            return

        limit = self._settings.voice_cache_max_bytes
        try:
            entries = [(p, p.stat()) for p in self.directory.glob("*.mp3")]
        except OSError:
            return

        total = sum(stat.st_size for _, stat in entries)
        # Recorded whether or not anything is dropped: a sweep that finds the
        # cache comfortably under the cap is exactly the one worth remembering,
        # because it is the one that buys the next minute of not sweeping.
        self._known_bytes = total
        self._last_sweep = time.monotonic()
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
        self._known_bytes = total
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
