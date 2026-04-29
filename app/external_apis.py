from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger("external")


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    summary: str
    error: Optional[str] = None


def _req_json(url: str, params: dict, timeout: int = 15):
    r = requests.get(url, params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def detect_weather_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["weather", "temperature", "കാലാവസ്ഥ", "താപനില", "mazha", "climate"])


def parse_city_for_weather(text: str) -> Optional[str]:
    t = (text or "").strip()
    m = re.search(r"\b(?:in|at)\s+([A-Za-z\u0D00-\u0D7F\s\-]{2,40})", t, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def get_weather(openweather_key: Optional[str], city: str) -> ToolResult:
    if not openweather_key:
        return ToolResult(ok=False, summary="", error="OPENWEATHER_API_KEY missing")
    try:
        data = _req_json(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": openweather_key, "units": "metric"},
        )
        main = data.get("main", {})
        wind = data.get("wind", {})
        w = (data.get("weather") or [{}])[0]
        summary = (
            f"Weather for {city}: {w.get('main','')} - {w.get('description','')}. "
            f"Temp {main.get('temp')}°C (feels {main.get('feels_like')}°C). "
            f"Humidity {main.get('humidity')}%. Wind {wind.get('speed')} m/s."
        )
        return ToolResult(ok=True, summary=summary)
    except Exception as e:
        log.warning("weather failed: %s", e)
        return ToolResult(ok=False, summary="", error=str(e))


def detect_news_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["news", "headlines", "വാർത്ത", "വാര്‍ത്ത", "breaking"])


def get_news(news_key: Optional[str], country: str = "in") -> ToolResult:
    if not news_key:
        return ToolResult(ok=False, summary="", error="NEWS_API_KEY missing")
    try:
        data = _req_json(
            "https://newsapi.org/v2/top-headlines",
            params={"apiKey": news_key, "country": country, "pageSize": 5},
        )
        arts = data.get("articles") or []
        lines = []
        for a in arts[:5]:
            title = a.get("title") or "Untitled"
            src = (a.get("source") or {}).get("name") or "Unknown"
            lines.append(f"- {title} ({src})")
        summary = "Top headlines:\n" + ("\n".join(lines) if lines else "- No headlines found.")
        return ToolResult(ok=True, summary=summary)
    except Exception as e:
        log.warning("news failed: %s", e)
        return ToolResult(ok=False, summary="", error=str(e))


def detect_search_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["search", "google", "lookup", "find"])


def parse_search_query(text: str) -> Optional[str]:
    t = (text or "").strip()
    # naive: remove leading keyword
    for k in ["search", "google", "lookup", "find"]:
        if t.lower().startswith(k):
            return t[len(k):].strip(" :.-")
    m = re.search(r"\b(?:search|google)\b\s*(.+)$", t, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def serp_search(serp_key: Optional[str], query: str) -> ToolResult:
    if not serp_key:
        return ToolResult(ok=False, summary="", error="SERPAPI_KEY missing")
    try:
        data = _req_json(
            "https://serpapi.com/search.json",
            params={"api_key": serp_key, "q": query, "engine": "google"},
            timeout=20,
        )
        results = data.get("organic_results") or []
        lines = []
        for r in results[:5]:
            title = r.get("title") or "Untitled"
            link = r.get("link") or ""
            snippet = r.get("snippet") or ""
            lines.append(f"- {title}\n  {link}\n  {snippet}")
        summary = f"Search results for: {query}\n" + ("\n".join(lines) if lines else "- No results found.")
        return ToolResult(ok=True, summary=summary)
    except Exception as e:
        log.warning("search failed: %s", e)
        return ToolResult(ok=False, summary="", error=str(e))
