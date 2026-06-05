from __future__ import annotations

import re


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
        if any(keyword in question for keyword in ["表格", "数据", "统计", "数值"]):
            return "table_lookup"
        if any(keyword in question for keyword in ["总结", "概括", "摘要"]):
            return "summarization"
        if any(keyword in question for keyword in ["定义", "是什么", "含义"]):
            return "definition"
        return "qa"
