from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings

try:
    from redis import Redis
except ImportError as exc:  # pragma: no cover - dependency check at runtime
    raise RuntimeError(
        "redis-py is required for Redis conversation history support. "
        "Please install dependencies from requirements.txt."
    ) from exc


class ConversationHistoryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = Redis.from_url(settings.redis_url, decode_responses=True)
        self.client.ping()

    def get_turns(self, user_id: str, session_id: str) -> list[dict[str, str]]:
        if not user_id or not session_id:
            return []
        raw = self.client.get(self._key(user_id, session_id))
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        return self._normalize_turns(payload)

    def get_messages(self, user_id: str, session_id: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for turn in self.get_turns(user_id, session_id):
            user_text = str(turn.get("user") or "").strip()
            assistant_text = str(turn.get("assistant") or "").strip()
            if user_text:
                messages.append({"role": "user", "text": user_text})
            if assistant_text:
                messages.append({"role": "assistant", "text": assistant_text})
        return messages[-self.settings.answer_history_max_messages :]

    def append_turn(
        self,
        user_id: str,
        session_id: str,
        question: str,
        answer: str,
    ) -> None:
        if not user_id or not session_id:
            return

        user_text = question.strip()
        assistant_text = answer.strip()
        if not user_text and not assistant_text:
            return

        turns = self.get_turns(user_id, session_id)
        turns.append({"user": user_text, "assistant": assistant_text})
        turns = turns[-self._max_turns() :]

        self.client.set(
            self._key(user_id, session_id),
            json.dumps(turns, ensure_ascii=False),
            ex=max(int(self.settings.chat_history_ttl_seconds), 1),
        )

    def clear_session(self, user_id: str, session_id: str) -> None:
        if not user_id or not session_id:
            return
        self.client.delete(self._key(user_id, session_id))

    def close(self) -> None:
        self.client.close()

    def _key(self, user_id: str, session_id: str) -> str:
        return f"chat:history:{user_id}:{session_id}"

    def _normalize_turns(self, payload: Any) -> list[dict[str, str]]:
        if not isinstance(payload, list):
            return []

        turns: list[dict[str, str]] = []
        pending_user = ""
        for item in payload:
            if not isinstance(item, dict):
                continue

            if "user" in item or "assistant" in item:
                user_text = str(item.get("user") or "").strip()
                assistant_text = str(item.get("assistant") or "").strip()
                if user_text or assistant_text:
                    turns.append({"user": user_text, "assistant": assistant_text})
                pending_user = ""
                continue

            role = str(item.get("role") or "").strip()
            text = str(item.get("text") or "").strip()
            if role not in {"user", "assistant"} or not text:
                continue
            if role == "user":
                if pending_user:
                    turns.append({"user": pending_user, "assistant": ""})
                pending_user = text
                continue
            turns.append({"user": pending_user, "assistant": text})
            pending_user = ""

        if pending_user:
            turns.append({"user": pending_user, "assistant": ""})
        return turns[-self._max_turns() :]

    def _max_turns(self) -> int:
        return max((int(self.settings.answer_history_max_messages) + 1) // 2, 1)
