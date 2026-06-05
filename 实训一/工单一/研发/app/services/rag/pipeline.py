from __future__ import annotations

from app.core.config import Settings
from app.models.domain import SearchHit
from app.services.intent.analyzer import IntentAnalyzer
from app.services.llm.client import OpenAICompatibleLLMClient
from app.services.vector.embedder import BgeM3Embedder
from app.services.vector.milvus_store import BaseVectorStore


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
        intent_result = self.intent_analyzer.analyze(question)
        query_vector = self.embedder.embed_query(intent_result["normalized_question"])
        hits = self.vector_store.search(
            embedding=query_vector,
            top_k=top_k or self.settings.top_k,
            doc_ids=doc_ids,
        )
        prompt = self._build_prompt(
            intent_result["normalized_question"],
            intent_result["intent"],
            hits,
        )
        answer = self.llm_client.chat(
            system_prompt=self._system_prompt(intent_result["intent"]),
            user_prompt=prompt,
        )
        return {
            "normalized_question": intent_result["normalized_question"],
            "intent": intent_result["intent"],
            "answer": answer.strip(),
            "references": hits,
        }

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
            context_blocks.append(
                f"[片段{index}] 文档={hit.source_file} 页码={hit.page} 相似度={hit.score:.4f}\n{hit.text}"
            )
        context = "\n\n".join(context_blocks) if context_blocks else "无可用检索结果"
        return (
            f"问题：{question}\n"
            f"意图：{intent}\n\n"
            f"参考内容：\n{context}\n\n"
            "请输出最终答案；如果参考内容不足以支持结论，直接说明未检索到充分依据。"
        )
