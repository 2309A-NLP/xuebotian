from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from app.core.config import (
    FACT_QUERY_RERANK_SCORE_THRESHOLD,
    KNOWLEDGE_RERANK_SCORE_THRESHOLD,
    RERANK_TOP_K,
    RETRIEVAL_QUERY_REWRITE_ENABLED,
    RETRIEVAL_QUERY_REWRITE_MAX_CHARS,
    RETRIEVAL_QUERY_REWRITE_MAX_TURNS,
    TOP_K,
)
from app.core.logging_utils import get_logger


logger = get_logger(__name__)


class RAGRetrievalMixin:
    def _build_basic_retrieval_query(
        self,
        query: str,
        character_name: Optional[str],
    ) -> str:
        parts = []
        if character_name:
            parts.append(character_name.strip())
        if query:
            parts.append(query.strip())
        return " ".join(part for part in parts if part).strip()

    def _normalize_retrieval_query(
        self,
        rewritten_query: str,
        fallback_query: str,
        character_name: Optional[str],
    ) -> str:
        normalized = (rewritten_query or "").strip()
        normalized_lower = normalized.lower()
        for prefix in ("retrieval query:", "query:", "output:"):
            if normalized_lower.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                normalized_lower = normalized.lower()

        normalized = normalized.strip("`\"' ")
        normalized = " ".join(normalized.split())
        if not normalized:
            normalized = fallback_query

        max_chars = max(16, RETRIEVAL_QUERY_REWRITE_MAX_CHARS)
        if len(normalized) > max_chars:
            normalized = normalized[:max_chars].strip()

        if character_name and character_name not in normalized:
            normalized = f"{character_name} {normalized}".strip()

        return normalized or fallback_query

    def _build_history_fallback_query(
        self,
        query: str,
        character_name: Optional[str],
        recent_turns: List[Dict],
    ) -> str:
        fallback_query = self._build_basic_retrieval_query(query, character_name)
        if not recent_turns:
            return fallback_query

        context_parts: List[str] = []
        for turn in self._get_recent_dialogue_turns(recent_turns):
            user_message = (turn.get("user_message") or "").strip()
            assistant_message = (turn.get("assistant_message") or "").strip()
            if user_message:
                context_parts.append(user_message)
            if assistant_message:
                context_parts.append(assistant_message)

        history_query = " ".join(
            part for part in [character_name or "", *context_parts, query] if part
        ).strip()

        return self._normalize_retrieval_query(
            history_query,
            fallback_query=fallback_query,
            character_name=character_name,
        )

    def _rewrite_retrieval_query(
        self,
        query: str,
        character_name: Optional[str],
        recent_turns: List[Dict],
        chat_mode: str,
    ) -> str:
        fallback_query = self._build_basic_retrieval_query(query, character_name)
        if not RETRIEVAL_QUERY_REWRITE_ENABLED:
            return fallback_query

        recent_dialogue = self._get_recent_dialogue_turns(
            recent_turns,
            limit=RETRIEVAL_QUERY_REWRITE_MAX_TURNS,
        )
        if not recent_dialogue:
            return fallback_query

        dialogue_lines: List[str] = []
        for index, turn in enumerate(recent_dialogue, start=1):
            user_message = (turn.get("user_message") or "").strip()
            assistant_message = (turn.get("assistant_message") or "").strip()
            if not user_message and not assistant_message:
                continue
            dialogue_lines.append(f"Turn {index}")
            if user_message:
                dialogue_lines.append(f"User: {user_message}")
            if assistant_message:
                dialogue_lines.append(f"Assistant: {assistant_message}")

        if not dialogue_lines:
            return fallback_query

        messages = [
            {
                "role": "system",
                "content": (
                    "你是检索改写助手，需要把用户当前问题改写成一条适合知识检索的短查询。\n"
                    "要求：\n"
                    "1. 结合最近几轮对话补全指代、省略和上下文。\n"
                    "2. 保留用户当前问题的真实意图，不要扩写成回答。\n"
                    "3. 只有在有助于检索时才带上角色名。\n"
                    "4. 输出一条简洁查询，不要解释，不要换行，不要出现乱码。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"[最近对话]\n{chr(10).join(dialogue_lines)}\n\n"
                    f"[当前角色]\n{character_name or '无'}\n\n"
                    f"[当前问题]\n{query}"
                ),
            },
        ]

        rewritten = self.llm.chat(messages, mode=chat_mode)

        if self._has_garbled_text(rewritten):
            return self._build_history_fallback_query(
                query, character_name, recent_turns
            )
        normalized_query = self._normalize_retrieval_query(
            rewritten,
            fallback_query=fallback_query,
            character_name=character_name,
        )
        if normalized_query:
            return normalized_query

        return self._build_history_fallback_query(query, character_name, recent_turns)

    def _build_retrieval_query(
        self,
        query: str,
        character_name: Optional[str],
        recent_turns: List[Dict],
        chat_mode: str,
    ) -> str:
        return self._rewrite_retrieval_query(
            query=query,
            character_name=character_name,
            recent_turns=recent_turns,
            chat_mode=chat_mode,
        )

    def _build_candidate_key(self, doc: Dict) -> str:
        return "||".join(
            [
                doc.get("parent_id", ""),
                doc.get("source_file", ""),
                str(int(doc.get("chunk_index", 0) or 0)),
                doc.get("message", ""),
                doc.get("access_key", ""),
            ]
        )

    def _search_candidates(
        self,
        candidate_query: str,
        character_name: Optional[str],
        query_embedding=None,
    ) -> Tuple[str, List[Dict]]:
        candidates = self.vector_store.hybrid_search(
            candidate_query,
            top_k=max(TOP_K * 2, RERANK_TOP_K * 3),
            character_name=character_name,
            query_embedding=query_embedding,
        )
        return candidate_query, candidates

    def _select_best_candidate_result(
        self,
        results: List[Tuple[str, List[Dict]]],
        preferred_query: str,
    ) -> Tuple[str, List[Dict]]:
        if not results:
            return preferred_query, []

        def result_score(item: Tuple[str, List[Dict]]) -> Tuple[float, int]:
            result_query, documents = item
            if not documents:
                return float("-inf"), int(result_query == preferred_query)
            best_score = documents[0].get("score", 0.0)
            return float(best_score), int(result_query == preferred_query)

        return max(results, key=result_score)

    def _search_character_candidates(
        self,
        query: str,
        character_name: Optional[str],
        recent_turns: List[Dict],
        chat_mode: str,
    ) -> Tuple[str, List[Dict]]:
        retrieval_query = self._build_retrieval_query(
            query=query,
            character_name=character_name,
            recent_turns=recent_turns,
            chat_mode=chat_mode,
        )

        fallback_query = self._build_basic_retrieval_query(query, character_name)
        candidate_queries = list(dict.fromkeys([retrieval_query, fallback_query]))

        if len(candidate_queries) == 1:
            selected_query = candidate_queries[0]
            _, candidates = self._search_candidates(
                selected_query,
                character_name,
            )
            reranked = self.reranker.rerank(
                selected_query,
                candidates,
                top_k=max(RERANK_TOP_K, TOP_K),
            )
            return selected_query, reranked[:RERANK_TOP_K]

        query_embeddings = self.embedding_model.encode(candidate_queries)
        search_results: List[Tuple[str, List[Dict]]] = []
        with ThreadPoolExecutor(max_workers=len(candidate_queries)) as executor:
            futures = [
                executor.submit(
                    self._search_candidates,
                    candidate_query,
                    character_name,
                    query_embeddings[index],
                )
                for index, candidate_query in enumerate(candidate_queries)
            ]
            for future in as_completed(futures):
                search_results.append(future.result())

        selected_query, selected_candidates = self._select_best_candidate_result(
            search_results,
            preferred_query=retrieval_query,
        )
        reranked = self.reranker.rerank(
            selected_query,
            selected_candidates,
            top_k=max(RERANK_TOP_K, TOP_K),
        )
        selected_docs = reranked[:RERANK_TOP_K]
        logger.info(
            "并行混合检索择优完成: 检索查询=%r 候选查询=%s 选中查询=%r 命中=%s",
            retrieval_query,
            candidate_queries,
            selected_query,
            len(selected_docs),
        )
        return selected_query, selected_docs

    def _resolve_character(
        self,
        requested_character: Optional[str],
        session_id: str,
        recent_turns: List[Dict],
        reranked_docs: List[Dict],
    ) -> Optional[str]:
        if requested_character:
            return requested_character
        last_character = self.memory.get_last_character(session_id, turns=recent_turns)
        if last_character:
            return last_character
        if reranked_docs:
            return reranked_docs[0]["name"]
        return None

    def _search_role_knowledge(
        self,
        query: str,
        requested_character: Optional[str],
        session_id: str,
        recent_turns: List[Dict],
        chat_mode: str,
    ) -> Tuple[Optional[str], str, List[Dict]]:
        retrieval_query, reranked_docs = self._search_character_candidates(
            query=query,
            character_name=requested_character,
            recent_turns=recent_turns,
            chat_mode=chat_mode,
        )

        detected_character = self._resolve_character(
            requested_character=requested_character,
            session_id=session_id,
            recent_turns=recent_turns,
            reranked_docs=reranked_docs,
        )
        return detected_character, retrieval_query, reranked_docs

    def _min_knowledge_score(self, query: str) -> float:
        if self._is_fact_seeking_query(query):
            return FACT_QUERY_RERANK_SCORE_THRESHOLD
        return KNOWLEDGE_RERANK_SCORE_THRESHOLD

    def _has_valid_knowledge(self, query: str, documents: List[Dict]) -> bool:
        if not documents:
            return False
        best_score = documents[0].get("rerank_score")
        if best_score is None:
            return True

        return float(best_score) >= self._min_knowledge_score(query)
