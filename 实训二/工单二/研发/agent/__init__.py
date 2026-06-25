"""
agent 模块
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

from .agent import ScheduleAgent, AgentConfig
from .llm import SiliconFlowChatModel, get_chat_model, SUPPORTED_MODELS
from .tools import add_schedule, query_schedules, delete_schedule, complete_schedule, set_recurring_schedule

__all__ = [
    "ScheduleAgent",
    "AgentConfig",
    "SiliconFlowChatModel",
    "get_chat_model",
    "SUPPORTED_MODELS",
    "add_schedule",
    "query_schedules",
    "delete_schedule",
    "complete_schedule",
    "set_recurring_schedule",
]
