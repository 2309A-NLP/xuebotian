import re
from typing import Dict, List, Optional

from app.core.config import (
    RECENT_HISTORY_MESSAGE_TURNS,
    RECENT_HISTORY_PROMPT_TURNS,
    RETRIEVAL_HISTORY_DIALOGUE_TURNS,
    SHORT_TERM_RELEVANT_HISTORY_TURNS,
)


class RAGHistoryMixin:
    def _get_recent_dialogue_turns(
        self,
        recent_turns: List[Dict],
        limit: int = RETRIEVAL_HISTORY_DIALOGUE_TURNS,
    ) -> List[Dict]:
        if not recent_turns:
            return []
        return recent_turns[-max(1, limit) :]

    def _messages_to_turns(self, messages: List[Dict]) -> List[Dict]:
        turns: List[Dict] = []
        for item in messages:
            user_message = (item.get("user_message") or "").strip()
            if user_message:
                turns.append(
                    {
                        "user_message": user_message,
                        "assistant_message": (
                            item.get("assistant_message") or ""
                        ).strip(),
                        "character_name": (item.get("character_name") or "").strip(),
                    }
                )
                continue
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                turns.append(
                    {
                        "user_message": content,
                        "assistant_message": "",
                        "character_name": "",
                    }
                )
            elif role == "assistant" and turns:
                turns[-1]["assistant_message"] = content
        return turns

    def _score_turn_relevance(
        self,
        query: str,
        turn: Dict,
        turn_index: int,
        total_turns: int,
    ) -> float:
        user_message = (turn.get("user_message") or "").strip()
        assistant_message = (turn.get("assistant_message") or "").strip()
        turn_text = "\n".join(
            part for part in [user_message, assistant_message] if part
        )
        if not turn_text:
            return 0.0

        query_tokens = set(self._tokenize_text(query))
        turn_tokens = set(self._tokenize_text(turn_text))
        overlap_score = 0.0
        if query_tokens and turn_tokens:
            overlap_score = len(query_tokens & turn_tokens) / max(1, len(query_tokens))

        normalized_query = self._normalize_match_text(query)
        normalized_turn = self._normalize_match_text(turn_text)
        exact_bonus = 0.0

        if normalized_query and normalized_query in normalized_turn:
            exact_bonus += 0.35

        if self._contains_history_reference(query):
            exact_bonus += 0.08

        recency_bonus = ((turn_index + 1) / max(1, total_turns)) * 0.18
        return overlap_score + exact_bonus + recency_bonus

    def _select_relevant_turns(
        self,
        query: str,
        turns: List[Dict],
        limit: int,
    ) -> List[Dict]:
        if not query or not turns:
            return []

        total_turns = len(turns)
        scored_turns = []
        for index, turn in enumerate(turns):
            score = self._score_turn_relevance(query, turn, index, total_turns)
            if score <= 0:
                continue
            scored_turns.append((score, index, turn))

        if not scored_turns:
            return []

        scored_turns.sort(key=lambda item: item[0], reverse=True)
        threshold = 0.08 if self._contains_history_reference(query) else 0.14

        selected = [
            (index, turn) for score, index, turn in scored_turns if score >= threshold
        ][: max(1, limit)]

        if not selected:
            selected = [
                (index, turn) for _, index, turn in scored_turns[: max(1, limit)]
            ]

        selected.sort(key=lambda item: item[0])
        return [turn for _, turn in selected]

    def _build_short_term_context(
        self,
        query: str,
        recent_turns: List[Dict],
        character_name: Optional[str],
        max_turns: int = SHORT_TERM_RELEVANT_HISTORY_TURNS,
    ) -> str:
        if not recent_turns:
            return ""

        limited_turns = recent_turns[-max(1, RECENT_HISTORY_PROMPT_TURNS) :]
        related_turns = self._select_relevant_turns(
            query=query,
            turns=limited_turns,
            limit=max_turns,
        )

        if not related_turns:
            related_turns = limited_turns[-max(1, max_turns) :]

        context_parts = ["[短期会话上下文]"]
        if character_name:
            context_parts.append(f"当前对话角色：{character_name}")
        for index, turn in enumerate(related_turns, start=1):
            turn_character = turn.get("character_name", "")
            role_label = f"（角色：{turn_character}）" if turn_character else ""
            context_parts.append(
                f"最近片段 {index}{role_label}\n"
                f"用户：{turn.get('user_message', '')}\n"
                f"助手：{turn.get('assistant_message', '')}"
            )
        return "\n\n".join(context_parts)

    def _deduplicate_long_term_history(
        self,
        conversations: List[Dict],
        recent_turns: List[Dict],
    ) -> List[Dict]:
        if not conversations:
            return []
        recent_pairs = {
            (
                (turn.get("user_message") or "").strip(),
                (turn.get("assistant_message") or "").strip(),
            )
            for turn in recent_turns
        }
        filtered = []
        for conversation in conversations:
            pair = (
                (conversation.get("user_message") or "").strip(),
                (conversation.get("assistant_message") or "").strip(),
            )
            if pair in recent_pairs:
                continue
            filtered.append(conversation)
        return filtered

    def _build_long_term_context(self, conversations: List[Dict]) -> str:
        if not conversations:
            return ""
        context_parts = ["[长期会话检索]"]
        for index, conversation in enumerate(conversations, start=1):
            character = conversation.get("character_name", "")
            role_label = f"（角色：{character}）" if character else ""
            context_parts.append(
                f"历史片段 {index}{role_label}\n"
                f"用户：{conversation['user_message']}\n"
                f"助手：{conversation['assistant_message']}"
            )
        return "\n\n".join(context_parts)

    def _build_history_messages(
        self,
        session_id: str,
        recent_turns: List[Dict],
        max_turns: int = RECENT_HISTORY_MESSAGE_TURNS,
    ) -> List[Dict[str, str]]:
        turns = recent_turns[-max_turns:] if recent_turns else []
        return self.memory.get_message_history(session_id, turns=turns)

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
