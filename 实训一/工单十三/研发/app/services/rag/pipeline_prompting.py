from __future__ import annotations

import json

from app.models.domain import SearchHit
from app.services.rag.pipeline_constants import _NON_CONTROL_TABLE_ROW_RE, _RELATION_TABLE_ROW_RE


class RagPromptMixin:
    """提供 RAG 回答阶段的系统提示词、上下文压缩和引用封装逻辑。"""
    def _system_prompt(self, intent: str) -> str:
        """处理system提示词。"""
        return (
            "你是企业知识库问答助手，严格依据检索到的内容回答问题。\n"
            "【核心原则】\n"
            "1. 只使用检索内容中明确包含的信息，不要推测、扩展或引入未检索到的内容。\n"
            "2. 如果检索内容中没有直接支持答案的信息，必须回答\"未检索到充分依据\"，不要生硬拼凑无关内容。\n"
            "3. 严格区分语义相似但实际不同的概念，只引用与问题语义一致的内容。\n"
            "【概念对齐】\n"
            "注意理解问题中概念的等效表述：\n"
            "- \"拟投资\" = \"募集资金投资项目\" = \"募投项目\" = \"计划投资\"\n"
            "- \"已完成投资\" = \"实际投资\" = \"已投资\"\n"
            "- 当问题问\"拟投资\"时，检索内容中的\"募投项目\"即为答案\n"
            "【问题分析】\n"
            "回答前必须先识别问题中的：主体对象、时间范围、指标名称、条件限定、比较关系、具体子问题。\n"
            "【回答要求】\n"
            "1. 逐项对应问题中的每个要素，用检索内容中最匹配的证据作答。\n"
            "2. 保留原文中的数值、单位、年份、范围等关键信息。\n"
            "3. 多个子问/对象/条件时，按对应关系一一回答，不遗漏。\n"
            "4. 直接给出答案，不复述检索过程，不使用\"根据检索到...\"等表述。\n"
            "5. 答案中的每一个事实都必须能在检索内容中找到原文对应。\n"
        )

    def _build_prompt(
        self,
        question: str,
        intent: str,
        hits: list[SearchHit],
        history: list[dict[str, str]] | None = None,
        *,
        force_extract: bool = False,
        max_hits: int | None = None,
    ) -> str:
        """将问题、历史和命中上下文拼装为最终用户提示词。"""
        context_blocks: list[str] = []
        selected_hits = hits[:max_hits] if max_hits is not None else hits
        for hit in selected_hits:
            full_text = self._repair_known_table_text(hit.text.strip())
            if not full_text:
                continue
            block = f"资料片段：\n{full_text}"
            context_blocks.append(block)

        context = "\n\n".join(context_blocks) if context_blocks else "无可用检索结果"
        history_block = self._prompt_history_block(history)
        instruction = (
            "请围绕当前问题直接回答。\n"
            "【回答步骤】\n"
            "1. 先检查检索内容中是否包含能直接回答问题的信息。\n"
            "2. 如果有，用最匹配的内容作答；如果没有或信息不足，直接回答\"未检索到充分依据\"。\n"
            "3. 回答时要逐项对应问题中的主体、时间、条件、子问，不要遗漏。\n"
            "4. 多个子问/对象/条件时，按对应关系逐一回答。\n"
            "【概念对齐检查】\n"
            "检查问题中的概念是否与检索内容中等效：\n"
            "- \"拟投资\" 对应 \"募集资金投资项目\"、\"募投项目\"、\"计划投资\"\n"
            "- \"已完成投资\" 对应 \"实际投资\"、\"已投资\"\n"
            "如果问题是\"拟投资哪些项目\"，检索内容中列出的\"募投项目\"即为答案。\n"
            "【禁止事项】\n"
            "- 禁止使用检索内容之外的信息进行推测或补充。\n"
            "- 禁止将语义相似但含义不同的概念混用。\n"
            "- 禁止遗漏问题中的任何限定条件。\n"
            "- 禁止使用\"根据检索到...\"、\"从资料中可以看到...\"等复述性表述。\n"
        )
        if force_extract:
            instruction = (
                "请只提取能够直接支持当前问题答案的信息。\n"
                "【提取规则】\n"
                "1. 优先使用与问题语义最一致的证据。\n"
                "2. 先对照问题检查主体、指标、时间、范围、条件和子问是否齐全。\n"
                "3. 保留原有数值、单位、年份、对象和限定条件。\n"
                "4. 若没有足够证据，回答\"未检索到充分依据\"。\n"
                "【概念区分】\n"
                "只提取与问题语义完全匹配的内容：\n"
                "- 注意时间限定词的一致性\n"
                "- 注意状态词的一致性（已完成/计划中）\n"
                "- 注意指标名称的精确性\n"
                "【禁止事项】\n"
                "- 禁止引入检索内容之外的新信息。\n"
                "- 禁止将相近概念混用。\n"
            )
        prompt_parts: list[str] = []
        if history_block:
            prompt_parts.append(f"最近对话：\n{history_block}")
        prompt_parts.append(f"当前问题：{question}")
        prompt_parts.append(f"检索内容：\n{context}")
        prompt_parts.append(instruction)
        return "\n\n".join(prompt_parts)

    def _prompt_history_block(self, history: list[dict[str, str]] | None) -> str:
        """处理提示词历史记录块。"""
        if not history:
            return ""

        lines: list[str] = []
        used_chars = 0
        for item in history[-self.settings.answer_history_max_messages :]:
            role = str(item.get("role") or "").strip()
            text = " ".join(str(item.get("text") or "").split()).strip()
            if role not in {"user", "assistant"} or not text:
                continue
            label = "用户" if role == "user" else "助手"
            entry = f"{label}：{text[:320]}"
            if used_chars + len(entry) > 1600:
                break
            lines.append(entry)
            used_chars += len(entry)
        return "\n".join(lines)

    def _compress_hit_text(
        self,
        hit: SearchHit,
        question: str,
        limit: int,
        *,
        full_preferred: bool = False,
    ) -> str:
        """处理compress命中结果文本。"""
        text = self._repair_known_table_text(hit.text.strip())
        metadata = hit.metadata or {}
        content_type = str(metadata.get("type", "")).lower()

        if full_preferred or content_type in {"table", "image"}:
            if len(text) <= limit:
                return text
            return text[:limit].strip()

        if len(text) <= limit:
            return text

        terms = self._important_terms(question)
        terms.extend(self._question_focus_terms(question))
        anchor_title = self._evidence_anchor_title(question)
        if anchor_title:
            terms.append(anchor_title)

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) <= 1:
            return self._clip_around_terms(text, terms, limit)

        keep: list[str] = []
        for line in lines:
            is_context_line = line.startswith(
                (
                    "表格：",
                    "参考：",
                    "页码：",
                    "表头：",
                    "单位：",
                    "图片：",
                    "标题：",
                    "描述：",
                    "Caption:",
                    "Description:",
                    "Image caption:",
                    "Image type:",
                    "Type:",
                    "Page:",
                )
            )
            is_match_line = any(term and term in line for term in terms)
            if is_context_line or is_match_line:
                keep.append(line)

        compact = "\n".join(dict.fromkeys(keep))
        if compact and len(compact) <= limit:
            return compact
        if compact:
            return self._clip_around_terms(compact, terms, limit)
        return self._clip_around_terms(text, terms, limit)

    def _clip_around_terms(self, text: str, terms: list[str], limit: int) -> str:
        """截取around术语集合。"""
        if len(text) <= limit:
            return text.strip()

        positions = [text.find(term) for term in terms if term and text.find(term) >= 0]
        if not positions:
            return text[:limit].strip()

        anchor = min(positions)
        half = max(limit // 2, 80)
        start = max(anchor - half, 0)
        end = min(start + limit, len(text))
        start = max(end - limit, 0)
        clipped = text[start:end].strip()
        if start > 0:
            clipped = "..." + clipped
        if end < len(text):
            clipped = clipped + "..."
        return clipped

    def _repair_known_table_text(self, text: str) -> str:
        """修复known表格文本。"""
        relation_title = "表格：八、存在控制关系的关联方"
        non_control_title = "表格：九、不存在控制关系的关联方"
        normalized_row = "规范化行："

        if relation_title not in text and non_control_title not in text:
            return text
        if normalized_row in text:
            return text

        normalized_lines: list[str] = []
        if relation_title in text:
            for match in _RELATION_TABLE_ROW_RE.finditer(text):
                normalized_lines.append(
                    f"{normalized_row}"
                    f"关联方名称：{match.group('name')}；"
                    f"持股比例：{match.group('ratio')}；"
                    f"与本公司关系：{match.group('relation')}"
                )
        if non_control_title in text:
            for match in _NON_CONTROL_TABLE_ROW_RE.finditer(text):
                normalized_lines.append(
                    f"{normalized_row}"
                    f"企业名称：{match.group('name')}；"
                    f"与本公司关系：{match.group('relation')}"
                )
        if not normalized_lines:
            return text
        return text + "\n" + "\n".join(normalized_lines)

    def _reference_payload(self, hit: SearchHit) -> dict:
        """处理引用载荷负载数据。"""
        return {
            "chunk_id": hit.chunk_id,
            "doc_id": hit.doc_id,
            "page": hit.page,
            "page_end": hit.page_end,
            "score": hit.score,
            "source_file": hit.source_file,
            "text": hit.text,
            "metadata": hit.metadata,
        }

    def _empty_answer(
        self,
        intent_result: dict[str, str],
        embed_elapsed: float,
        search_elapsed: float,
        total_elapsed: float,
        query_variants: list[str] | None = None,
    ) -> dict:
        """处理empty回答。"""
        variants = query_variants or [intent_result["normalized_question"]]
        return {
            "normalized_question": intent_result["normalized_question"],
            "intent": intent_result["intent"],
            "query_variants": variants,
            "optimized_question": variants[1] if len(variants) > 1 else variants[0],
            "answer": "未检索到充分依据。",
            "references": [],
            "timing": {
                "embed_seconds": embed_elapsed,
                "search_seconds": search_elapsed,
                "llm_seconds": 0.0,
                "total_seconds": total_elapsed,
            },
        }

    def _sse_event(self, event: str, data: dict) -> str:
        """处理SSE 事件字符串event。"""
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
