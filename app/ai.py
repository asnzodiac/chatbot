from __future__ import annotations

import itertools
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger("ai")


class LLMClient:
    def __init__(self, groq_keys: List[str], openrouter_key: Optional[str]):
        self._groq_keys = [k for k in groq_keys if k]
        self._openrouter_key = openrouter_key
        self._groq_cycle = itertools.cycle(self._groq_keys) if self._groq_keys else None

    def chat(self, messages: List[Dict[str, str]], model: str = "llama-3.3-70b-versatile") -> Tuple[bool, str]:
        # Try Groq first
        if self._groq_cycle:
            ok, txt = self._chat_groq(messages, model=model)
            if ok:
                return True, txt

        # Fallback
        if self._openrouter_key:
            return self._chat_openrouter(messages)

        return False, "LLM unavailable (no working provider keys)."

    def _chat_groq(self, messages: List[Dict[str, str]], model: str) -> Tuple[bool, str]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        last_err = None

        # Rotate keys on failure (up to number of keys * 2 attempts)
        attempts = max(2, min(6, len(self._groq_keys) * 2)) if self._groq_keys else 2

        for _ in range(attempts):
            key = next(self._groq_cycle)
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 700,
            }
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    if content:
                        return True, content.strip()
                    last_err = f"empty_content:{data}"
                    continue

                # Rotate on 401/429/5xx as well
                last_err = f"groq_http_{r.status_code}:{r.text[:500]}"
                log.warning("Groq failure: %s", last_err)
                continue

            except Exception as e:
                last_err = f"groq_exception:{e}"
                log.warning("Groq exception: %s", e)
                continue

        return False, f"Groq failed: {last_err or 'unknown'}"

    def _chat_openrouter(self, messages: List[Dict[str, str]]) -> Tuple[bool, str]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._openrouter_key}",
            "Content-Type": "application/json",
            # Optional but recommended by OpenRouter:
            "HTTP-Referer": "https://render.com",
            "X-Title": "Adimma Kann Telegram Bot",
        }
        payload = {
            "model": "openai/gpt-4o-mini",  # solid fallback; change anytime
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 700,
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=35)
            if r.status_code != 200:
                return False, f"OpenRouter HTTP {r.status_code}: {r.text[:500]}"
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return (True, content.strip()) if content else (False, "OpenRouter empty content")
        except Exception as e:
            log.exception("OpenRouter exception")
            return False, f"OpenRouter exception: {e}"
