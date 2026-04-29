from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional


class ChatStateStore:
    """
    Stores sleeping/active per chat.

    Render free tier disk is ephemeral across deploys; this still satisfies
    "persist per chat" during runtime and across requests within same instance.
    """
    def __init__(self, db_path: str = "data/state.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_state (
                    chat_id INTEGER PRIMARY KEY,
                    sleeping INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            con.commit()

    def is_sleeping(self, chat_id: int) -> bool:
        row = None
        with self._connect() as con:
            row = con.execute(
                "SELECT sleeping FROM chat_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if not row:
            return False
        return bool(row[0])

    def set_sleeping(self, chat_id: int, sleeping: bool) -> None:
        now = int(time.time())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO chat_state(chat_id, sleeping, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET sleeping=excluded.sleeping, updated_at=excluded.updated_at
                """,
                (chat_id, int(sleeping), now),
            )
            con.commit()
