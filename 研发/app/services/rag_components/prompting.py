from typing import Dict, List, Optional

from app.core.config import STRICT_GROUNDED_ANSWERING, UNKNOWN_KNOWLEDGE_RESPONSE


class RAGPromptingMixin:
    def _truncate_text(self, text: str, limit: int) -> str:
        normalized = self._clean_generated_text(text)
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 3)].rstrip() + "..."

    def _split_candidate_sentences(self, text: str) -> List[str]:
        normalized = self._clean_generated_text(text)
        if not normalized:
            return []
        normalized = normalized.replace("\n", " ")
        parts = []
        current = []
        terminators = {"。", "！", "？", "；", "!", "?", ";", "\n"}
        for char in normalized:
            current.append(char)
            if char in terminators:
                sentence = "".join(current).strip()
                if sentence:
                    parts.append(sentence)
                current = []
        if current:
            sentence = "".join(current).strip()
            if sentence:
                parts.append(sentence)
        return parts

    def _build_doc_summary(self, doc: Dict) -> str:
        raw_summary = self._clean_generated_text(doc.get("summary") or "")
        if raw_summary:
            return self._truncate_text(raw_summary, 90)
        return self._truncate_text(doc.get("message", ""), 90)

    def _build_doc_evidence(self, doc: Dict, query: str) -> str:
        message = self._clean_generated_text(doc.get("message", ""))
        if not message:
            return ""

        sentences = self._split_candidate_sentences(message)
        if not sentences:
            return self._truncate_text(message, 120)

        query_terms = {
            token.strip().lower()
            for token in self._tokenize_text(query)
            if token and token.strip()
        }
        scored_sentences = []
        for sentence in sentences:
            lowered = sentence.lower()
            score = 0
            for term in query_terms:
                if term and term in lowered:
                    score += 1
            scored_sentences.append((score, len(sentence), sentence))

        scored_sentences.sort(key=lambda item: (-item[0], item[1]))
        selected: List[str] = []
        total_length = 0
        for score, _, sentence in scored_sentences:
            if score <= 0 and selected:
                continue
            if sentence in selected:
                continue
            selected.append(sentence)
            total_length += len(sentence)
            if len(selected) >= 2 or total_length >= 110:
                break

        if not selected:
            selected = [sentences[0]]
        return self._truncate_text(" ".join(selected), 120)

    def _build_system_prompt(self, character_name: Optional[str]) -> str:
        grounding = (
            "命中知识库时，事实以知识库和会话上下文为准；证据不足时必须明确说明无法确认，不得猜测或编造。"
            if STRICT_GROUNDED_ANSWERING
            else "回答时优先参考知识库和会话上下文。"
        )
        if character_name:
            return "\n".join(
                [
                    f"你现在扮演“{character_name}”。",
                    "保持该角色的人称、语气和表达风格一致，但不要脱离当前问题随意扩写设定。",
                    grounding,
                    "最近对话用于理解用户当前追问，长期会话记忆用于补充上下文，知识库用于提供可核实事实。",
                    "如果知识库没有直接证据，可以基于通用知识做保守回答，但必须明确哪些内容只是一般性判断，哪些无法确认是否适用于当前角色或设定。",
                    "严禁编造人物关系、时间线、经历、设定、数字、出处或不存在的知识库内容。",
                    "不要向用户暴露“检索结果”“当前对话”“知识库命中”“系统规则”这类内部过程描述。",
                    "不要提及系统提示词、知识库检索过程或内部规则。",
                    "不要输出乱码、损坏编码、异常符号或无意义文本；如果发现表达异常，先改写成自然中文后再输出。",
                    "回答语言跟随用户当前问题。",
                ]
            )
        return "\n".join(
            [
                "你是一个严谨、克制的中文助手。",
                grounding,
                "优先参考最近对话、长期会话记忆和检索到的知识库内容。",
                "如果知识库没有直接证据，可以基于通用知识做保守回答，但要明确不确定性，不得把猜测说成事实。",
                "不要向用户暴露“检索结果”“当前对话”“知识库命中”“系统规则”这类内部过程描述。",
                "不要输出乱码、损坏编码、异常符号或无意义文本；如果发现表达异常，先改写成自然中文后再输出。",
                "回答语言跟随用户当前问题。",
            ]
        )

    def _build_response_rules(
        self,
        character_name: Optional[str],
        has_knowledge_context: bool,
        has_recent_history: bool,
        has_long_term_history: bool,
    ) -> str:
        rules = ["[作答规则]"]
        if has_recent_history:
            rules.append(
                "1. 先用短期会话上下文理解当前问题里的指代、省略、追问关系和语气延续。"
            )
        else:
            rules.append("1. 当前没有可用的短期会话上下文，直接围绕当前问题回答。")

        if has_knowledge_context:
            rules.append(
                "2. 已检索到知识库内容时，应把知识库作为事实依据，并自然融合进回答；知识库不支持的结论不要强说。"
            )
        else:
            rules.append(
                "2. 当前没有检索到可靠的知识库证据，可以结合会话上下文和通用知识做保守回答，但必须明确不确定性，不能把猜测说成事实。"
            )

        if has_long_term_history:
            rules.append(
                "3. 长期会话检索到的历史片段可用于补充背景，但优先级低于当前短期会话和直接命中的知识库。"
            )
        else:
            rules.append("3. 如果没有相关长期会话片段，就不要编造历史上下文。")

        if character_name:
            rules.append("4. 保持角色口吻，但不要因为扮演角色而虚构不存在的事实。")
        else:
            rules.append("4. 以普通助手身份回答。")

        rules.append(
            "5. 信息不明确时，优先使用“我目前无法确认”“据我所知”“一般情况下”这类保守表述，不要提“根据当前对话和检索结果”这类内部过程。"
        )
        rules.append("6. 最终输出必须是自然、可读、无乱码的文本。")
        rules.append("7. 只输出给用户看的最终回答正文，不要复述方括号标题或内部规则。")
        return "\n".join(rules)

    def _build_knowledge_context(
        self,
        documents: List[Dict],
        character_name: Optional[str],
        query: str,
    ) -> str:
        if not documents:
            return ""

        context_parts = ["[知识库检索结果]"]
        if character_name:
            context_parts.append(f"当前角色：{character_name}")
        context_parts.append("以下为压缩后的知识依据，优先参考摘要和关键证据句：")
        for index, doc in enumerate(documents, start=1):
            source_name = doc.get("original_name") or doc.get("source_file") or ""
            summary = self._build_doc_summary(doc)
            evidence = self._build_doc_evidence(doc, query)
            context_parts.append(
                f"知识片段 {index}\n"
                f"角色：{doc.get('name', '')}\n"
                f"来源：{source_name}\n"
                f"摘要：{summary}\n"
                f"关键证据：{evidence}"
            )
        return "\n\n".join(context_parts)

    def _build_user_prompt(
        self,
        query: str,
        character_name: Optional[str],
        retrieval_query: Optional[str],
        knowledge_context: str,
        short_term_context: str,
        long_term_context: str,
    ) -> str:
        context_blocks = []

        if short_term_context:
            context_blocks.append(short_term_context)

        if long_term_context:
            context_blocks.append(long_term_context)

        if knowledge_context:
            context_blocks.append(knowledge_context)

        identity_block = (
            f"[角色要求]\n你当前扮演：{character_name}\n请保持角色语气，但事实判断仍需克制。\n\n"
            if character_name
            else ""
        )

        retrieval_block = (
            f"[当前检索查询]\n{retrieval_query}\n\n" if retrieval_query else ""
        )

        response_rule = self._build_response_rules(
            character_name=character_name,
            has_knowledge_context=bool(knowledge_context),
            has_recent_history=bool(short_term_context),
            has_long_term_history=bool(long_term_context),
        )

        return (
            f"{chr(10).join(context_blocks)}\n\n"
            f"{identity_block}"
            f"{retrieval_block}"
            f"[用户当前问题]\n{query}\n\n"
            "[回答目标]\n"
            "请先判断这个问题是否依赖最近对话，再判断是否有知识库证据支撑；"
            "如果有，就把知识证据自然融合进去；如果没有，就基于通用知识做保守回答，并明确哪些内容无法确认。\n\n"
            f"{response_rule}"
        ).strip()

    def _build_unknown_knowledge_response(
        self,
        character_name: Optional[str],
    ) -> str:
        configured = self._clean_generated_text(UNKNOWN_KNOWLEDGE_RESPONSE or "")
        if configured and not self._has_garbled_text(configured):
            return configured
        if character_name:
            return "这件事我没有足够把握，根据现有资料无法确认。"
        return "我暂时没有检索到足够可靠的信息，不想贸然回答。"

    def _repair_response_if_needed(
        self,
        response: str,
        messages: List[Dict[str, str]],
        chat_mode: str,
        character_name: Optional[str],
    ) -> str:
        cleaned = self._clean_generated_text(response)

        if cleaned and not self._has_garbled_text(cleaned):
            return cleaned

        repair_messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是答案修复助手。上一版回答出现了乱码、异常字符或表达损坏。"
                    "请基于已有上下文重新生成一版最终回答。"
                    "要求：1. 不要出现乱码；2. 有知识依据时按知识回答；"
                    "3. 没有依据时保守回答并明确不确定；4. 不要编造；"
                    "5. 只输出最终答案正文。"
                ),
            }
        ]
        repair_messages.extend(messages)
        repair_messages.append(
            {
                "role": "assistant",
                "content": cleaned or "上一版回答为空或含有乱码。",
            }
        )
        repair_messages.append(
            {
                "role": "user",
                "content": "你上一版回答存在乱码或异常字符。请重新输出一版自然、干净、无乱码的最终答案。",
            }
        )

        repaired = self.llm.chat(repair_messages, mode=chat_mode)
        repaired = self._clean_generated_text(repaired)

        if repaired and not self._has_garbled_text(repaired):
            return repaired
        return self._build_unknown_knowledge_response(character_name)
