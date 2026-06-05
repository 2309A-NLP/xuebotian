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
    "增长率",
    "收入",
    "利润",
)


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
            "帮我看看": "",
            "请问": "",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\s+", " ", text).strip()
        return text or question.strip()

    def _classify(self, question: str) -> str:
        if any(keyword in question for keyword in _VISUAL_KEYWORDS):
            return "visual_lookup"
        if any(keyword in question for keyword in _TABLE_KEYWORDS):
            return "table_lookup"
        if any(keyword in question for keyword in ("总结", "概括", "摘要")):
            return "summarization"
        if any(keyword in question for keyword in ("定义", "是什么", "含义")):
            return "definition"
        return "qa"
