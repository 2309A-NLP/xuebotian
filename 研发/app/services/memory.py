import json
import time
import traceback
from typing import Dict, List, Optional

import redis
from redis.exceptions import ResponseError

from app.core.config import (
    CONVERSATION_EXPIRE_SECONDS,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    SHORT_TERM_MEMORY_ROUNDS,
)
from app.core.logging_utils import get_logger


logger = get_logger(__name__)


class ConversationMemory:
    def __init__(self, max_rounds: int = SHORT_TERM_MEMORY_ROUNDS):
        self.max_rounds = max_rounds
        self.client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )

    def _get_key(self, session_id: str) -> str:
        return f"conversation:{session_id }"

    def _load_turns(self, key: str) -> List[Dict]:

        key_type = self.client.type(key)
        if isinstance(key_type, bytes):
            key_type = key_type.decode("utf-8")

        if key_type == "none":
            return []
        if key_type != "list":
            self.client.delete(key)
            return []

        items = self.client.lrange(key, 0, -1)
        turns: List[Dict] = []
        for item in items:
            try:
                turns.append(json.loads(item))
            except json.JSONDecodeError:
                logger.error(
                    "解析 Redis 会话历史失败，已跳过损坏记录。key=%s item=%r\n%s",
                    key,
                    item,
                    traceback.format_exc(),
                )
                continue
        return turns

    def get_recent_turns(self, session_id: str) -> List[Dict]:
        key = self._get_key(session_id)
        try:
            return self._load_turns(key)
        except ResponseError:
            logger.error(
                "读取 Redis 会话历史失败，已降级返回空列表。session_id=%s\n%s",
                session_id,
                traceback.format_exc(),
            )
            return []

    def get_message_history(
        self, session_id: str, turns: Optional[List[Dict]] = None
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        for turn in turns if turns is not None else self.get_recent_turns(session_id):
            user_message = turn.get("user_message")
            assistant_message = turn.get("assistant_message")
            if user_message:
                messages.append({"role": "user", "content": user_message})
            if assistant_message:
                messages.append({"role": "assistant", "content": assistant_message})
        return messages

    def add_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        character_name: Optional[str] = None,
    ) -> None:
        key = self._get_key(session_id)
        turn = {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "character_name": character_name,
            "timestamp": int(time.time()),
        }
        self.client.rpush(key, json.dumps(turn, ensure_ascii=False))

        self.client.ltrim(key, -self.max_rounds, -1)

        self.client.expire(key, CONVERSATION_EXPIRE_SECONDS)

    def get_last_character(
        self, session_id: str, turns: Optional[List[Dict]] = None
    ) -> Optional[str]:
        turns = turns if turns is not None else self.get_recent_turns(session_id)
        for turn in reversed(turns):
            character_name = turn.get("character_name")
            if character_name:
                return character_name
        return None

    def clear_history(self, session_id: str) -> None:
        self.client.delete(self._get_key(session_id))

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except redis.RedisError:
            logger.error(
                "Redis 连通性检查失败，已降级返回 False。\n%s",
                traceback.format_exc(),
            )
            return False
