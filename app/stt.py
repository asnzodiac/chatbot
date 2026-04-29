from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("stt")


@dataclass(frozen=True)
class STTResult:
    ok: bool
    text: Optional[str]
    error: Optional[str]


class STTService:
    """
    Crash-proof STT wrapper.

    - Does NOT import SpeechRecognition at module import time (prevents gunicorn boot crash).
    - If SpeechRecognition can't load (e.g., Python 3.14 missing aifc), STT is disabled gracefully.
    """

    def __init__(self):
        self._sr = None
        self._recognizer = None
        self._init_error: Optional[str] = None

        try:
            import speech_recognition as sr  # lazy import
            self._sr = sr
            self._recognizer = sr.Recognizer()
        except Exception as e:
            self._init_error = f"speech_recognition_unavailable:{e}"
            log.warning("STT disabled: %s", self._init_error)

    def available(self) -> bool:
        return self._sr is not None and self._recognizer is not None

    def transcribe_ogg_bytes(self, ogg_bytes: bytes) -> STTResult:
        if not ogg_bytes:
            return STTResult(ok=False, text=None, error="empty_audio")

        if not self.available():
            return STTResult(ok=False, text=None, error=self._init_error or "stt_unavailable")

        if not shutil.which("ffmpeg"):
            return STTResult(ok=False, text=None, error="ffmpeg_not_installed")

        sr = self._sr
        recognizer = self._recognizer

        with tempfile.TemporaryDirectory() as td:
            ogg_path = os.path.join(td, "audio.ogg")
            wav_path = os.path.join(td, "audio.wav")

            with open(ogg_path, "wb") as f:
                f.write(ogg_bytes)

            # Convert to wav (mono, 16kHz) for stability
            cmd = ["ffmpeg", "-y", "-i", ogg_path, "-ac", "1", "-ar", "16000", wav_path]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if p.returncode != 0:
                    return STTResult(ok=False, text=None, error=f"ffmpeg_convert_failed:{p.stderr[-300:]}")
            except Exception as e:
                return STTResult(ok=False, text=None, error=f"ffmpeg_exception:{e}")

            try:
                with sr.AudioFile(wav_path) as source:
                    audio = recognizer.record(source)
            except Exception as e:
                return STTResult(ok=False, text=None, error=f"audiofile_read_failed:{e}")

            # Primary ml-IN, fallback en-IN
            for lang in ("ml-IN", "en-IN"):
                try:
                    text = recognizer.recognize_google(audio, language=lang)
                    if text:
                        return STTResult(ok=True, text=text.strip(), error=None)
                except sr.UnknownValueError:
                    continue
                except Exception as e:
                    log.warning("STT recognize_google failed (%s): %s", lang, e)
                    continue

        return STTResult(ok=False, text=None, error="stt_failed")
