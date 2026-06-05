from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator

from app.core.config import Settings
from app.services.intent.analyzer import IntentAnalyzer
from app.services.llm.client import OpenAICompatibleLLMClient
from app.services.rag.pipeline_constants import INSUFFICIENT_EVIDENCE_PHRASES
from app.services.rag.pipeline_prompting import RagPromptMixin
from app.services.rag.pipeline_query import RagQueryMixin
from app.services.rag.pipeline_ranking import RagRankingMixin
from app.services.rag.pipeline_retrieval import RagRetrievalMixin
from app.services.rag.reranker import BgeReranker
from app.services.vector.embedder import BgeM3Embedder
from app.services.vector.milvus_store import BaseVectorStore

logger = logging.getLogger(__name__)

class RagPipeline(
    RagRetrievalMixin,
    RagQueryMixin,
    RagRankingMixin,
    RagPromptMixin,
):
    def __init__(
        self,
        settings: Settings,
        intent_analyzer: IntentAnalyzer,
        embedder: BgeM3Embedder,
        vector_store: BaseVectorStore,
        reranker: BgeReranker,
        llm_client: OpenAICompatibleLLMClient,
    ) -> None:
        self.settings = settings
        self.intent_analyzer = intent_analyzer
        self.embedder = embedder
        self.vector_store = vector_store
        self.reranker = reranker
        self.llm_client = llm_client

    def answer(
        self,
        question: str,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> dict:
        started_at = time.perf_counter()
        intent_result = self.intent_analyzer.analyze(question)
        target_top_k = top_k or self.settings.top_k

        embed_started = time.perf_counter()
        query_variants = self._query_variants(intent_result["normalized_question"])
        query_vectors = self.embedder.embed_queries(query_variants)
        embed_elapsed = time.perf_counter() - embed_started

        search_started = time.perf_counter()
        hits = self._search(
            query_vectors=query_vectors,
            query_variants=query_variants,
            question=intent_result["normalized_question"],
            intent=intent_result["intent"],
            target_top_k=target_top_k,
            doc_ids=doc_ids,
        )
        search_elapsed = time.perf_counter() - search_started

        if not hits:
            total_elapsed = time.perf_counter() - started_at
            return self._empty_answer(
                intent_result,
                embed_elapsed,
                search_elapsed,
                total_elapsed,
                query_variants,
            )

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

        extraction_llm_elapsed = 0.0
        fallback_search_elapsed = 0.0
        fallback_llm_elapsed = 0.0
        used_fallback = False
        used_extraction_fallback = False
        if self._needs_original_question_retry(answer) and hits:
            extraction_started = time.perf_counter()
            extraction_answer = self.llm_client.chat(
                system_prompt=self._system_prompt(intent_result["intent"]),
                user_prompt=self._build_prompt(
                    intent_result["normalized_question"],
                    intent_result["intent"],
                    hits,
                    force_extract=True,
                    max_hits=min(3, len(hits)),
                ),
            )
            extraction_llm_elapsed = time.perf_counter() - extraction_started
            if not self._needs_original_question_retry(extraction_answer):
                answer = extraction_answer
                used_extraction_fallback = True

        if self._needs_original_question_retry(answer):
            retry_result = self._retry_with_original_question(
                question=question,
                intent_result=intent_result,
                target_top_k=target_top_k,
                doc_ids=doc_ids,
            )
            fallback_search_elapsed = retry_result["search_elapsed"]
            fallback_llm_elapsed = retry_result["llm_elapsed"]
            if retry_result["hits"]:
                answer = retry_result["answer"]
                hits = retry_result["hits"]
                query_variants = retry_result["query_variants"]
                used_fallback = True
        total_elapsed = time.perf_counter() - started_at

        logger.info(
            "QA timing | embed=%.3fs search=%.3fs llm=%.3fs retry_search=%.3fs retry_llm=%.3fs total=%.3fs hits=%s variants=%s fallback=%s question=%s",
            embed_elapsed,
            search_elapsed,
            llm_elapsed + extraction_llm_elapsed,
            fallback_search_elapsed,
            fallback_llm_elapsed,
            total_elapsed,
            len(hits),
            len(query_variants),
            used_fallback or used_extraction_fallback,
            intent_result["normalized_question"],
        )

        return {
            "normalized_question": intent_result["normalized_question"],
            "intent": intent_result["intent"],
            "query_variants": query_variants,
            "optimized_question": query_variants[1] if len(query_variants) > 1 else query_variants[0],
            "answer": answer.strip(),
            "references": hits,
            "timing": {
                "embed_seconds": embed_elapsed,
                "search_seconds": search_elapsed + fallback_search_elapsed,
                "llm_seconds": llm_elapsed + extraction_llm_elapsed + fallback_llm_elapsed,
                "total_seconds": total_elapsed,
                "fallback_used": used_fallback or used_extraction_fallback,
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
        target_top_k = top_k or self.settings.top_k

        embed_started = time.perf_counter()
        query_variants = self._query_variants(intent_result["normalized_question"])
        query_vectors = self.embedder.embed_queries(query_variants)
        embed_elapsed = time.perf_counter() - embed_started

        search_started = time.perf_counter()
        hits = self._search(
            query_vectors=query_vectors,
            query_variants=query_variants,
            question=intent_result["normalized_question"],
            intent=intent_result["intent"],
            target_top_k=target_top_k,
            doc_ids=doc_ids,
        )
        search_elapsed = time.perf_counter() - search_started

        yield self._sse_event(
            "meta",
            {
                "normalized_question": intent_result["normalized_question"],
                "intent": intent_result["intent"],
                "query_variants": query_variants,
                "references": [self._reference_payload(hit) for hit in hits],
                "timing": {
                    "embed_seconds": embed_elapsed,
                    "search_seconds": search_elapsed,
                },
            },
        )

        if not hits:
            total_elapsed = time.perf_counter() - started_at
            yield self._sse_event(
                "done",
                {
                    "answer": "未检索到充分依据。",
                    "timing": {
                        "embed_seconds": embed_elapsed,
                        "search_seconds": search_elapsed,
                        "llm_seconds": 0.0,
                        "total_seconds": total_elapsed,
                    },
                },
            )
            return

        prompt = self._build_prompt(
            intent_result["normalized_question"],
            intent_result["intent"],
            hits,
        )

        llm_started = time.perf_counter()
        answer_parts: list[str] = []
        for token in self.llm_client.stream_chat(
            system_prompt=self._system_prompt(intent_result["intent"]),
            user_prompt=prompt,
        ):
            answer_parts.append(token)
        first_answer = "".join(answer_parts).strip()
        llm_elapsed = time.perf_counter() - llm_started

        extraction_llm_elapsed = 0.0
        fallback_search_elapsed = 0.0
        fallback_llm_elapsed = 0.0
        used_fallback = False
        used_extraction_fallback = False
        final_answer = first_answer
        if self._needs_original_question_retry(first_answer) and hits:
            extraction_started = time.perf_counter()
            extraction_answer = self.llm_client.chat(
                system_prompt=self._system_prompt(intent_result["intent"]),
                user_prompt=self._build_prompt(
                    intent_result["normalized_question"],
                    intent_result["intent"],
                    hits,
                    force_extract=True,
                    max_hits=min(3, len(hits)),
                ),
            )
            extraction_llm_elapsed = time.perf_counter() - extraction_started
            if not self._needs_original_question_retry(extraction_answer):
                final_answer = extraction_answer.strip()
                used_extraction_fallback = True

        if self._needs_original_question_retry(final_answer):
            retry_result = self._retry_with_original_question(
                question=question,
                intent_result=intent_result,
                target_top_k=target_top_k,
                doc_ids=doc_ids,
            )
            fallback_search_elapsed = retry_result["search_elapsed"]
            fallback_llm_elapsed = retry_result["llm_elapsed"]
            if retry_result["hits"]:
                hits = retry_result["hits"]
                query_variants = retry_result["query_variants"]
                final_answer = retry_result["answer"].strip()
                used_fallback = True

        for chunk in self._stream_chunks(final_answer):
            yield self._sse_event("token", {"delta": chunk})

        total_elapsed = time.perf_counter() - started_at
        logger.info(
            "QA stream timing | embed=%.3fs search=%.3fs llm=%.3fs retry_search=%.3fs retry_llm=%.3fs total=%.3fs hits=%s variants=%s fallback=%s question=%s",
            embed_elapsed,
            search_elapsed,
            llm_elapsed + extraction_llm_elapsed,
            fallback_search_elapsed,
            fallback_llm_elapsed,
            total_elapsed,
            len(hits),
            len(query_variants),
            used_fallback or used_extraction_fallback,
            intent_result["normalized_question"],
        )
        yield self._sse_event(
            "done",
            {
                "answer": final_answer,
                "timing": {
                    "embed_seconds": embed_elapsed,
                    "search_seconds": search_elapsed + fallback_search_elapsed,
                    "llm_seconds": llm_elapsed + extraction_llm_elapsed + fallback_llm_elapsed,
                    "total_seconds": total_elapsed,
                    "fallback_used": used_fallback or used_extraction_fallback,
                },
            },
        )

    def _retry_with_original_question(
        self,
        question: str,
        intent_result: dict[str, str],
        target_top_k: int,
        doc_ids: list[str] | None,
    ) -> dict:
        retry_question = question.strip() or intent_result["normalized_question"]
        query_variants = [retry_question]

        search_started = time.perf_counter()
        query_vectors = self.embedder.embed_queries(query_variants)
        hits = self._search(
            query_vectors=query_vectors,
            query_variants=query_variants,
            question=retry_question,
            intent=intent_result["intent"],
            target_top_k=target_top_k,
            doc_ids=doc_ids,
        )
        search_elapsed = time.perf_counter() - search_started

        if not hits:
            return {
                "answer": "",
                "hits": [],
                "query_variants": query_variants,
                "search_elapsed": search_elapsed,
                "llm_elapsed": 0.0,
            }

        prompt = self._build_prompt(
            retry_question,
            intent_result["intent"],
            hits,
        )
        llm_started = time.perf_counter()
        answer = self.llm_client.chat(
            system_prompt=self._system_prompt(intent_result["intent"]),
            user_prompt=prompt,
        )
        llm_elapsed = time.perf_counter() - llm_started
        logger.info(
            "Retried QA with original question | hits=%s question=%s normalized=%s",
            len(hits),
            retry_question,
            intent_result["normalized_question"],
        )
        return {
            "answer": answer.strip(),
            "hits": hits,
            "query_variants": query_variants,
            "search_elapsed": search_elapsed,
            "llm_elapsed": llm_elapsed,
        }

    def _needs_original_question_retry(self, answer: str) -> bool:
        compact = re.sub(r"\s+", "", answer or "")
        return any(
            re.sub(r"\s+", "", phrase) in compact
            for phrase in INSUFFICIENT_EVIDENCE_PHRASES
        )

    def _stream_chunks(self, text: str) -> Iterator[str]:
        chunk_size = max(self.settings.stream_emit_char_threshold, 1)
        for start in range(0, len(text), chunk_size):
            yield text[start : start + chunk_size]
