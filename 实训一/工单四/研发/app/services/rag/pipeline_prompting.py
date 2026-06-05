from __future__ import annotations

import json

from app.models.domain import SearchHit
from app.services.rag.pipeline_constants import _NON_CONTROL_TABLE_ROW_RE, _RELATION_TABLE_ROW_RE


class RagPromptMixin:
    def _system_prompt(self, intent: str) -> str:
        return (
            "你是企业知识库问答助手。"
            "必须严格只根据提供的知识库检索结果回答，不得使用外部知识。"
            "如果知识块中已经出现字段、标题、图表说明、表格行或可以直接支持答案的描述，优先直接抽取答案。"
            "只有在知识块确实无法支持结论时，才回答“未检索到充分依据”。"
            "涉及数值、比例、年份、项目名称时，尽量保留原文单位和限定条件。"
        )

    def _build_prompt(
        self,
        question: str,
        intent: str,
        hits: list[SearchHit],
        *,
        force_extract: bool = False,
        max_hits: int | None = None,
    ) -> str:
        context_blocks: list[str] = []
        used_chars = 0
        max_chars = self.settings.prompt_max_context_chars
        selected_hits = hits[:max_hits] if max_hits is not None else hits
        for index, hit in enumerate(selected_hits, start=1):
            remaining = max_chars - used_chars
            if remaining <= 160:
                break
            clipped_text = self._compress_hit_text(
                hit,
                question,
                min(self.settings.prompt_chunk_char_limit, remaining),
                full_preferred=index <= 3,
            )
            if not clipped_text:
                continue
            block = f"[知识块{index}]\n{clipped_text}"
            context_blocks.append(block)
            used_chars += len(block)

        context = "\n\n".join(context_blocks) if context_blocks else "无可用检索结果"
        instruction = (
            "请严格只根据上面的知识库检索结果作答。"
            "优先直接抽取能够支持答案的字段、标题、表格行、图表描述或结论性语句。"
            "不要因为知识块没有逐字重复问题就拒答，只要知识块可以支持答案就应作答。"
            "如果多个年份、项目、主体同时出现，按问题限定条件筛选。"
            "只有在知识块确实不能支持答案时，才回答“未检索到充分依据”。"
        )
        if force_extract:
            instruction = (
                "请执行证据抽取式回答："
                "先检查每个知识块中是否存在能直接支持答案的字段、标题、表格行、图表描述或比较结论；"
                "一旦找到，就直接给出答案，不要保守拒答；"
                "只有全部知识块都无法支持答案时，才回答“未检索到充分依据”。"
            )
        return (
            f"问题：{question}\n"
            f"\n知识库检索结果：\n{context}\n\n"
            f"{instruction}"
        )

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
        if (
            "表格：八、存在控制关系的关联方" not in text
            and "表格：九、不存在控制关系的关联方" not in text
        ):
            return text
        if "规范化行：" in text:
            return text

        normalized_lines: list[str] = []
        if "表格：八、存在控制关系的关联方" in text:
            for match in _RELATION_TABLE_ROW_RE.finditer(text):
                normalized_lines.append(
                    "规范化行："
                    f"关联方名称：{match.group('name')}，"
                    f"持股比例：{match.group('ratio')}，"
                    f"与本公司关系：{match.group('relation')}"
                )
        if "表格：九、不存在控制关系的关联方" in text:
            for match in _NON_CONTROL_TABLE_ROW_RE.finditer(text):
                normalized_lines.append(
                    "规范化行："
                    f"企业名称：{match.group('name')}，"
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
