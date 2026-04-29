from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_token: str
    webhook_url: str
    owner_id: int

    groq_api_keys: List[str]
    openrouter_api_key: Optional[str]

    openweather_api_key: Optional[str]
    serpapi_key: Optional[str]
    news_api_key: Optional[str]

    memory_max_messages: int = 20

    @staticmethod
    def load() -> "Config":
        load_dotenv()

        telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
        webhook_url = os.getenv("WEBHOOK_URL", "").strip()
        owner_id_raw = os.getenv("OWNER_ID", "").strip()

        if not telegram_token:
            raise RuntimeError("Missing TELEGRAM_TOKEN")
        if not webhook_url:
            raise RuntimeError("Missing WEBHOOK_URL")
        if not owner_id_raw.isdigit():
            raise RuntimeError("Missing/invalid OWNER_ID (must be integer Telegram user id)")

        groq_raw = os.getenv("GROQ_API_KEY", "").strip()
        groq_keys = [k.strip() for k in groq_raw.split(",") if k.strip()]

        return Config(
            telegram_token=telegram_token,
            webhook_url=webhook_url,
            owner_id=int(owner_id_raw),
            groq_api_keys=groq_keys,
            openrouter_api_key=(os.getenv("OPENROUTER_API_KEY") or "").strip() or None,
            openweather_api_key=(os.getenv("OPENWEATHER_API_KEY") or "").strip() or None,
            serpapi_key=(os.getenv("SERPAPI_KEY") or "").strip() or None,
            news_api_key=(os.getenv("NEWS_API_KEY") or "").strip() or None,
            memory_max_messages=int(os.getenv("MEMORY_MAX_MESSAGES", "20")),
        )
