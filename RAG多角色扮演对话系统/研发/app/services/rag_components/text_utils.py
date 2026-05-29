import re
from typing import List


class RAGTextUtilsMixin:

    def _normalize_match_text(self, text: str) -> str:
        return re.sub(r"\s+", "", (text or "").strip().lower())

    def _clean_generated_text(self, text: str) -> str:

        cleaned = (text or "").replace("\ufeff", "").replace("\u0000", "")

        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _has_garbled_text(self, text: str) -> bool:
        cleaned = self._clean_generated_text(text)
        if not cleaned:
            return True

        if "\ufffd" in cleaned:
            return True

        suspicious_fragments = (
            "閿",
            "閵",
            "閳",
            "閹存垶",
            "娴ｇ姷",
            "閺嶈",
            "閻滅増",
            "閺冪姵",
            "閻儴",
            "闂傤噣",
            "閸ョ偟",
            "閺堝",
            "娑撯偓",
        )
        if any(fragment in cleaned for fragment in suspicious_fragments):
            return True

        suspicious_chars = set("閿涢妴閳ラ幋娴ｉ惃閺勯崷閸氶崚鏉╃紒閻拠闂傞弮鐡掔涵")

        suspicious_count = sum(1 for char in cleaned if char in suspicious_chars)

        cjk_count = sum(1 for char in cleaned if "\u4e00" <= char <= "\u9fff")

        return (
            cjk_count >= 8
            and suspicious_count >= 6
            and (suspicious_count / max(1, cjk_count)) >= 0.2
        )

    def _tokenize_text(self, text: str) -> List[str]:
        if not text:
            return []

        tokens = self.vector_store._tokenize(text)
        deduplicated: List[str] = []
        seen = set()
        for token in tokens:
            normalized = token.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(normalized)
        return deduplicated

    def _contains_history_reference(self, query: str) -> bool:
        normalized = (query or "").strip().lower()
        if not normalized:
            return False
        if re.search(
            r"\b(he|she|it|they|them|him|her|that|this|those|these|former|latter)\b",
            normalized,
        ):
            return True
        markers = (
            "刚才",
            "之前",
            "上次",
            "前面",
            "后面",
            "后来",
            "那个",
            "这个",
            "那件事",
            "这件事",
            "他",
            "她",
            "它",
            "他们",
            "她们",
            "它们",
            "继续",
            "接着",
            "再说",
            "还有",
        )
        return any(marker in normalized for marker in markers)

    def _is_fact_seeking_query(self, query: str) -> bool:
        normalized = (query or "").strip().lower()
        if not normalized:
            return False
        chinese_markers = (
            "谁",
            "什么",
            "哪位",
            "哪个",
            "哪里",
            "何时",
            "多久",
            "多少",
            "为什么",
            "如何",
            "介绍",
            "简介",
            "生平",
            "背景",
            "资料",
            "身份",
            "关系",
            "结局",
            "是不是",
            "是否",
            "请问",
        )
        if "?" in normalized or "\uff1f" in normalized:
            return True
        if any(marker in normalized for marker in chinese_markers):
            return True
        return bool(
            re.search(
                r"\b(who|what|when|where|why|how|which|introduce|profile|background|ending|relationship)\b",
                normalized,
            )
        )

    def _is_identity_query(self, query: str) -> bool:
        normalized = (query or "").strip().lower()
        if not normalized:
            return False
        markers = ("你是谁", "你叫什么", "你的名字", "阁下是谁", "如何称呼你")
        return any(marker in normalized for marker in markers) or bool(
            re.search(r"\b(who are you|your name)\b", normalized)
        )
