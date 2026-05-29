import hashlib
import json
import traceback
from typing import Dict, List, Optional

import redis

from app.core.config import (
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    RESPONSE_CACHE_ENABLED,
    RESPONSE_CACHE_EXPIRE_SECONDS,
    RESPONSE_CACHE_MAX_HISTORY_CHARS,
)
from app.core.logging_utils import get_logger


logger = get_logger(__name__)


class ResponseCache:
    def __init__(self):
        self.enabled = RESPONSE_CACHE_ENABLED
        self.expire_seconds = max(60, RESPONSE_CACHE_EXPIRE_SECONDS)
        self.max_history_chars = max(80, RESPONSE_CACHE_MAX_HISTORY_CHARS)
        self.client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
        self.namespace = "response_cache"
        self.version_key = f"{self.namespace}:answer_version"

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().split())

    def _history_fingerprint(self, recent_turns: List[Dict]) -> str:
        parts: List[str] = []
        total_length = 0
        for turn in recent_turns[-3:]:
            user_message = self._normalize_text(turn.get("user_message", ""))
            assistant_message = self._normalize_text(turn.get("assistant_message", ""))
            character_name = self._normalize_text(turn.get("character_name", ""))
            for segment in (character_name, user_message, assistant_message):
                if not segment:
                    continue
                parts.append(segment)
                total_length += len(segment)
                if total_length >= self.max_history_chars:
                    return " | ".join(parts)[: self.max_history_chars]
        return " | ".join(parts)[: self.max_history_chars]

    def _build_key(
        self,
        *,
        query: str,
        character_name: Optional[str],
        chat_mode: str,
        recent_turns: List[Dict],
        answer_version: int,
    ) -> str:
        payload = {
            "query": self._normalize_text(query),
            "character_name": self._normalize_text(character_name or ""),
            "chat_mode": self._normalize_text(chat_mode),
            "recent_history": self._history_fingerprint(recent_turns),
            "answer_version": int(answer_version),
        }
        digest = hashlib.sha1(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return f"{self.namespace}:answer:{digest}"

    def get_knowledge_version(self) -> int:
        if not self.enabled:
            return 0
        try:
            value = self.client.get(self.version_key)
            return int(value or 0)
        except Exception:
            logger.error("读取响应缓存版本失败。\n%s", traceback.format_exc())
            return 0

    def bump_knowledge_version(self) -> int:
        if not self.enabled:
            return 0
        try:
            version = int(self.client.incr(self.version_key))
            logger.info("回答缓存版本已更新: version=%s", version)
            return version
        except Exception:
            logger.error("更新响应缓存版本失败。\n%s", traceback.format_exc())
            return 0

    def get(
        self,
        *,
        query: str,
        character_name: Optional[str],
        chat_mode: str,
        recent_turns: List[Dict],
    ) -> Optional[Dict]:
        if not self.enabled:
            return None
        try:
            key = self._build_key(
                query=query,
                character_name=character_name,
                chat_mode=chat_mode,
                recent_turns=recent_turns,
                answer_version=self.get_knowledge_version(),
            )
            payload = self.client.get(key)
            if not payload:
                return None
            data = json.loads(payload)
            if isinstance(data, dict) and data.get("answer"):
                logger.info("响应缓存命中: key=%s", key)
                return data
            return None
        except Exception:
            logger.error("读取响应缓存失败。\n%s", traceback.format_exc())
            return None

    def set(
        self,
        *,
        query: str,
        character_name: Optional[str],
        chat_mode: str,
        recent_turns: List[Dict],
        answer: str,
        effective_character: Optional[str],
    ) -> None:
        if not self.enabled:
            return
        try:
            key = self._build_key(
                query=query,
                character_name=character_name,
                chat_mode=chat_mode,
                recent_turns=recent_turns,
                answer_version=self.get_knowledge_version(),
            )
            payload = {
                "answer": answer,
                "character": effective_character or character_name,
                "chat_mode": chat_mode,
            }
            self.client.setex(
                key,
                self.expire_seconds,
                json.dumps(payload, ensure_ascii=False),
            )
            logger.info("响应缓存已写入: key=%s", key)
        except Exception:
            logger.error("写入响应缓存失败。\n%s", traceback.format_exc())
