"""
Agent 智能体核心
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

真正的 Agent 架构 = LLM + Tools + Memory
"""

import json
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .llm import SiliconFlowChatModel as LLMClient, get_llm_client
from .memory import ConversationMemory, get_memory
from .tools import Tool, ToolResult


class AgentState(Enum):
    """Agent 状态"""
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    RESPONDING = "responding"
    ERROR = "error"


@dataclass
class Message:
    """对话消息"""
    role: str  # system, user, assistant, tool
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "tool_call_id": self.tool_call_id
        }


@dataclass
class AgentConfig:
    """Agent 配置"""
    name: str = "日程提醒助手"
    description: str = "您的智能日程管理助手"
    model: str = "deepseek-ai/DeepSeek-V4-Flash"
    temperature: float = 0.7
    max_tokens: int = 2048
    system_prompt: str = ""
    api_key: str = ""
    api_base: str = "https://api.siliconflow.cn/v1"


class ScheduleAgent:
    """
    日程提醒智能体（真正的 Agent 架构）

    架构说明：
    1. LLM (Large Language Model) - 大脑，理解意图
    2. Tools - 工具，执行具体操作
    3. Memory - 记忆，存储对话历史
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm_client: Optional[LLMClient] = None,
        memory: Optional[ConversationMemory] = None
    ):
        """
        初始化 Agent

        Args:
            config: Agent 配置
            llm_client: LLM 客户端
            memory: 记忆模块
        """
        self.config = config or AgentConfig()
        self.llm = llm_client or get_llm_client(self.config)
        self.memory = memory or get_memory()
        self.tools: Dict[str, Tool] = {}
        self.state = AgentState.IDLE

        # 设置系统提示词
        self._setup_system_prompt()

        # 注册内置工具
        self._register_builtin_tools()

        # 把 LLM 客户端注入 tools 模块（用于 add_schedule_from_text 的二次解析）
        try:
            from .tools import set_llm_client
            set_llm_client(self.llm)
        except Exception as e:
            print(f"[Agent] 注入 LLM 客户端失败: {e}")

    def _setup_system_prompt(self):
        """设置系统提示词"""
        from datetime import date as _date, timedelta as _td

        today_str = _date.today().strftime("%Y-%m-%d")
        tomorrow_str = (_date.today() + _td(days=1)).strftime("%Y-%m-%d")
        day_after_str = (_date.today() + _td(days=2)).strftime("%Y-%m-%d")

        self.system_prompt = f"""你是一个日程提醒智能助手，你的唯一职责是通过工具来管理用户的日程。

【当前日期信息】
- 今天: {today_str}
- 明天: {tomorrow_str}
- 后天: {day_after_str}

【核心原则】你绝对不能自己编造任何日程信息！所有日程数据必须从数据库获取。

【工具调用规则】当你收到以下类型的用户请求时，必须立即调用对应的工具，禁止自行回答：
- **查询日程**（如"日程有哪些/有什么安排/查看日程/今天的日程"）→ 必须调用 query_schedules(query_date="今天")，**注意**：只有明确说了"日程"才查询，不要和其他操作混淆
- 用户说"添加/新建/安排日程" → 必须调用一次 add_schedule(time="HH:MM", date="YYYY-MM-DD", content="事项")
  示例："添加日程：上午8点起床" → add_schedule(time="08:00", date="{today_str}", content="起床")，只调用一次，不要重复
- 用户说"15:15|0000001|提醒我买咖啡"或竖线分隔格式 → 解析出 time=15:15、recurrence_rule=0000001、content="买咖啡"，调用 set_recurring_schedule(time_str=..., recurrence_rule=..., content=...)
- 用户说"删除/取消/删掉/去掉 日程 第X个/第X条"（如"删除日程1"、"取消第2个"）→ 必须调用 delete_schedule(position=序号)，序号从1开始
- 用户说"完成/做完了/标记完成/搞定了 日程 第X个/第X条" → 必须调用 complete_schedule(position=序号)

【禁止行为】
- **禁止重复调用工具**：每条用户消息最多调用一次对应工具！例如用户说"添加日程：上午8点起床"，只调用一次 add_schedule(time="08:00", date="{today_str}", content="起床")，**绝对不要**因为上一条消息的影响而调用第二次
- 禁止在回复中提及"查询中"、"正在查询"、"让我看看"等过程描述
- 禁止自己编造日程内容、时间、序号
- 禁止用"根据您的记录"等话术假装查询了数据库
- 禁止询问日期相关问题（如"请问是今天吗"）——日期由你自己从上面"当前日期信息"推断

【回复格式】
- 调用工具后，把工具返回的结果原样告诉用户
- 如果数据库返回空（"没有日程"），如实告知用户，不要加任何额外信息
- 不要在工具结果之前加任何前缀（如"查询结果如下"）

【add_schedule 工具说明（重要）】
- 工具接收三个字段：time、date、content
- 你必须自己从用户输入中解析这三个字段（这是你的工作，不要再调用其它解析工具）：
  - time: 24小时制 HH:MM。"下午5点"→"17:00"，"上午8点"→"08:00"，"中午12点"→"12:00"，"晚上7点"→"19:00"，"8点半"→"08:30"
  - date: YYYY-MM-DD。"今天"→{today_str}，"明天"→{tomorrow_str}，"后天"→{day_after_str}。**如果用户没说日期，默认填今天的日期 ({today_str})，不要追问**
  - content: 去除时间/日期/指令词/前缀后剩余的事项内容（如"下午5点开会"→"开会"，"提醒我买咖啡"→"买咖啡"）
  - 如果用户用了"|"分隔的特殊格式（如"15:15|0000001|提醒我买咖啡"），按竖线拆开：time / recurrence_rule / content
- 只有当 time 或 content 缺失时才向用户追问；date 没指定就默认填今天

【query_schedules 工具说明】
- 如果用户问"今天"，传入 query_date="今天"
- 如果用户问"明天"，传入 query_date="明天"
- 如果没指定日期，传入空字符串（会自动查今天）
"""

    def _register_builtin_tools(self):
        """注册内置工具"""
        from .tools import (
            add_schedule,
            query_schedules,
            delete_schedule,
            complete_schedule,
            set_recurring_schedule
        )

        self.register_tool(add_schedule)
        self.register_tool(query_schedules)
        self.register_tool(delete_schedule)
        self.register_tool(complete_schedule)
        self.register_tool(set_recurring_schedule)

    def register_tool(self, tool: Tool):
        """注册工具"""
        self.tools[tool.name] = tool
        print(f"[Agent] 已注册工具: {tool.name}")

    def unregister_tool(self, tool_name: str):
        """注销工具"""
        if tool_name in self.tools:
            del self.tools[tool_name]

    def get_tools_definition(self) -> List[Dict]:
        """获取工具定义（用于 LLM 调用）"""
        return [tool.to_openai_format() for tool in self.tools.values()]

    def process(self, user_input: str) -> str:
        """
        处理用户输入（核心方法）

        流程：
        1. 理解用户意图
        2. 决定是否需要调用工具
        3. 如果需要，调用工具
        4. 整合结果，生成回复

        Args:
            user_input: 用户输入

        Returns:
            Agent 回复
        """
        self.state = AgentState.THINKING

        try:
            # 1. 添加用户消息到记忆
            self.memory.add_message(Message(role="user", content=user_input))

            # 2. 获取对话历史，构建消息列表
            messages = self._build_messages()

            # 3. 调用 LLM，让它决定是否需要工具
            response = self.llm.chat(
                messages=messages,
                tools=self.get_tools_definition(),
                tool_choice="auto"
            )

            # 4. 处理 LLM 响应
            assistant_message = response["choices"][0]["message"]

            # 5. 检查是否有工具调用
            if "tool_calls" in assistant_message and assistant_message["tool_calls"]:
                return self._handle_tool_calls(assistant_message["tool_calls"], messages)
            else:
                # 没有工具调用，直接返回回复
                content = assistant_message.get("content", "")
                self.memory.add_message(Message(role="assistant", content=content))
                return content

        except Exception as e:
            self.state = AgentState.ERROR
            return f"抱歉，出错了: {str(e)}"

    def run(self, user_input: str) -> str:
        """
        运行入口（process 的别名）

        兼容 main_agent.py 中 agent.run(...) 的调用方式。

        Args:
            user_input: 用户输入

        Returns:
            Agent 回复
        """
        return self.process(user_input)

    def _handle_tool_calls(self, tool_calls: List[Dict], messages: List[Dict]) -> str:
        """处理工具调用"""
        self.state = AgentState.TOOL_CALLING

        results = []
        tool_messages = []
        for tool_call in tool_calls:
            function = tool_call["function"]
            tool_name = function["name"]
            arguments = json.loads(function["arguments"])

            # 查找工具
            if tool_name not in self.tools:
                results.append(f"工具 {tool_name} 不存在")
                continue

            tool = self.tools[tool_name]

            # 调用工具
            print(f"[Agent] 调用工具: {tool_name}, 参数: {arguments}")
            tool_result: ToolResult = tool.execute(**arguments)

            # 添加工具结果消息
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result.to_message()
            })

            results.append(tool_result.to_message())

        # 只调用了一个工具：直接返回工具结果，避免 LLM 二次总结时丢内容或幻觉
        if len(results) == 1:
            self.state = AgentState.RESPONDING
            content = results[0]
            # 把工具结果也加入消息历史，便于下次上下文
            for tm in tool_messages:
                messages.append(tm)
            # 添加一条 assistant 消息作为对工具调用的"回复"占位，保持消息链完整
            messages.append({"role": "assistant", "content": content})
            self.memory.add_message(Message(role="assistant", content=content))
            return content

        # 多次工具调用：让 LLM 整合工具结果生成最终回复
        for tm in tool_messages:
            messages.append(tm)
        self.state = AgentState.RESPONDING
        final_response = self.llm.chat(
            messages=messages,
            tools=None  # 不再需要工具
        )

        content = final_response["choices"][0]["message"]["content"]
        self.memory.add_message(Message(role="assistant", content=content))

        return content

    def _build_messages(self) -> List[Dict]:
        """构建消息列表"""
        messages = [{"role": "system", "content": self.system_prompt}]

        # 添加对话历史（兼容 Message 对象和 dict 两种形态）
        history = self.memory.get_history()
        for msg in history:
            if isinstance(msg, dict):
                messages.append(msg)
            else:
                messages.append(msg.to_dict())

        return messages

    def reset(self):
        """重置 Agent，清空记忆"""
        self.memory.clear()
        self.state = AgentState.IDLE

    def get_status(self) -> Dict[str, Any]:
        """获取 Agent 状态"""
        return {
            "state": self.state.value,
            "name": self.config.name,
            "model": self.config.model,
            "tools_count": len(self.tools),
            "memory_count": len(self.memory.get_history())
        }


# 全局 Agent 实例
_agent: Optional[ScheduleAgent] = None


def get_agent(config: Optional[AgentConfig] = None) -> ScheduleAgent:
    """获取 Agent 实例"""
    global _agent
    if _agent is None:
        _agent = ScheduleAgent(config)
    return _agent


def reset_agent():
    """重置 Agent"""
    global _agent
    if _agent:
        _agent.reset()
