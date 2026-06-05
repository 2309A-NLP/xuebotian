from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator

from app.core.config import Settings
from app.models.domain import SearchHit
from app.services.intent.analyzer import IntentAnalyzer
from app.services.llm.client import OpenAICompatibleLLMClient
from app.services.vector.embedder import BgeM3Embedder
from app.services.vector.milvus_store import BaseVectorStore

logger = logging.getLogger(__name__)


class RagPipeline:
    def __init__(
        self,
        settings: Settings,
        intent_analyzer: IntentAnalyzer,
        embedder: BgeM3Embedder,
        vector_store: BaseVectorStore,
        llm_client: OpenAICompatibleLLMClient,
    ) -> None:
        self.settings = settings
        self.intent_analyzer = intent_analyzer
        self.embedder = embedder
        self.vector_store = vector_store
        self.llm_client = llm_client

    def answer(
        self,
        question: str,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> dict:
        started_at = time.perf_counter()
        intent_result = self.intent_analyzer.analyze(question)

        embed_started = time.perf_counter()
        query_vector = self.embedder.embed_query(intent_result["normalized_question"])
        embed_elapsed = time.perf_counter() - embed_started

        search_started = time.perf_counter()
        hits = self.vector_store.search(
            embedding=query_vector,
            top_k=top_k or self.settings.top_k,
            doc_ids=doc_ids,
        )
        search_elapsed = time.perf_counter() - search_started

        prompt = self._build_prompt(
            intent_result["normalized_question"],
            intent_result["intent"],
            hits,
        )

        llm_started = time.perf_counter()
        answer = self.llm_client.chat(
            system_prompt=self._system_prompt(intent_result["intent"]),
            user_prompt=prompt,
        )
        llm_elapsed = time.perf_counter() - llm_started
        total_elapsed = time.perf_counter() - started_at

        logger.info(
            "QA timing | embed=%.3fs search=%.3fs llm=%.3fs total=%.3fs hits=%s question=%s",
            embed_elapsed,
            search_elapsed,
            llm_elapsed,
            total_elapsed,
            len(hits),
            intent_result["normalized_question"],
        )

        return {
            "normalized_question": intent_result["normalized_question"],
            "intent": intent_result["intent"],
            "answer": answer.strip(),
            "references": hits,
            "timing": {
                "embed_seconds": embed_elapsed,
                "search_seconds": search_elapsed,
                "llm_seconds": llm_elapsed,
                "total_seconds": total_elapsed,
            },
        }

    def stream_answer(
        self,
        question: str,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> Iterator[str]:
        started_at = time.perf_counter()
        intent_result = self.intent_analyzer.analyze(question)

        embed_started = time.perf_counter()
        query_vector = self.embedder.embed_query(intent_result["normalized_question"])
        embed_elapsed = time.perf_counter() - embed_started

        search_started = time.perf_counter()
        hits = self.vector_store.search(
            embedding=query_vector,
            top_k=top_k or self.settings.top_k,
            doc_ids=doc_ids,
        )
        search_elapsed = time.perf_counter() - search_started

        yield self._sse_event(
            "meta",
            {
                "normalized_question": intent_result["normalized_question"],
                "intent": intent_result["intent"],
                "references": [self._reference_payload(hit) for hit in hits],
                "timing": {
                    "embed_seconds": embed_elapsed,
                    "search_seconds": search_elapsed,
                },
            },
        )

        prompt = self._build_prompt(
            intent_result["normalized_question"],
            intent_result["intent"],
            hits,
        )

        llm_started = time.perf_counter()
        answer_parts: list[str] = []
        pending_parts: list[str] = []
        last_emit_at = time.perf_counter()
        for token in self.llm_client.stream_chat(
            system_prompt=self._system_prompt(intent_result["intent"]),
            user_prompt=prompt,
        ):
            answer_parts.append(token)
            pending_parts.append(token)

            pending_text = "".join(pending_parts)
            now = time.perf_counter()
            reached_char_threshold = (
                len(pending_text) >= self.settings.stream_emit_char_threshold
            )
            reached_time_threshold = (
                (now - last_emit_at) * 1000 >= self.settings.stream_emit_interval_ms
            )
            sentence_boundary = token.endswith((".", "。", "!", "！", "?", "？", "\n"))

            if reached_char_threshold or reached_time_threshold or sentence_boundary:
                yield self._sse_event("token", {"delta": pending_text})
                pending_parts.clear()
                last_emit_at = now

        if pending_parts:
            yield self._sse_event("token", {"delta": "".join(pending_parts)})

        llm_elapsed = time.perf_counter() - llm_started
        total_elapsed = time.perf_counter() - started_at
        logger.info(
            "QA stream timing | embed=%.3fs search=%.3fs llm=%.3fs total=%.3fs hits=%s question=%s",
            embed_elapsed,
            search_elapsed,
            llm_elapsed,
            total_elapsed,
            len(hits),
            intent_result["normalized_question"],
        )
        yield self._sse_event(
            "done",
            {
                "answer": "".join(answer_parts).strip(),
                "timing": {
                    "embed_seconds": embed_elapsed,
                    "search_seconds": search_elapsed,
                    "llm_seconds": llm_elapsed,
                    "total_seconds": total_elapsed,
                },
            },
        )

    def _system_prompt(self, intent: str) -> str:
        return (
            "你是企业知识库问答助手。"
            "必须严格基于提供的文档片段回答。"
            "回答应准确、简洁、避免编造。"
            "若证据不足，请明确说明。"
            f"当前任务类型：{intent}。"
        )

    def _build_prompt(self, question: str, intent: str, hits: list[SearchHit]) -> str:
        context_blocks = []
        for index, hit in enumerate(hits, start=1):
            clipped_text = hit.text[: self.settings.prompt_chunk_char_limit].strip()
            context_blocks.append(
                f"[片段{index}] 文档={hit.source_file} 页码={hit.page} 相似度={hit.score:.4f}\n{clipped_text}"
            )
        context = "\n\n".join(context_blocks) if context_blocks else "无可用检索结果"
        return (
            f"问题：{question}\n"
            f"意图：{intent}\n\n"
            f"参考内容：\n{context}\n\n"
            "请输出最终答案；如果参考内容不足以支持结论，直接说明未检索到充分依据。"
        )

    def _reference_payload(self, hit: SearchHit) -> dict:
        return {
            "chunk_id": hit.chunk_id,
            "doc_id": hit.doc_id,
            "page": hit.page,
            "score": hit.score,
            "source_file": hit.source_file,
            "text": hit.text[: self.settings.prompt_chunk_char_limit],
        }

    def _sse_event(self, event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
