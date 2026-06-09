from __future__ import annotations

import json

from app.models.domain import SearchHit
from app.services.rag.pipeline_constants import _NON_CONTROL_TABLE_ROW_RE, _RELATION_TABLE_ROW_RE


class RagPromptMixin:
    def _system_prompt(self, intent: str) -> str:
        return (
            "你是企业知识库问答助手。"
            "只依据当前问题、检索内容和最近对话回答，不使用外部知识。"
            "以当前问题为准，最近对话只用于补足指代、省略和上下文。"
            "先理解问题真正要问的主体、指标、时间、范围和条件，再从检索内容中选用最匹配的证据作答。"
            "回答要完整，不要遗漏问题中的任何关键信息、限定条件、比较关系或子问题。"
            "相近但不相同的概念必须严格区分，只能使用与问题语义一致的内容，忽略无关或易混淆的信息。"
            "直接回答，不要复述检索过程；保留原文中的数值、单位、年份、对象、范围和条件。"
            "如果证据不足，回答“未检索到充分依据”。"
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
            "请围绕当前问题直接回答。"
            "结合最近对话补足指代，结合检索内容选择最匹配、最直接的证据。"
            "先检查问题里有哪些主体、指标、时间、范围、条件、比较关系和子问，再逐项答全。"
            "只回答问题要求的内容；相近但不一致的内容不要混用，也不要漏掉问题里的限定信息。"
            "如果有多个子问、多个年份、多个对象或多个条件，按对应关系逐项回答完整。"
            "回答时保留原文中的关键数值、单位、年份和限定条件，不要补充检索内容之外的新事实。"
            "如果检索内容不足以支持答案，回答“未检索到充分依据”。"
        )
        if force_extract:
            instruction = (
                "请只提取能够直接支持当前问题答案的信息。"
                "优先使用与问题语义最一致的证据，忽略无关或易混淆的内容。"
                "先对照问题检查主体、指标、时间、范围、条件和子问是否齐全，再逐项对应回答，不要漏项。"
                "保留原有数值、单位、年份、对象和限定条件，不要引入检索内容之外的新信息。"
                "若没有足够证据，回答“未检索到充分依据”。"
            )
        prompt_parts: list[str] = []
        if history_block:
            prompt_parts.append(f"最近对话：\n{history_block}")
        prompt_parts.append(f"当前问题：{question}")
        prompt_parts.append(f"检索内容：\n{context}")
        prompt_parts.append(instruction)
        return "\n\n".join(prompt_parts)

    def _prompt_history_block(self, history: list[dict[str, str]] | None) -> str:
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
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
