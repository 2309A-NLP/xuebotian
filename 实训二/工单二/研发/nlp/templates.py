"""
对话模板管理
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

提供各种对话回复模板，支持多种风格
"""

import random
from typing import List, Optional


class ResponseTemplates:
    """对话响应模板"""

    # 添加日程成功
    ADD_SUCCESS = [
        "好的主人，已经帮您记录好日程啦：【{content}】在 {date} {time}。",
        "收到！我已经安排好了：{content}，时间是 {date} {time}。",
        "已记录！{date} {time} 的 {content} 事项已加入日程表。",
        "好的~ {content} 已安排在 {date} {time}，我会准时提醒您的！"
    ]

    # 添加循环日程成功
    ADD_RECURRENCE_SUCCESS = [
        "好的主人，已经帮您添加循环日程：【{content}】{recurrence_text} {time}。",
        "收到！已设置 {content} {recurrence_text} {time}，我会按时提醒您的！",
        "已记录！{content} {recurrence_text} {time} 已加入日程表。"
    ]

    # 删除日程成功
    DELETE_SUCCESS = [
        "已经删除日程 {id}，删除的日程内容是：{time} {content}",
        "好的，已经帮您取消了这个日程：{time} {content}",
        "已删除！{content} 已从日程表中移除。",
        "日程 {id} 已取消，该事项是 {time} 的 {content}。"
    ]

    # 删除日程不存在
    DELETE_NOT_FOUND = [
        "抱歉，主人，没有找到日程 {id}，请您确认一下编号是否正确呢？",
        "找不到日程 {id}哦，可能是已经删除或者编号有误~",
        "主人，日程 {id} 不存在呢，您可以用「我今天的日程有哪些」来查看所有日程。"
    ]

    # 查询日程
    QUERY_RESULT = [
        "主人，您今天有以下日程：",
        "好的，这是今天的日程安排：",
        "让我看看...您今天的日程有这些："
    ]

    # 查询结果为空
    QUERY_EMPTY = [
        "主人，今天暂时没有安排任何日程，好好休息一下吧~",
        "今天没有日程哦，主人可以放松一下！",
        "暂无日程安排，主人今天想做什么呢？"
    ]

    # 日程列表格式
    SCHEDULE_LIST_ITEM = "{id}: {time} - {content}"

    # 修改日程成功
    UPDATE_SUCCESS = [
        "好的主人，已经帮您修改日程 {id} 了。",
        "已更新！日程 {id} 的信息已修改。",
        "修改成功！"
    ]

    # 完成日程成功
    COMPLETE_SUCCESS = [
        "太棒了！{content} 已完成，主人真厉害！",
        "收到！{content} 已标记为完成~",
        "已完成！主人加油哦~"
    ]

    # 帮助信息
    HELP = """
日程提醒智能体使用指南：

📝 添加日程：
   "添加日程：明天上午9点开会"
   "安排下午3点去健身房"

📋 查询日程：
   "我今天的日程有哪些？"
   "查看明天的安排"

❌ 删除日程：
   "删除日程1"
   "取消第2个日程"

✅ 完成日程：
   "完成日程1"
   "我已经做完第3个了"

🔄 循环日程：
   "每天早上8点提醒我喝水"
   "每周一上午9点开会"

💡 提示：您可以用自然语言跟我交流，我会尽力理解您的意思！
"""

    # 温馨提醒模板
    REMINDER = [
        "提醒您：{content}",
        "{content}的时间到啦！",
        "主人，该{content}了哦~",
    ]

    # 模糊输入的澄清
    CLARIFICATION_TIME = "请问您想安排在什么时间呢？"
    CLARIFICATION_CONTENT = "请问需要提醒您做什么呢？"
    CLARIFICATION_DATE = "请问是哪一天呢？（今天/明天/后天/具体日期）"
    CLARIFICATION_BOTH = "请问您想安排在什么时间，以及需要做什么呢？"

    # 错误回复
    ERROR = [
        "抱歉主人，我没有理解您的意思，请重新描述一下可以吗？",
        "这个有点难倒我了，能换个说法吗？",
        "我有点困惑，您能说得更清楚一点吗？"
    ]


class ResponseGenerator:
    """响应生成器"""

    def __init__(self):
        self.templates = ResponseTemplates()

    def generate(self, template_type: str, **kwargs) -> str:
        """生成响应文本"""
        templates = getattr(self.templates, template_type, self.templates.ERROR)
        if isinstance(templates, list):
            template = random.choice(templates)
        else:
            template = templates

        try:
            return template.format(**kwargs)
        except KeyError:
            return random.choice(self.templates.ERROR)

    def format_schedule_list(self, schedules: List[dict], date: Optional[str] = None) -> str:
        """格式化日程列表"""
        if not schedules:
            return self.generate("QUERY_EMPTY")

        lines = [self.generate("QUERY_RESULT")]

        for idx, schedule in enumerate(schedules, 1):
            item = self.templates.SCHEDULE_LIST_ITEM.format(
                id=idx,
                time=schedule.get('schedule_time', ''),
                content=schedule.get('content', '')
            )
            lines.append(item)

        # 添加总计
        total = len(schedules)
        lines.append(f"\n共 {total} 个日程")

        return "\n".join(lines)

    def format_reminder(self, content: str) -> str:
        """生成温馨提醒"""
        return self.generate("REMINDER", content=content)

    def get_clarification(self, needs_time: bool = False, needs_content: bool = False,
                         needs_date: bool = False) -> str:
        """获取澄清问题"""
        if needs_time and needs_content:
            return self.templates.CLARIFICATION_BOTH
        elif needs_time:
            return self.templates.CLARIFICATION_TIME
        elif needs_content:
            return self.templates.CLARIFICATION_CONTENT
        elif needs_date:
            return self.templates.CLARIFICATION_DATE
        return ""

    def get_recurrence_text(self, recurrence: str) -> str:
        """获取循环类型的文字描述"""
        recurrence_map = {
            "daily": "每天",
            "weekly": "每周",
            "monthly": "每月",
            "workday": "每个工作日"
        }
        return recurrence_map.get(recurrence, "")


# 全局响应生成器实例
response_generator = ResponseGenerator()


def get_response_generator() -> ResponseGenerator:
    """获取响应生成器"""
    return response_generator
