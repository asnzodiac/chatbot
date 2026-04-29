from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.ai import LLMClient
from app.character import load_character_prompt
from app.config import Config
from app.external_apis import (
    detect_news_intent,
    detect_search_intent,
    detect_weather_intent,
    get_news,
    get_weather,
    parse_city_for_weather,
    parse_search_query,
    serp_search,
)
from app.language import detect_language
from app.media import describe_image, extract_pdf_text
from app.memory import MemoryStore
from app.state import ChatStateStore
from app.stt import STTService
from app.telegram import TelegramAPI
from app.tts import TTSService

log = logging.getLogger("handler")

# Singletons (safe enough for this small app)
_MEMORY: Optional[MemoryStore] = None
_STATE: Optional[ChatStateStore] = None
_TTS: Optional[TTSService] = None
_STT: Optional[STTService] = None


SLEEP_TRIGGERS = {"bye", "stop", "sleep", "standby", "good night", "goodnight"}
WAKE_TRIGGERS = {"hi", "hello", "wake up", "adimma", "adimma kann", "hey", "ഹലോ", "ഹായ്"}


def _get_singletons(cfg: Config):
    global _MEMORY, _STATE, _TTS, _STT
    if _MEMORY is None:
        _MEMORY = MemoryStore(max_messages=cfg.memory_max_messages)
    if _STATE is None:
        _STATE = ChatStateStore()
    if _TTS is None:
        _TTS = TTSService()
    if _STT is None:
        _STT = STTService()
    return _MEMORY, _STATE, _TTS, _STT


def handle_update(cfg: Config, tg: TelegramAPI, update: Dict[str, Any]) -> None:
    memory, state, tts, stt = _get_singletons(cfg)
    llm = LLMClient(cfg.groq_api_keys, cfg.openrouter_api_key)

    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    message_id = message.get("message_id")

    # Commands
    text = (message.get("text") or "").strip()
    if text.startswith("/start"):
        _on_start(cfg, tg, chat_id, message)
        return
    if text.startswith("/help"):
        _reply_text_and_voice(cfg, tg, tts, chat_id, message_id, _help_text())
        return
    if text.startswith("/clear"):
        memory.clear(chat_id)
        _reply_text_and_voice(cfg, tg, tts, chat_id, message_id, "Memory cleared. Fresh slate, sir.")
        return

    # Sleep gate (ignore everything unless wake)
    if state.is_sleeping(chat_id):
        # Wake only on wake triggers (text or voice recognized later)
        if text and _contains_trigger(text, WAKE_TRIGGERS):
            state.set_sleeping(chat_id, False)
            _reply_text_and_voice(cfg, tg, tts, chat_id, message_id, "Okay okay, I’m awake. What now?")
        return

    # If text triggers sleep, set sleep and acknowledge
    if text and _contains_trigger(text, SLEEP_TRIGGERS):
        state.set_sleeping(chat_id, True)
        _reply_text_and_voice(cfg, tg, tts, chat_id, message_id, "Alright then. Going standby. Wake me with “adimma”.")
        return

    # Handle message types -> convert into user_input
    user_input, detected_lang = _ingest_message(cfg, tg, stt, message)
    if not user_input:
        # If non-text unhandled, still respond safely (text+voice)
        _reply_text_and_voice(cfg, tg, tts, chat_id, message_id, "I got that, but I can’t read it properly. Try text/voice, sir.")
        return

    # Language detection based on user_input
    detection = detect_language(user_input)
    detected_lang = detection.lang  # overwrite if needed

    # Wake triggers while active: just respond normally (don’t toggle)
    # External APIs triggers
    tool_context = _maybe_call_tools(cfg, user_input)
    # Prepare LLM messages (character + rules + memory + current turn)
    character_prompt = load_character_prompt("character.txt")

    system_rules = (
        "You are a Telegram chat assistant.\n"
        "Always be emotionally intelligent and context-aware.\n"
        "Never be hateful or truly abusive; playful roasting only.\n"
        "You are loyal only to the owner referred to as 'sir'.\n"
        "Reply in the SAME language style as the user: English, Malayalam, or Manglish.\n"
        f"Detected user language: {detected_lang}.\n"
    )

    messages = [{"role": "system", "content": character_prompt},
                {"role": "system", "content": system_rules}]

    # Add tool context as system (keeps it stable)
    if tool_context:
        messages.append({"role": "system", "content": f"Useful context (from tools/APIs):\n{tool_context}"})

    # Add memory
    for m in memory.get(chat_id):
        messages.append(m)

    # Add current user input
    messages.append({"role": "user", "content": user_input})

    tg.send_chat_action(chat_id, "typing")
    ok, reply = llm.chat(messages)

    if not ok or not reply:
        reply = _fallback_reply(detected_lang)

    # Store memory
    memory.append(chat_id, "user", user_input)
    memory.append(chat_id, "assistant", reply)

    _reply_text_and_voice(cfg, tg, tts, chat_id, message_id, reply)


def _on_start(cfg: Config, tg: TelegramAPI, chat_id: int, message: Dict[str, Any]) -> None:
    user = message.get("from") or {}
    user_id = user.get("id")
    first_name = user.get("first_name", "")
    username = user.get("username", "")

    welcome = (
        "Adimma Kann reporting.\n\n"
        "Talk to me in English / മലയാളം / Manglish.\n"
        "Send voice notes too. I’ll talk back.\n\n"
        "Try:\n"
        "- weather in Kochi\n"
        "- news\n"
        "- search best biryani in kozhikode\n\n"
        "Commands: /help /clear"
    )
    tg.send_message(chat_id, welcome)

    # Notify owner
    try:
        note = f"New /start:\nuser_id={user_id}\nfirst_name={first_name}\nusername=@{username}" if username else f"New /start:\nuser_id={user_id}\nfirst_name={first_name}\nusername=(none)"
        tg.send_message(cfg.owner_id, note)
    except Exception:
        log.exception("Failed to notify owner on /start")


def _help_text() -> str:
    return (
        "How to use me:\n"
        "- Just message normally (English / മലയാളം / Manglish)\n"
        "- Send a voice note: I’ll transcribe + reply\n"
        "- Send a PDF: I can summarize/extract key points\n"
        "- Send an image: I’ll respond based on basic metadata + your caption\n\n"
        "Sleep: say “bye/stop/sleep/standby/good night”\n"
        "Wake: say “adimma/hello/wake up”\n\n"
        "Commands:\n"
        "/start – intro\n"
        "/help – this message\n"
        "/clear – clear chat memory"
    )


def _contains_trigger(text: str, triggers: set[str]) -> bool:
    t = (text or "").lower()
    return any(trg in t for trg in triggers)


def _ingest_message(cfg: Config, tg: TelegramAPI, stt: STTService, message: Dict[str, Any]) -> Tuple[Optional[str], str]:
    # Default language guess
    detected_lang = "en"

    # Text
    if message.get("text"):
        return message["text"].strip(), detected_lang

    # Voice
    if message.get("voice"):
        voice = message["voice"]
        file_id = voice.get("file_id")
        if not file_id:
            return None, detected_lang
        file_info = tg.get_file(file_id)
        if not file_info:
            return None, detected_lang
        content = tg.download_file(file_info.get("file_path", ""))
        if not content:
            return None, detected_lang
        stt_res = stt.transcribe_ogg_bytes(content)
        if stt_res.ok and stt_res.text:
            return stt_res.text, detected_lang
        # If STT fails, still respond with a prompt
        return "I got your voice note, but transcription failed. Try again a bit slower?", detected_lang

    # Photo
    if message.get("photo"):
        photos = message.get("photo") or []
        largest = photos[-1] if photos else None
        if not largest:
            return None, detected_lang
        file_id = largest.get("file_id")
        file_info = tg.get_file(file_id) if file_id else None
        if not file_info:
            return None, detected_lang
        img_bytes = tg.download_file(file_info.get("file_path", ""))
        info = describe_image(img_bytes or b"")
        caption = (message.get("caption") or "").strip()

        user_input = (
            "User sent an image.\n"
            f"Image metadata description: {info.description}\n"
            f"User caption (if any): {caption or '(no caption)'}\n"
            "Reply appropriately and ask a clarifying question if needed."
        )
        return user_input, detected_lang

    # Document (PDF)
    doc = message.get("document")
    if doc:
        filename = (doc.get("file_name") or "").lower()
        mime = (doc.get("mime_type") or "").lower()
        if "pdf" in mime or filename.endswith(".pdf"):
            file_id = doc.get("file_id")
            file_info = tg.get_file(file_id) if file_id else None
            if not file_info:
                return None, detected_lang
            pdf_bytes = tg.download_file(file_info.get("file_path", ""))
            pdf_text = extract_pdf_text(pdf_bytes or b"")
            caption = (message.get("caption") or "").strip()

            if not pdf_text.ok:
                return "I received a PDF, but I couldn't extract text from it. Is it scanned?", detected_lang

            # If user provided caption, treat it as query; else summarize
            user_query = caption or "Summarize this PDF clearly and briefly."
            user_input = (
                f"PDF content (extracted text, may be partial):\n{pdf_text.text}\n\n"
                f"User request: {user_query}"
            )
            return user_input, detected_lang

    return None, detected_lang


def _maybe_call_tools(cfg: Config, user_input: str) -> str:
    # Returns a string that will be injected into LLM as extra context
    contexts = []

    if detect_weather_intent(user_input):
        city = parse_city_for_weather(user_input) or "Kochi"
        w = get_weather(cfg.openweather_api_key, city)
        contexts.append(w.summary if w.ok else f"Weather tool failed: {w.error}")

    if detect_news_intent(user_input):
        n = get_news(cfg.news_api_key)
        contexts.append(n.summary if n.ok else f"News tool failed: {n.error}")

    if detect_search_intent(user_input):
        q = parse_search_query(user_input) or ""
        if q:
            s = serp_search(cfg.serpapi_key, q)
            contexts.append(s.summary if s.ok else f"Search tool failed: {s.error}")
        else:
            contexts.append("User asked to search, but no query was provided.")

    return "\n\n".join([c for c in contexts if c]).strip()


def _fallback_reply(lang: str) -> str:
    if lang == "ml":
        return "ചെറിയ ടെക്‌നിക്കൽ പണി ആയി, സാർ. ഒന്ന് വീണ്ടും പറയാമോ?"
    if lang == "manglish":
        return "Oru technical scene aayi, sir. Onnu veendum parayamo?"
    return "Small technical issue, sir. Can you say that again?"


def _reply_text_and_voice(cfg: Config, tg: TelegramAPI, tts: TTSService, chat_id: int, reply_to_message_id: Optional[int], text: str) -> None:
    # Always attempt both: text first (fast), then voice
    safe_text = (text or "").strip() or "..."

    # Telegram text can be max 4096; split if needed
    chunks = []
    while len(safe_text) > 4096:
        cut = safe_text[:4096]
        # try cut at newline/space
        cut = cut.rsplit("\n", 1)[0] if "\n" in cut else cut.rsplit(" ", 1)[0]
        if not cut:
            cut = safe_text[:4096]
        chunks.append(cut)
        safe_text = safe_text[len(cut):].lstrip()
    chunks.append(safe_text)

    for i, ch in enumerate(chunks):
        tg.send_message(chat_id, ch, reply_to_message_id=reply_to_message_id if i == 0 else None)

    # Voice
    # Detect language again for voice selection (based on final reply)
    lang = detect_language(text).lang
    tg.send_chat_action(chat_id, "upload_audio")

    tts_res = tts.synthesize(text, lang=lang)
    if tts_res.ok and tts_res.path:
        tg.send_audio(chat_id, tts_res.path)
    else:
        # Fail-safe: if voice fails, at least notify briefly in text (but don't spam)
        tg.send_message(chat_id, "Voice reply failed on my side. Text is above, sir.")
