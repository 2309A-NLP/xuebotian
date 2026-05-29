import time
from typing import Dict, Generator, List, Optional

from app.core.config import LONG_TERM_MEMORY_TOP_K
from app.core.logging_utils import get_logger
from app.services.ingestion.loader import clean_name, load_data


logger = get_logger(__name__)


class RAGRuntimeMixin:
    def _should_use_long_term_history(
        self,
        query: str,
        recent_turns: List[Dict],
    ) -> bool:
        if not query or not recent_turns:
            return False
        return self._contains_history_reference(query)

    def _build_knowledge_index(self, documents: List[Dict]) -> None:
        logger.info("开始构建向量索引和 BM25 索引")
        self.vector_store.build_index(documents)
        logger.info("知识索引构建完成")

    def hydrate_knowledge(self, documents: List[Dict]) -> int:
        logger.info("已按缓存状态标记知识库完成初始化: 记录数=%s", len(documents))
        self._initialized = True
        return len(documents)

    def append_knowledge(self, documents: List[Dict]) -> int:
        logger.info("开始追加知识记录: 数量=%s", len(documents))
        loaded_count = self.vector_store.append_documents(documents)
        self._initialized = True
        logger.info("知识追加完成: 新增=%s", loaded_count)
        return loaded_count

    def initialize(self):
        if self._initialized:
            return
        documents = load_data()
        self._build_knowledge_index(documents)
        self._initialized = True

    def reload_knowledge(self, documents: Optional[List[Dict]] = None) -> int:
        documents = documents if documents is not None else load_data()
        logger.info("开始重载知识库: 记录数=%s", len(documents))
        self._build_knowledge_index(documents)
        self._initialized = True
        return len(documents)

    def _store_turn(
        self,
        session_id: str,
        query: str,
        response: str,
        character_name: Optional[str],
    ) -> None:
        self.memory.add_turn(
            session_id=session_id,
            user_message=query,
            assistant_message=response,
            character_name=character_name,
        )
        self.vector_store.add_conversation(
            session_id,
            query,
            response,
            character_name=character_name or "",
        )

    def _prepare_chat_context(
        self,
        query: str,
        session_id: str,
        character_name: Optional[str],
        chat_mode: str,
    ) -> Dict:
        requested_character = clean_name(character_name or "") or None
        recent_turns = self.memory.get_recent_turns(session_id)
        last_character = self.memory.get_last_character(session_id, turns=recent_turns)

        detected_character, retrieval_query, role_docs = self._search_role_knowledge(
            query=query,
            requested_character=requested_character,
            session_id=session_id,
            recent_turns=recent_turns,
            chat_mode=chat_mode,
        )
        logger.info(
            "对话检索完成: 会话ID=%s 指定角色=%r 识别角色=%r 检索查询=%r 命中文档数=%s",
            session_id,
            requested_character,
            detected_character,
            retrieval_query,
            len(role_docs),
        )

        has_valid_knowledge = self._has_valid_knowledge(query, role_docs)
        effective_sources = role_docs if has_valid_knowledge else []
        effective_character = (
            requested_character
            or last_character
            or (detected_character if has_valid_knowledge else None)
        )
        memory_query = retrieval_query or self._build_retrieval_query(
            query=query,
            character_name=effective_character,
            recent_turns=recent_turns,
            chat_mode=chat_mode,
        )
        long_term_history: List[Dict] = []
        if self._should_use_long_term_history(query, recent_turns):
            long_term_history = self.vector_store.search_conversations(
                query=memory_query,
                session_id=session_id,
                top_k=LONG_TERM_MEMORY_TOP_K,
            )
            long_term_history = self._deduplicate_long_term_history(
                long_term_history,
                recent_turns,
            )
            logger.info(
                "已触发长期记忆检索: 会话ID=%s 查询=%r 命中=%s",
                session_id,
                memory_query,
                len(long_term_history),
            )
        else:
            logger.info("已跳过长期记忆检索: 会话ID=%s 当前问题无需历史召回", session_id)

        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": self._build_system_prompt(effective_character),
            }
        ]
        messages.extend(self._build_history_messages(session_id, recent_turns))
        messages.append(
            {
                "role": "user",
                "content": self._build_user_prompt(
                    query=query,
                    character_name=effective_character,
                    retrieval_query=(
                        retrieval_query if has_valid_knowledge else memory_query
                    ),
                    knowledge_context=self._build_knowledge_context(
                        effective_sources,
                        effective_character,
                        query,
                    ),
                    short_term_context=self._build_short_term_context(
                        memory_query or query,
                        recent_turns,
                        effective_character,
                    ),
                    long_term_context=self._build_long_term_context(long_term_history),
                ),
            }
        )

        return {
            "query": query,
            "session_id": session_id,
            "effective_character": effective_character,
            "effective_sources": effective_sources,
            "long_term_history": long_term_history,
            "recent_turns": recent_turns,
            "messages": messages,
            "chat_mode": chat_mode,
        }

    def _build_chat_result(self, context: Dict, response: str) -> Dict:
        return {
            "response": response,
            "character": context.get("effective_character"),
            "sources": [
                {
                    "name": doc["name"],
                    "rerank_score": doc.get("rerank_score", 0.0),
                    "text": doc.get("message", ""),
                }
                for doc in context.get("effective_sources", [])
            ],
            "session_id": context.get("session_id", "default"),
            "long_term_history_count": len(context.get("long_term_history", [])),
            "short_term_history_count": min(
                len(context.get("recent_turns", [])) + 1,
                self.memory.max_rounds,
            ),
        }

    def _build_cached_chat_result(
        self,
        *,
        cached_answer: str,
        cached_character: Optional[str],
        session_id: str,
        recent_turns: List[Dict],
    ) -> Dict:
        return {
            "response": cached_answer,
            "character": cached_character,
            "sources": [],
            "session_id": session_id,
            "long_term_history_count": 0,
            "short_term_history_count": min(
                len(recent_turns) + 1,
                self.memory.max_rounds,
            ),
        }

    def chat(
        self,
        query: str,
        session_id: str = "default",
        character_name: Optional[str] = None,
        chat_mode: str = "offline",
    ) -> Dict:
        recent_turns = self.memory.get_recent_turns(session_id)
        cached_response = self.response_cache.get(
            query=query,
            character_name=character_name,
            chat_mode=chat_mode,
            recent_turns=recent_turns,
        )
        if cached_response:
            cached_answer = cached_response.get("answer", "")
            cached_character = cached_response.get("character") or character_name
            result = self._build_cached_chat_result(
                cached_answer=cached_answer,
                cached_character=cached_character,
                session_id=session_id,
                recent_turns=recent_turns,
            )
            self.memory.add_turn(
                session_id=session_id,
                user_message=query,
                assistant_message=cached_answer,
                character_name=cached_character,
            )
            logger.info(
                "对话命中响应缓存: 会话ID=%s 角色=%r 模式=%s",
                session_id,
                character_name,
                chat_mode,
            )
            return result

        context = self._prepare_chat_context(
            query=query,
            session_id=session_id,
            character_name=character_name,
            chat_mode=chat_mode,
        )
        messages = context["messages"]
        effective_character = context["effective_character"]

        response = self.llm.chat(messages, mode=chat_mode)
        self._store_turn(session_id, query, response, effective_character)
        logger.info(
            "对话完成: 会话ID=%s 生效角色=%r",
            session_id,
            effective_character,
        )
        result = self._build_chat_result(context, response)
        self.response_cache.set(
            query=query,
            character_name=character_name,
            chat_mode=chat_mode,
            recent_turns=recent_turns,
            answer=response,
            effective_character=effective_character,
        )
        return result

    def stream_chat(
        self,
        query: str,
        session_id: str = "default",
        character_name: Optional[str] = None,
        chat_mode: str = "offline",
    ) -> Generator[Dict, None, None]:
        started_at = time.perf_counter()
        recent_turns = self.memory.get_recent_turns(session_id)
        cached_response = self.response_cache.get(
            query=query,
            character_name=character_name,
            chat_mode=chat_mode,
            recent_turns=recent_turns,
        )
        if cached_response:
            cached_character = cached_response.get("character") or character_name
            cached_answer = cached_response.get("answer", "")
            result = self._build_cached_chat_result(
                cached_answer=cached_answer,
                cached_character=cached_character,
                session_id=session_id,
                recent_turns=recent_turns,
            )
            logger.info(
                "流式对话命中响应缓存: 会话ID=%s 角色=%r 模式=%s 耗时=%.3fs",
                session_id,
                character_name,
                chat_mode,
                time.perf_counter() - started_at,
            )
            yield {
                "event": "replace",
                "data": {"content": cached_answer},
            }
            self.memory.add_turn(
                session_id=session_id,
                user_message=query,
                assistant_message=cached_answer,
                character_name=cached_character,
            )
            yield {"event": "done", "data": result}
            return

        context_started_at = time.perf_counter()
        context = self._prepare_chat_context(
            query=query,
            session_id=session_id,
            character_name=character_name,
            chat_mode=chat_mode,
        )
        logger.info(
            "流式对话上下文准备完成: 会话ID=%s 耗时=%.3fs",
            session_id,
            time.perf_counter() - context_started_at,
        )
        messages = context["messages"]
        effective_character = context["effective_character"]

        streamed_chunks: List[str] = []
        first_chunk_sent = False
        for chunk in self.llm.stream_chat(messages, mode=chat_mode):
            if not chunk:
                continue
            if not first_chunk_sent:
                first_chunk_sent = True
                logger.info(
                    "流式对话首个响应片段到达: 会话ID=%s 总耗时=%.3fs",
                    session_id,
                    time.perf_counter() - started_at,
                )
            streamed_chunks.append(chunk)
            yield {"event": "delta", "data": {"content": chunk}}

        final_response = self._clean_generated_text("".join(streamed_chunks))

        self._store_turn(session_id, query, final_response, effective_character)
        result = self._build_chat_result(context, final_response)
        self.response_cache.set(
            query=query,
            character_name=character_name,
            chat_mode=chat_mode,
            recent_turns=recent_turns,
            answer=final_response,
            effective_character=effective_character,
        )
        logger.info(
            "对话流式输出完成: 会话ID=%s 生效角色=%r",
            session_id,
            effective_character,
        )
        yield {"event": "done", "data": result}

    def delete_session(self, session_id: str) -> None:
        self.memory.clear_history(session_id)
        self.vector_store.delete_conversation(session_id)
