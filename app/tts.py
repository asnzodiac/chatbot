from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import tempfile
import threading
from dataclasses import dataclass
from typing import Optional

import edge_tts

log = logging.getLogger("tts")


@dataclass(frozen=True)
class TTSResult:
    ok: bool
    path: Optional[str]
    error: Optional[str]


class TTSService:
    """
    Render/Gunicorn-safe Edge-TTS:
    - Uses /tmp by default (always writable on Render)
    - Avoids asyncio.run pitfalls by creating a dedicated event loop per call
    - Adds timeout + retries
    - Atomic file writes to avoid corrupted cache on concurrent requests
    """

    def __init__(self, cache_dir: str = "/tmp/tts_cache"):
        self.cache_dir = os.getenv("TTS_CACHE_DIR", cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)

        # Prevent multiple threads from generating the same file at the same time
        self._lock = threading.Lock()

        # Optional speaking style controls (Edge supports these formats)
        self.rate = os.getenv("EDGE_TTS_RATE", "+0%")
        self.volume = os.getenv("EDGE_TTS_VOLUME", "+0%")

    def _hash(self, voice: str, text: str) -> str:
        m = hashlib.md5()
        m.update((voice + "||" + text).encode("utf-8", errors="ignore"))
        return m.hexdigest()

    def voice_for_lang(self, lang: str) -> list[str]:
        # Jarvis-like male voice first
        jarvis_voice = os.getenv("EDGE_VOICE_EN", "en-US-GuyNeural")

        if lang == "ml":
            # Malayalam voices are limited; keep strong fallbacks
            return [
                os.getenv("EDGE_VOICE_ML_1", "ml-IN-MidhunNeural"),
                os.getenv("EDGE_VOICE_ML_2", "ml-IN-SobhanaNeural"),
                jarvis_voice,
                "en-IN-PrabhatNeural",
                "en-GB-RyanNeural",
            ]

        if lang == "manglish":
            return [
                jarvis_voice,
                "en-IN-PrabhatNeural",
                "en-GB-RyanNeural",
            ]

        # English
        return [
            jarvis_voice,
            "en-GB-RyanNeural",
            "en-IN-PrabhatNeural",
        ]

    def synthesize(self, text: str, lang: str) -> TTSResult:
        text = (text or "").strip()
        if not text:
            return TTSResult(ok=False, path=None, error="empty_text")

        # Bound the size (Edge + Telegram can choke on huge text)
        if len(text) > 1800:
            text = text[:1800].rsplit(" ", 1)[0] + "..."

        voices = self.voice_for_lang(lang)

        # small shuffle after first voice to reduce rate-limit patterns if many requests
        if len(voices) > 1:
            first = voices[0]
            rest = voices[1:]
            random.shuffle(rest)
            voices = [first] + rest

        last_err = None

        for voice in voices:
            key = self._hash(voice, text)
            out_path = os.path.join(self.cache_dir, f"{key}.mp3")

            # Cache hit
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return TTSResult(ok=True, path=out_path, error=None)

            # Generate with lock (prevents two workers writing same file)
            with self._lock:
                # Check again after lock (another thread may have generated it)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    return TTSResult(ok=True, path=out_path, error=None)

                try:
                    self._run_tts_to_file(text=text, voice=voice, out_path=out_path, timeout=35)
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                        return TTSResult(ok=True, path=out_path, error=None)
                    last_err = "tts_output_missing_or_empty"
                except Exception as e:
                    last_err = f"{type(e).__name__}:{e}"
                    log.warning("TTS failed voice=%s err=%s", voice, last_err)
                    continue

        return TTSResult(ok=False, path=None, error=f"tts_failed_all_voices:last={last_err}")

    def _run_tts_to_file(self, text: str, voice: str, out_path: str, timeout: int = 35) -> None:
        """
        Runs async edge-tts in a fresh event loop (Gunicorn-thread safe),
        writes atomically: tmpfile -> rename.
        """

        async def _job(tmp_path: str):
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=self.rate, volume=self.volume)
            await communicate.save(tmp_path)

        # write to temp file first (atomic)
        fd, tmp_path = tempfile.mkstemp(prefix="tts_", suffix=".mp3", dir=self.cache_dir)
        os.close(fd)
        try:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(asyncio.wait_for(_job(tmp_path), timeout=timeout))
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

            # Atomic replace
            os.replace(tmp_path, out_path)

        finally:
            # cleanup temp if something failed before replace
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
