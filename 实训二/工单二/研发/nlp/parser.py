"""
自然语言解析器
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

功能：
1. 解析用户输入的自然语言命令
2. 识别意图（添加、删除、查询、修改日程）
3. 提取时间、内容等信息
4. 处理模糊、口语化的表达
"""

import re
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from enum import Enum


class Intent(Enum):
    """用户意图枚举"""
    ADD = "add"              # 添加日程
    DELETE = "delete"        # 删除日程
    UPDATE = "update"        # 修改日程
    QUERY = "query"          # 查询日程
    COMPLETE = "complete"    # 完成日程
    HELP = "help"            # 帮助
    UNKNOWN = "unknown"      # 未知


@dataclass
class ParsedCommand:
    """解析后的命令"""
    intent: Intent
    content: str = ""           # 日程内容
    schedule_date: Optional[str] = None  # 日期 (YYYY-MM-DD)
    schedule_time: Optional[str] = None  # 时间 (HH:MM)
    recurrence: str = "none"     # 循环类型
    schedule_id: Optional[int] = None   # 日程ID
    raw_input: str = ""          # 原始输入
    clarification_needed: List[str] = field(default_factory=list)  # 需要澄清的信息


class NLPParser:
    """
    自然语言解析器
    支持口语化、模糊的输入表达
    """

    def __init__(self):
        # 时间关键词
        self.time_keywords = {
            '早': 'morning',
            '上午': 'morning',
            '中午': 'noon',
            '下午': 'afternoon',
            '晚上': 'evening',
            '傍晚': 'evening',
            '深夜': 'night'
        }

        # 循环关键词映射
        self.recurrence_keywords = {
            '每天': 'daily',
            '每日': 'daily',
            '天天': 'daily',
            '每天': 'daily',
            '每周': 'weekly',
            '每周': 'weekly',
            '每周': 'weekly',
            '每月': 'monthly',
            '每月': 'monthly',
            '工作日': 'workday',
            '周一到周五': 'workday'
        }

        # 意图关键词
        self.intent_keywords = {
            Intent.ADD: ['添加', '新增', '加入', '创建', '安排', '加', '记'],
            Intent.DELETE: ['删除', '取消', '移除', '去掉', '删', '去掉'],
            Intent.UPDATE: ['修改', '更新', '改', '编辑', '调整'],
            Intent.QUERY: ['查询', '查看', '看', '有什么', '有哪些', '今天的日程', '日程有哪些', '日程表'],
            Intent.COMPLETE: ['完成', '做完了', '搞定了', '已办', '结束']
        }

    def parse(self, user_input: str) -> ParsedCommand:
        """
        解析用户输入
        """
        user_input = user_input.strip()
        if not user_input:
            return ParsedCommand(intent=Intent.UNKNOWN, raw_input=user_input)

        # 检测意图
        intent = self._detect_intent(user_input)

        # 根据意图解析不同部分
        if intent == Intent.ADD:
            return self._parse_add(user_input)
        elif intent == Intent.DELETE:
            return self._parse_delete(user_input)
        elif intent == Intent.UPDATE:
            return self._parse_update(user_input)
        elif intent == Intent.QUERY:
            return self._parse_query(user_input)
        elif intent == Intent.COMPLETE:
            return self._parse_complete(user_input)
        else:
            return ParsedCommand(intent=Intent.UNKNOWN, raw_input=user_input)

    def _detect_intent(self, text: str) -> Intent:
        """检测用户意图"""
        text_lower = text.lower()

        for intent, keywords in self.intent_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return intent

        # 默认按添加处理（如果包含时间）
        if self._contains_time(text):
            return Intent.ADD

        return Intent.UNKNOWN

    def _contains_time(self, text: str) -> bool:
        """检查是否包含时间信息"""
        time_patterns = [
            r'\d{1,2}:\d{2}',           # 14:30
            r'\d{1,2}点\d{0,2}',          # 14点30 / 14点
            r'\d{1,2}时\d{0,2}',          # 14时30 / 14时
            r'早[上中下]?[晨午晚]',        # 早上、中午、下午、晚上
            r'今[天日]',                  # 今天
            r'明[天日]',                  # 明天
            r'后[天日]'                   # 后天
        ]

        for pattern in time_patterns:
            if re.search(pattern, text):
                return True
        return False

    def _parse_add(self, text: str) -> ParsedCommand:
        """解析添加日程命令"""
        result = ParsedCommand(intent=Intent.ADD, raw_input=text)

        # 提取时间
        date_str, time_str = self._extract_time(text)
        result.schedule_date = date_str
        result.schedule_time = time_str

        # 提取循环规则
        recurrence = self._extract_recurrence(text)
        result.recurrence = recurrence

        # 提取内容（去除时间和关键词）
        content = self._extract_content(text, ['添加', '新增', '加入', '创建', '安排', '加', '记', '日程', '：', ':'])
        result.content = content

        # 检查是否需要澄清
        if not result.schedule_time:
            result.clarification_needed.append("时间")
        if not result.content:
            result.clarification_needed.append("日程内容")

        return result

    def _parse_delete(self, text: str) -> ParsedCommand:
        """解析删除日程命令"""
        result = ParsedCommand(intent=Intent.DELETE, raw_input=text)

        # 提取日程ID
        schedule_id = self._extract_id(text)
        result.schedule_id = schedule_id

        if not schedule_id:
            # 尝试提取日程内容来定位
            content = self._extract_content(text, ['删除', '取消', '移除', '去掉', '删', '日程', '：', ':'])
            result.content = content

        return result

    def _parse_update(self, text: str) -> ParsedCommand:
        """解析修改日程命令"""
        result = ParsedCommand(intent=Intent.UPDATE, raw_input=text)

        # 提取日程ID
        schedule_id = self._extract_id(text)
        result.schedule_id = schedule_id

        # 提取新时间
        date_str, time_str = self._extract_time(text)
        result.schedule_date = date_str
        result.schedule_time = time_str

        # 提取新内容
        content = self._extract_content(text, ['修改', '更新', '改', '编辑', '调整', '：', ':'])
        result.content = content

        return result

    def _parse_query(self, text: str) -> ParsedCommand:
        """解析查询日程命令"""
        result = ParsedCommand(intent=Intent.QUERY, raw_input=text)

        # 确定查询范围
        if '今天' in text or '今日' in text:
            result.schedule_date = date.today().strftime("%Y-%m-%d")
        elif '明天' in text or '明日' in text:
            tomorrow = date.today() + timedelta(days=1)
            result.schedule_date = tomorrow.strftime("%Y-%m-%d")
        elif '后天' in text or '后日' in text:
            day_after = date.today() + timedelta(days=2)
            result.schedule_date = day_after.strftime("%Y-%m-%d")
        elif '本周' in text:
            # 本周一的日期
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            result.schedule_date = monday.strftime("%Y-%m-%d")

        return result

    def _parse_complete(self, text: str) -> ParsedCommand:
        """解析完成日程命令"""
        result = ParsedCommand(intent=Intent.COMPLETE, raw_input=text)

        # 提取日程ID
        schedule_id = self._extract_id(text)
        result.schedule_id = schedule_id

        if not schedule_id:
            content = self._extract_content(text, ['完成', '做完了', '搞定了', '已办', '结束'])
            result.content = content

        return result

    def _extract_time(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """提取日期和时间"""
        date_str = None
        time_str = None

        # 提取具体时间 14:30 或 14点30
        time_patterns = [
            (r'(\d{1,2}):(\d{2})', '%H:%M'),   # 14:30
            (r'(\d{1,2})点(\d{1,2})?分?', '%H:%M'),  # 14点30分 / 14点
            (r'(\d{1,2})时(\d{1,2})?分?', '%H:%M')   # 14时30分 / 14时
        ]

        for pattern, fmt in time_patterns:
            match = re.search(pattern, text)
            if match:
                if len(match.groups()) >= 2 and match.group(2):
                    time_str = f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
                else:
                    # 只有小时，默认为整点
                    time_str = f"{int(match.group(1)):02d}:00"
                break

        # 提取日期
        if '今天' in text or '今日' in text:
            date_str = date.today().strftime("%Y-%m-%d")
        elif '明天' in text or '明日' in text:
            tomorrow = date.today() + timedelta(days=1)
            date_str = tomorrow.strftime("%Y-%m-%d")
        elif '后天' in text or '后日' in text:
            day_after = date.today() + timedelta(days=2)
            date_str = day_after.strftime("%Y-%m-%d")
        elif '大后天' in text:
            day_after = date.today() + timedelta(days=3)
            date_str = day_after.strftime("%Y-%m-%d")
        elif re.search(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', text):
            # 明确日期 2025-01-15
            match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', text)
            if match:
                date_str = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

        # 如果没有指定日期，默认今天
        if date_str is None:
            date_str = date.today().strftime("%Y-%m-%d")

        return date_str, time_str

    def _extract_recurrence(self, text: str) -> str:
        """提取循环规则"""
        for keyword, recurrence in self.recurrence_keywords.items():
            if keyword in text:
                return recurrence
        return "none"

    def _extract_id(self, text: str) -> Optional[int]:
        """提取日程ID"""
        # 匹配 "日程1" 或 "1" 形式的ID
        patterns = [
            r'日程\s*(\d+)',
            r'第\s*(\d+)\s*个',
            r'^(\d+)$',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None

    def _extract_content(self, text: str, remove_keywords: List[str]) -> str:
        """提取日程内容"""
        content = text

        # 移除关键词
        for keyword in remove_keywords:
            content = content.replace(keyword, ' ')

        # 清理多余空格
        content = ' '.join(content.split())

        return content.strip()

    def generate_clarification(self, parsed: ParsedCommand) -> str:
        """生成澄清问题"""
        if not parsed.clarification_needed:
            return ""

        questions = []
        if "时间" in parsed.clarification_needed:
            questions.append("请问您想安排在什么时间呢？")
        if "日程内容" in parsed.clarification_needed:
            questions.append("请问需要提醒您做什么呢？")

        return " ".join(questions)


# 全局解析器实例
nlp_parser = NLPParser()


def get_parser() -> NLPParser:
    """获取NLP解析器"""
    return nlp_parser
