from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque, Dict, List


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


class MemoryStore:
    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self._lock = Lock()
        self._mem: Dict[int, Deque[ChatMessage]] = {}

    def get(self, chat_id: int) -> List[dict]:
        with self._lock:
            dq = self._mem.get(chat_id)
            if not dq:
                return []
            return [{"role": m.role, "content": m.content} for m in list(dq)]

    def append(self, chat_id: int, role: str, content: str) -> None:
        if not content:
            return
        with self._lock:
            dq = self._mem.setdefault(chat_id, deque())
            dq.append(ChatMessage(role=role, content=content))
            while len(dq) > self.max_messages:
                dq.popleft()

    def clear(self, chat_id: int) -> None:
        with self._lock:
            self._mem.pop(chat_id, None)
