from __future__ import annotations

import re

_VISUAL_KEYWORDS = (
    "图中",
    "图里",
    "图上",
    "图表",
    "图片",
    "配图",
    "曲线",
    "柱状图",
    "折线图",
    "饼图",
    "趋势图",
    "增长图",
    "示意图",
    "流程图",
    "结构图",
)

_TABLE_KEYWORDS = (
    "表格",
    "表中",
    "表内",
    "表里",
    "数据",
    "统计",
    "数值",
    "金额",
    "比例",
    "占比",
    "增长率",
    "股数",
    "总股本",
    "持股",
    "发行",
    "募投",
    "收入",
    "利润",
    "成本",
    "费用",
)

_FIELD_LOOKUP_KEYWORDS = (
    "多少",
    "几",
    "几家",
    "几次",
    "数额",
    "金额",
    "数值",
    "比例",
    "占比",
    "比率",
    "股数",
    "总股本",
    "募资",
    "募投",
    "收入",
    "利润",
    "成本",
    "费用",
    "均价",
    "价格",
    "日期",
    "时间",
)

_SUMMARY_KEYWORDS = ("总结", "概括", "摘要")
_DEFINITION_KEYWORDS = ("定义", "是什么", "含义")


class IntentAnalyzer:
    def analyze(self, question: str) -> dict[str, str]:
        normalized = self._normalize(question)
        intent = self._classify(normalized)
        return {
            "normalized_question": normalized,
            "intent": intent,
        }

    def _normalize(self, question: str) -> str:
        text = question.strip()
        replacements = {
            "这个": "",
            "那个": "",
            "这个问题": "",
            "那个问题": "",
            "帮我看看": "",
            "请问": "",
            "麻烦问一下": "",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\s+", " ", text).strip()
        return text or question.strip()

    def _classify(self, question: str) -> str:
        if any(keyword in question for keyword in _VISUAL_KEYWORDS):
            return "visual_lookup"
        if self._is_table_lookup(question):
            return "table_lookup"
        if any(keyword in question for keyword in _SUMMARY_KEYWORDS):
            return "summarization"
        if any(keyword in question for keyword in _DEFINITION_KEYWORDS):
            return "definition"
        return "qa"

    def _is_table_lookup(self, question: str) -> bool:
        if any(keyword in question for keyword in _TABLE_KEYWORDS):
            return True
        return any(keyword in question for keyword in _FIELD_LOOKUP_KEYWORDS) and any(
            token in question
            for token in ("多少", "几", "金额", "比例", "占比", "股数", "总股本", "收入", "利润")
        )
