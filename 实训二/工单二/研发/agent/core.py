"""
Agent 核心模块
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

from langchain_core.messages import HumanMessage
from langchain.agents import create_agent as langchain_create_agent

from .llm import get_chat_model
from .tools import (
    add_schedule, query_schedules, delete_schedule,
    complete_schedule, set_recurring_schedule
)


class ScheduleAgent:
    """日程提醒智能体"""

    def __init__(self, llm=None):
        self.llm = llm
        self._graph = None

    def initialize(self, api_key: str, model: str = "deepseek-ai/DeepSeek-V4-Flash") -> None:
        if not api_key:
            raise ValueError("请先配置 API Key！")

        self.llm = get_chat_model(api_key=api_key, model=model)

        system_prompt = """你是一个日程提醒智能助手，你的唯一职责是通过工具来管理用户的日程。

【核心原则】你绝对不能自己编造任何日程信息！所有日程数据必须从数据库获取。

【工具调用规则】当你收到以下类型的用户请求时，必须立即调用对应的工具，禁止自行回答：
- 用户问"日程有哪些/有什么安排/查看日程" → 必须调用 query_schedules(query_date="今天") 或 query_schedules(query_date="明天") 等
- 用户说"添加/新建/安排日程" → 必须调用 add_schedule(user_input="用户原话")
- 用户说"删除/取消日程" → 必须调用 delete_schedule(position=序号)
- 用户说"完成/完成了/标记完成" → 必须调用 complete_schedule(position=序号)
- 用户说"设置循环/每周/每天重复" → 必须调用 set_recurring_schedule(...)

【禁止行为】
- 禁止在回复中提及"查询中"、"正在查询"、"让我看看"等过程描述
- 禁止自己编造日程内容、时间、序号
- 禁止用"根据您的记录"等话术假装查询了数据库

【回复格式】
- 调用工具后，把工具返回的结果原样告诉用户
- 如果数据库返回空（"没有日程"），如实告知用户，不要加任何额外信息
- 不要在工具结果之前加任何前缀（如"查询结果如下"）

【add_schedule 工具说明】
- 直接传入用户原始输入，如"下午5点开会"
- 不要尝试自己解析时间，只传 user_input 即可

【query_schedules 工具说明】
- 如果用户问"今天"，传入 query_date="今天"
- 如果用户问"明天"，传入 query_date="明天"
- 如果没指定日期，传入空字符串（会自动查今天）
"""

        tools = [add_schedule, query_schedules, delete_schedule, complete_schedule, set_recurring_schedule]
        self._graph = langchain_create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
        )

    def run(self, user_input: str) -> str:
        if not self._graph:
            raise RuntimeError("请先调用 initialize() 初始化！")

        try:
            result = self._graph.invoke(
                {"messages": [("user", user_input)]},
                stream_mode="values",
            )
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if hasattr(msg, "type") and msg.type == "ai" and msg.content:
                    return msg.content
            return "抱歉，我没有理解您的意思。"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"抱歉，出错了: {str(e)}"

    def clear_history(self) -> None:
        pass


def create_agent(api_key: str, model: str = "deepseek-ai/DeepSeek-V4-Flash") -> ScheduleAgent:
    """工厂函数：创建并初始化一个日程提醒 Agent。"""
    agent = ScheduleAgent()
    agent.initialize(api_key=api_key, model=model)
    return agent
