from __future__ import annotations

import json
import logging
import re

from app.services.rag.pipeline_constants import _DOMAIN_TERMS, _ORG_RE, _YEAR_RE

logger = logging.getLogger(__name__)

_SOURCE_SCOPE_TERMS = (
    "招股意向书",
    "招股说明书",
    "招股书",
    "募集说明书",
    "说明书",
    "年报",
    "半年报",
    "季报",
    "公告",
    "报告",
    "文件",
    "资料",
    "文档",
    "手册",
    "制度",
    "合同",
    "章程",
)

_VISUAL_HINT_TERMS = (
    "图",
    "图中",
    "图里",
    "图上",
    "图表",
    "图片",
    "曲线",
    "柱状图",
    "折线图",
    "饼图",
    "趋势图",
    "增长图",
    "示意图",
    "流程图",
    "结构图",
)

_TABLE_HINT_TERMS = (
    "表",
    "表格",
    "表中",
    "表内",
    "表里",
    "表头",
)

_QUESTION_HINT_TERMS = (
    "哪个",
    "哪些",
    "多少",
    "几个",
    "是否",
    "怎么",
    "如何",
    "最快",
    "最高",
    "最低",
    "最大",
    "最小",
    "负增长",
    "增长率",
    "排名",
    "占比",
)


class RagQueryMixin:
    """提供查询改写、关键词提取和检索变体生成逻辑。"""
    def _query_variants(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[str]:
        """生成用于检索的查询变体集合。"""
        if not self.settings.query_rewrite_enabled:
            return [question]
        try:
            return self._llm_query_variants(question, history)
        except Exception:
            logger.exception("LLM query rewrite failed, fallback to conservative variants")
        return self._fallback_query_variants(question)

    def _llm_query_variants(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[str]:
        """处理llm查询查询变体。"""
        total_variant_limit = max(int(self.settings.llm_query_variant_count), 1) + 1
        history_block = self._query_history_block(history)
        prompt = (
            "你擅长把用户问题改写成更适合检索的查询表达。"
            "请围绕提高召回率和准确率，对当前问题做等价改写，并保持核心语义、查询意图、主体、字段、时间、范围、条件、比较关系和否定约束不变。\n"
            "优先补全对检索有帮助但在原问题中省略的上下文，显式展开简称、别名、行业术语、常见说法、隐含条件和可能的字段表达；也可以调整语序、替换同义表达、把口语化问题改成更清晰的检索问句。\n"
            "每一条输出都必须是自然、完整、可直接检索的中文问句或陈述句，禁止写成关键词列表、短语拼接、标签串、分号分隔词组或搜索框检索词串。\n"
            "如果原问题已经足够清晰，可以不改写；通常只返回最有价值的少量版本，只有确实存在明显不同且同样高价值的等价表达时，才额外返回更多版本，并按检索价值从高到低排序。\n"
            "不要引入原问题没有的新事实、新数字、新结论，不要扩大或缩小查询范围，不要输出关键词堆砌、短语列表、解释或分析过程。\n"
            "只输出 JSON。\n"
            "- 输出格式：{\"queries\": [\"...\"]}\n"
            f"{history_block}"
            f"当前问题：{question}"
        )
        raw = self.llm_client.chat(
            system_prompt="",
            user_prompt=prompt,
            max_tokens=self.settings.query_rewrite_max_tokens,
            temperature=0.0,
        )
        rewrites = self._parse_rewrite_response(raw)

        variants = [question]
        for rewrite in rewrites:
            compact = re.sub(r"\s+", " ", rewrite).strip()
            if (
                compact
                and compact != question
                and compact not in variants
                and self._is_safe_rewrite(question, compact)
            ):
                variants.append(compact)
                if len(variants) >= total_variant_limit:
                    break

        if len(variants) == 1:
            for fallback in self._fallback_rewrite_candidates(question):
                compact = re.sub(r"\s+", " ", fallback or "").strip()
                if (
                    compact
                    and compact != question
                    and compact not in variants
                    and self._is_safe_rewrite(question, compact)
                ):
                    variants.append(compact)
                    break

        return variants

    def _query_history_block(self, history: list[dict[str, str]] | None) -> str:
        """处理查询历史记录块。"""
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
            entry = f"{label}：{text[:240]}"
            if used_chars + len(entry) > 1200:
                break
            lines.append(entry)
            used_chars += len(entry)
        if not lines:
            return ""
        return "最近对话（按时间顺序）：\n" + "\n".join(lines) + "\n"

    def _is_safe_rewrite(self, question: str, rewrite: str) -> bool:
        """判断安全改写结果改写结果是否成立。"""
        if len(rewrite) > 240:
            return False
        if self._looks_like_keyword_list(rewrite):
            return False
        question_numbers = set(re.findall(r"\d+(?:[.,]\d+)?%?", question))
        rewrite_numbers = set(re.findall(r"\d+(?:[.,]\d+)?%?", rewrite))
        if not rewrite_numbers <= question_numbers:
            return False
        if "。" in rewrite and "。" not in question:
            return False
        protected_negations = ("不存在", "未", "没有", "无")
        for negation in protected_negations:
            if negation in question and negation not in rewrite:
                return False
        for constraint in self._essential_constraints(question):
            if constraint and constraint not in rewrite:
                return False
        for org in self._org_phrases(question):
            if org and org not in rewrite:
                return False
        anchor_title = self._evidence_anchor_title(question)
        if anchor_title and anchor_title not in rewrite:
            return False
        return True

    def _looks_like_keyword_list(self, text: str) -> bool:
        """判断关键词列表是否成立。"""
        compact = re.sub(r"\s+", " ", text or "").strip()
        if not compact:
            return True
        if "？" in compact or "?" in compact:
            return False
        if any(punct in compact for punct in ("；", ";", "/", "|")):
            return True

        tokens = [token for token in re.split(r"[，,、\s]+", compact) if token]
        if len(tokens) < 3:
            return False

        sentence_markers = (
            "是",
            "有",
            "在",
            "为",
            "与",
            "和",
            "及",
            "是否",
            "多少",
            "哪些",
            "哪个",
            "如何",
            "怎么",
            "情况",
            "数据",
            "原因",
            "影响",
            "分别",
            "包括",
        )
        if any(marker in compact for marker in sentence_markers):
            return False

        short_token_count = sum(1 for token in tokens if len(token) <= 6)
        return short_token_count >= max(len(tokens) - 1, 3)

    def _parse_rewrite_response(self, raw: str) -> list[str]:
        """解析改写结果响应数据。"""
        text = raw.strip()
        if not text:
            return []
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        match = re.search(r"\{.*\}", text, flags=re.S)
        payload_text = match.group(0) if match else text
        payload = json.loads(payload_text)
        if isinstance(payload, dict):
            single = payload.get("query")
            if isinstance(single, str) and single.strip():
                return [single]
        queries = payload.get("queries") if isinstance(payload, dict) else None
        if not isinstance(queries, list):
            return []
        return [item for item in queries if isinstance(item, str)]

    def _fallback_query_variants(self, question: str) -> list[str]:
        """处理回退结果查询查询变体。"""
        variants = [question]
        for fallback in self._fallback_rewrite_candidates(question):
            compact = re.sub(r"\s+", " ", fallback or "").strip()
            if compact and compact != question and self._is_safe_rewrite(question, compact):
                variants.append(compact)
                break
        return variants

    def _best_fallback_rewrite(self, question: str) -> str:
        """处理最佳片段回退结果改写结果。"""
        return self._normalize_question_text(question)

    def _fallback_rewrite_candidates(self, question: str) -> list[str]:
        """处理回退结果改写结果candidates。"""
        candidates = [
            self._best_fallback_rewrite(question),
            self._normalize_question_text(self._strip_source_scope(question)),
            self._normalize_question_text(self._strip_org_prefix(question)),
        ]
        cleaned: list[str] = []
        for candidate in candidates:
            compact = re.sub(r"\s+", " ", candidate or "").strip()
            if compact and compact not in cleaned:
                cleaned.append(compact)
        return cleaned

    def _normalize_question_text(self, text: str) -> str:
        """规范化问题文本文本。"""
        compact = re.sub(r"\s+", " ", text or "").strip(" ，；。")
        if not compact:
            return ""
        if compact[-1] not in "？?":
            if any(token in compact for token in ("什么", "哪个", "哪些", "多少", "是否", "如何", "怎么")):
                compact = f"{compact}？"
        return compact

    def _essential_constraints(self, question: str) -> list[str]:
        """处理essentialconstraints。"""
        constraints: list[str] = []
        for negation in ("不存在", "存在", "未", "没有", "无"):
            if negation in question and negation not in constraints:
                constraints.append(negation)
        for year in _YEAR_RE.findall(question):
            value = re.sub(r"\s+", "", year)
            if value and value not in constraints:
                constraints.append(value)
        for number in re.findall(r"\d+(?:[.,]\d+)?%?", question):
            if number not in constraints:
                constraints.append(number)
        for phrase in ("增长率", "负增长", "最快", "最高", "最低", "最大", "最小"):
            if phrase in question and phrase not in constraints:
                constraints.append(phrase)
        return constraints[:8]

    def _question_focus_terms(self, question: str) -> list[str]:
        """处理问题文本focus术语集合。"""
        patterns = (
            r"(?:什么|哪个|哪些|多少|是否|有无|如何|怎么|哪一项|哪一个)([\u4e00-\u9fffA-Za-z0-9%\.]{2,20})",
            r"([\u4e00-\u9fffA-Za-z0-9%\.]{2,20})(?:是什么|有哪些|是多少|为多少|分别是|吗|？|\?)",
            r"(?:查询|查找|列出|说明|回答)([\u4e00-\u9fffA-Za-z0-9%\.]{2,20})",
        )
        terms: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, question):
                value = match.strip()
                if value and value not in terms:
                    terms.append(value)
        anchor_title = self._evidence_anchor_title(question)
        if anchor_title and anchor_title not in terms:
            terms.append(anchor_title)
        for phrase in ("增长率", "负增长", "最快", "最高", "最低", "最大", "最小", "行业", "类别"):
            if phrase in question and phrase not in terms:
                terms.append(phrase)
        for term in self._important_terms(question):
            if term not in terms:
                terms.append(term)
        return terms[:6]

    def _keyword_terms(self, question: str) -> list[str]:
        """处理关键词术语集合。"""
        stopwords = {
            "请问",
            "这个",
            "那个",
            "一个",
            "帮我",
            "看看",
            "根据",
            "文件",
            "报告",
            "什么",
            "哪个",
            "哪些",
            "多少",
            "如何",
            "是否",
            "是不是",
            "的是",
            "了吗",
            "吗",
            "呢",
            "啊",
        }
        terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9%\.]{2,30}", question)
        cleaned: list[str] = []
        for term in terms:
            value = term.strip()
            if value in stopwords:
                continue
            if any(value in org for org in self._org_phrases(question)):
                continue
            if value not in cleaned:
                cleaned.append(value)
        return cleaned[:10]

    def _generic_table_fields(self, question: str) -> list[str]:
        """处理generic表格字段列表。"""
        fields: list[str] = []
        if any(term in question for term in ("金额", "资金", "收入", "利润", "费用", "成本", "价格")):
            fields.extend(["金额", "单位"])
        if any(term in question for term in ("比例", "占比", "持股", "增长率", "比率")):
            fields.extend(["比例", "占比"])
        if any(term in question for term in ("数量", "股数", "人数", "次数")):
            fields.extend(["数量", "单位"])
        if any(term in question for term in ("关系", "关联方", "控制")):
            fields.extend(["名称", "关系"])
        if any(term in question for term in ("项目", "用途", "工程")):
            fields.extend(["项目", "名称"])
        if any(term in question for term in ("时间", "日期", "年度", "年份", "报告期")):
            fields.extend(["日期", "期间"])
        return list(dict.fromkeys(fields))

    def _terms_from_queries(self, queries: list[str]) -> list[str]:
        """处理术语集合from查询集合。"""
        terms: list[str] = []
        for query in queries:
            terms.extend(self._important_terms(query))
        return list(dict.fromkeys(terms))

    def _important_terms(self, question: str) -> list[str]:
        """处理关键术语术语集合。"""
        terms: list[str] = []
        for org in self._org_phrases(question):
            terms.append(org)
            terms.extend(self._org_aliases(org))
        anchor_title = self._evidence_anchor_title(question)
        if anchor_title:
            terms.append(anchor_title)
        for year in _YEAR_RE.findall(question):
            terms.append(re.sub(r"\s+", "", year))
        for term in _DOMAIN_TERMS:
            if term in question:
                terms.append(term)
        return list(dict.fromkeys(terms))

    def _org_phrases(self, question: str) -> list[str]:
        """处理机构名phrases。"""
        phrases: list[str] = []
        for match in _ORG_RE.findall(question):
            phrase = re.sub(r"^(与|和|关于|有关|报告期内|请问)+", "", match.strip())
            if phrase and phrase not in phrases:
                phrases.append(phrase)
        return phrases

    def _org_aliases(self, org: str) -> list[str]:
        """处理机构名aliases。"""
        compact = org.strip()
        aliases: list[str] = []
        suffixes = ("股份有限公司", "有限责任公司", "有限公司", "公司")
        for suffix in suffixes:
            if compact.endswith(suffix):
                short = compact[: -len(suffix)]
                break
        else:
            short = compact

        for city in ("武汉", "湖北", "上海", "北京", "深圳", "广州"):
            if short.startswith(city) and len(short) > len(city) + 1:
                short = short[len(city) :]
                break
        if short and short != compact:
            aliases.append(short)
        return aliases

    def _append_variant(self, variants: list[str], text: str) -> None:
        """追加查询变体。"""
        compact = re.sub(r"\s+", " ", text or "").strip(" ，；。")
        if compact and compact not in variants:
            variants.append(compact)

    def _strip_source_scope(self, question: str) -> str:
        """去除来源限定范围限定。"""
        text = re.sub(r"\s+", " ", question).strip()
        if not text:
            return ""

        clauses = re.split(r"[，。；]\s*", text)
        for index in range(1, len(clauses)):
            prefix = "，".join(part for part in clauses[:index] if part).strip()
            suffix = "，".join(part for part in clauses[index:] if part).strip()
            if (
                suffix
                and len(suffix) >= 8
                and self._looks_like_source_scope(prefix)
                and self._looks_like_answer_bearing(suffix)
            ):
                return suffix

        match = re.match(
            r"^(?P<prefix>.*?(?:招股意向书|招股说明书|招股书|募集说明书|年报|半年报|季报|公告|报告|文件|资料|文档|手册|说明书).{0,16}?[中内里])(?P<suffix>.+)$",
            text,
        )
        if match:
            suffix = match.group("suffix").lstrip("，。； ")
            if self._looks_like_answer_bearing(suffix):
                return suffix
        return ""

    def _strip_org_prefix(self, question: str) -> str:
        """去除机构名前缀。"""
        text = re.sub(r"\s+", " ", question).strip()
        if not text:
            return ""

        lead_removed = re.sub(
            r"^(?:报告期内[，]?\s*|根据[^，]{0,30}[，]?\s*|从[^，]{0,30}[，]?\s*)",
            "",
            text,
        ).strip()
        if not lead_removed or len(lead_removed) < 6:
            lead_removed = text

        org_match = _ORG_RE.match(lead_removed)
        if not org_match:
            return ""

        org_name = org_match.group(0)
        if re.match(r"^(没有|某|该|本|这个|那个|这家|那家)", org_name):
            return ""
        suffix = lead_removed[len(org_name) :].lstrip("，。； ")
        if not suffix or len(suffix) < 6:
            return ""

        if self._looks_like_answer_bearing(suffix):
            return suffix
        return ""

    def _looks_like_source_scope(self, text: str) -> bool:
        """判断来源限定范围限定是否成立。"""
        compact = text.strip()
        if not compact:
            return False
        has_org = bool(self._org_phrases(compact))
        has_source_term = any(term in compact for term in _SOURCE_SCOPE_TERMS)
        ends_like_scope = compact.endswith(("中", "内", "里")) and not self._contains_evidence_anchor(compact)
        return has_org or has_source_term or ends_like_scope

    def _looks_like_answer_bearing(self, text: str) -> bool:
        """判断回答bearing是否成立。"""
        compact = text.strip()
        if len(compact) < 6:
            return False
        return (
            any(term in compact for term in _QUESTION_HINT_TERMS)
            or self._contains_evidence_anchor(compact)
            or "？" in compact
            or "?" in compact
        )

    def _evidence_anchor_title(self, question: str) -> str:
        """处理证据锚点锚点标题。"""
        text = re.sub(r"\s+", " ", question).strip()
        patterns = (
            r"(?:从|根据|对照|结合)?(?P<title>[\u4e00-\u9fffA-Za-z0-9（）()、《》“”\"'·\-\s]{4,80}?(?:图表|增长图|趋势图|柱状图|折线图|饼图|示意图|流程图|结构图|图片|图|表格|表)(?:中|内|里|上|可见|可以看出)?)",
            r"(?P<title>[\u4e00-\u9fffA-Za-z0-9（）()、《》“”\"'·\-\s]{4,80}?(?:图表|增长图|趋势图|柱状图|折线图|饼图|示意图|流程图|结构图|图片|图|表格|表)(?:显示|反映|可以看出|可见))",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            title = re.sub(r"\s+", " ", match.group("title")).strip(" ，；。")
            if title and not self._looks_like_source_scope(title):
                return title
        return ""

    def _contains_visual_anchor(self, text: str) -> bool:
        """判断是否包含图片证据锚点。"""
        return any(term in text for term in _VISUAL_HINT_TERMS)

    def _contains_table_anchor(self, text: str) -> bool:
        """判断是否包含表格锚点。"""
        return any(term in text for term in _TABLE_HINT_TERMS)

    def _contains_evidence_anchor(self, text: str) -> bool:
        """判断是否包含证据锚点锚点。"""
        return self._contains_visual_anchor(text) or self._contains_table_anchor(text)

    def _has_source_scope(self, question: str) -> bool:
        """判断是否具备来源限定范围限定。"""
        return bool(self._strip_source_scope(question))
