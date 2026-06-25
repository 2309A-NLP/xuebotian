"""
Memory 模块
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
import json


class ConversationMemory:
    """对话记忆 - 兼容 agent/agent.py 接口"""

    def __init__(self, max_history: int = 20):
        self.max_history = max_history
        self._messages: List[Dict[str, str]] = []

    def add_message(self, msg) -> None:
        """添加消息，msg 可以是 dict 或 dataclass"""
        if isinstance(msg, dict):
            self._messages.append({"role": msg["role"], "content": msg["content"]})
        else:
            self._messages.append({"role": msg.role, "content": msg.content})

    def get_history(self) -> List[Dict[str, str]]:
        return self._messages[-self.max_history:]

    def clear(self) -> None:
        self._messages.clear()


# 全局实例
_conversation_memory: Optional[ConversationMemory] = None


def get_memory() -> ConversationMemory:
    global _conversation_memory
    if _conversation_memory is None:
        _conversation_memory = ConversationMemory()
    return _conversation_memory
