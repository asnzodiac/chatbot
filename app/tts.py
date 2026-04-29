from __future__ import annotations

import asyncio
import hashlib
import logging
import os
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
    def __init__(self, cache_dir: str = "/tmp/tts_cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _hash(self, voice: str, text: str) -> str:
        m = hashlib.md5()
        m.update((voice + "||" + text).encode("utf-8", errors="ignore"))
        return m.hexdigest()

    def voice_for_lang(self, lang: str) -> list[str]:
        # Required voices:
        # English → en-GB-RyanNeural
        # Malayalam → best available
        # Manglish → English voice
        if lang == "ml":
            return ["ml-IN-MidhunNeural", "ml-IN-SobhanaNeural", "en-IN-PrabhatNeural", "en-GB-RyanNeural"]
        if lang == "manglish":
            return ["en-IN-PrabhatNeural", "en-GB-RyanNeural"]
        return ["en-GB-RyanNeural", "en-IN-PrabhatNeural"]

    def synthesize(self, text: str, lang: str) -> TTSResult:
        text = (text or "").strip()
        if not text:
            return TTSResult(ok=False, path=None, error="empty_text")

        # Keep TTS bounded (Telegram + edge-tts can be slow for huge text)
        if len(text) > 1800:
            text = text[:1800].rsplit(" ", 1)[0] + "..."

        for voice in self.voice_for_lang(lang):
            h = self._hash(voice, text)
            out_path = os.path.join(self.cache_dir, f"{h}.mp3")
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return TTSResult(ok=True, path=out_path, error=None)

            try:
                asyncio.run(self._synth_async(text, voice, out_path))
                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    return TTSResult(ok=True, path=out_path, error=None)
            except Exception as e:
                log.warning("TTS failed for voice=%s: %s", voice, e)
                continue

        return TTSResult(ok=False, path=None, error="tts_failed_all_voices")

    async def _synth_async(self, text: str, voice: str, out_path: str) -> None:
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(out_path)
