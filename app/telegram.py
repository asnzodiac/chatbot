from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import requests

log = logging.getLogger("telegram")


class TelegramAPI:
    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    def _post(self, method: str, data: Optional[dict] = None, files: Optional[dict] = None, timeout: int = 20):
        url = f"{self.base}/{method}"
        try:
            r = requests.post(url, data=data, files=files, timeout=timeout)
            return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
        except Exception as e:
            log.exception("Telegram POST %s failed", method)
            return 0, {"ok": False, "error": str(e)}

    def send_message(self, chat_id: int, text: str, reply_to_message_id: Optional[int] = None) -> bool:
        data = {"chat_id": chat_id, "text": text}
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        code, resp = self._post("sendMessage", data=data)
        return bool(resp and isinstance(resp, dict) and resp.get("ok"))

    def send_audio(self, chat_id: int, audio_path: str, caption: Optional[str] = None) -> bool:
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:1024]
        try:
            with open(audio_path, "rb") as f:
                files = {"audio": f}
                code, resp = self._post("sendAudio", data=data, files=files, timeout=60)
                return bool(resp and isinstance(resp, dict) and resp.get("ok"))
        except Exception:
            log.exception("send_audio failed")
            return False

    def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        code, resp = self._post("sendChatAction", data={"chat_id": chat_id, "action": action})
        return bool(resp and isinstance(resp, dict) and resp.get("ok"))

    def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        code, resp = self._post("getFile", data={"file_id": file_id})
        if not (isinstance(resp, dict) and resp.get("ok")):
            return None
        return resp.get("result")

    def download_file(self, file_path: str, timeout: int = 60) -> Optional[bytes]:
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code != 200:
                return None
            return r.content
        except Exception:
            log.exception("download_file failed")
            return None

    def set_webhook(self, url: str) -> Tuple[bool, Any]:
        code, resp = self._post("setWebhook", data={"url": url}, timeout=20)
        ok = bool(isinstance(resp, dict) and resp.get("ok"))
        return ok, resp
