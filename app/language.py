from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from langdetect import detect_langs

Lang = Literal["en", "ml", "manglish"]

_MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")

# Minimal Manglish heuristic dictionary (expand anytime)
_MANG_WORDS = {
    "entha", "enthaa", "enth", "alle", "poyi", "pooyi", "cheyyu", "cheyy", "cheyyuka",
    "da", "di", "machane", "bro", "chetta", "chechi", "setta", "ivide", "avid", "kollam",
    "sheri", "nalla", "okke", "engane", "evide", "appo", "pinne", "oru", "onnum",
    "sugam", "aano", "aano?", "aanoo", "ayyo", "mwone", "mwonee", "poda", "podi",
}

_WORD_RE = re.compile(r"[A-Za-z']+")


@dataclass(frozen=True)
class Detection:
    lang: Lang
    reason: str


def detect_language(text: str) -> Detection:
    t = (text or "").strip()
    if not t:
        return Detection(lang="en", reason="empty->en")

    # Malayalam unicode always wins
    if _MALAYALAM_RE.search(t):
        return Detection(lang="ml", reason="malayalam_unicode")

    # Tokenize for Manglish scoring
    tokens = [w.lower() for w in _WORD_RE.findall(t)]
    mang_score = 0
    for w in tokens:
        if w in _MANG_WORDS:
            mang_score += 2
        # common Manglish suffix patterns
        if w.endswith(("alle", "aa", "aay", "anu", "aano", "entho")):
            mang_score += 1

    # langdetect probabilities
    try:
        probs = detect_langs(t)
        top = probs[0]
        top_lang = top.lang
        top_prob = top.prob
    except Exception:
        top_lang, top_prob = "en", 0.0

    # Score-based decision
    if mang_score >= 3 and top_lang in ("en", "id", "tl", "so", "sw", "de", "fr"):
        return Detection(lang="manglish", reason=f"manglish_score={mang_score}, langdetect={top_lang}:{top_prob:.2f}")

    if top_lang == "ml":
        return Detection(lang="ml", reason=f"langdetect_ml:{top_prob:.2f}")

    return Detection(lang="en", reason=f"langdetect_{top_lang}:{top_prob:.2f}")
