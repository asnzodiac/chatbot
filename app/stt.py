from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple

import speech_recognition as sr

log = logging.getLogger("stt")


@dataclass(frozen=True)
class STTResult:
    ok: bool
    text: Optional[str]
    error: Optional[str]


class STTService:
    def __init__(self):
        self.recognizer = sr.Recognizer()

    def transcribe_ogg_bytes(self, ogg_bytes: bytes) -> STTResult:
        if not ogg_bytes:
            return STTResult(ok=False, text=None, error="empty_audio")

        if not shutil.which("ffmpeg"):
            return STTResult(ok=False, text=None, error="ffmpeg_not_installed")

        with tempfile.TemporaryDirectory() as td:
            ogg_path = os.path.join(td, "audio.ogg")
            wav_path = os.path.join(td, "audio.wav")
            with open(ogg_path, "wb") as f:
                f.write(ogg_bytes)

            # Convert to wav (mono, 16kHz) for SR stability
            cmd = [
                "ffmpeg", "-y",
                "-i", ogg_path,
                "-ac", "1",
                "-ar", "16000",
                wav_path,
            ]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if p.returncode != 0:
                    return STTResult(ok=False, text=None, error=f"ffmpeg_convert_failed:{p.stderr[-300:]}")
            except Exception as e:
                return STTResult(ok=False, text=None, error=f"ffmpeg_exception:{e}")

            try:
                with sr.AudioFile(wav_path) as source:
                    audio = self.recognizer.record(source)
            except Exception as e:
                return STTResult(ok=False, text=None, error=f"audiofile_read_failed:{e}")

            # Primary ml-IN, fallback en-IN
            for lang in ("ml-IN", "en-IN"):
                try:
                    text = self.recognizer.recognize_google(audio, language=lang)
                    if text:
                        return STTResult(ok=True, text=text.strip(), error=None)
                except sr.UnknownValueError:
                    continue
                except Exception as e:
                    log.warning("STT recognize_google failed (%s): %s", lang, e)
                    continue

        return STTResult(ok=False, text=None, error="stt_failed")
