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
    def _query_variants(self, question: str) -> list[str]:
        if not self.settings.query_rewrite_enabled:
            return [question]
        try:
            return self._llm_query_variants(question)
        except Exception:
            logger.exception("LLM query rewrite failed, fallback to conservative variants")
        return self._fallback_query_variants(question)

    def _llm_query_variants(self, question: str) -> list[str]:
        system_prompt = ""
        user_prompt = (
            "你是 RAG 查询改写器。请把下面的问题改写成 2-3 条更适合向量检索的查询：\n"
            "【核心规则】如果原问题以机构名(XX公司/XX有限公司/XX股份有限公司等)开头,"
            "且去掉该机构名后剩余部分仍是一个语义完整的独立问题,"
            "则第一条查询必须是不含该机构名的核心问法(直接问「什么/哪个/多少/如何」等),"
            "因为长机构名会稀释 embedding 向量中的问题信号,导致检索不准。\n"
            "1) 第一条:去掉机构名/来源限定后的核心问法(只保留问题本身,不含公司名/文件名/报告名);\n"
            "2) 第二条:保留必要限定条件的完整查询(机构名尽量用简称);\n"
            "3) 第三条(可选):纯关键词组合,用于 BM25 精确匹配。\n"
            "优先保留字段、数字、时间、比较关系、否定条件和图表标题等证据锚点;"
            "不要引入原问题没有的新事实、新数字、新专有名词或新结论;"
            "只输出 JSON,格式为 {\"queries\":[\"...\",\"...\",\"...\"]}。"
            f"\n原问题：{question}"
        )
        raw = self.llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
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
                if len(variants) >= 3:
                    break

        # 如果 LLM 改写不足 2 个变体，用规则兜底补充
        while len(variants) < 2:
            fallback = self._best_fallback_rewrite(question)
            if fallback and fallback != question:
                self._append_variant(variants, fallback)
            else:
                break

        return variants[:3]

    def _is_safe_rewrite(self, question: str, rewrite: str) -> bool:
        if len(rewrite) > 240:
            return False
        question_numbers = set(re.findall(r"\d+(?:[.,]\d+)?%?", question))
        rewrite_numbers = set(re.findall(r"\d+(?:[.,]\d+)?%?", rewrite))
        if not rewrite_numbers <= question_numbers:
            return False
        if "《" in rewrite and "《" not in question:
            return False
        protected_negations = ("不存在", "未", "没有", "无")
        for negation in protected_negations:
            if negation in question and negation not in rewrite:
                return False
        return True

    def _parse_rewrite_response(self, raw: str) -> list[str]:
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
        variants = [question]
        # 优先尝试去机构名（最有利于语义检索）
        stripped_org = self._strip_org_prefix(question)
        self._append_variant(variants, stripped_org)
        # 再尝试去来源范围（招股书等限定）
        stripped_source = self._strip_source_scope(question)
        self._append_variant(variants, stripped_source)
        # 最后用关键词组合兜底
        fallback = self._best_fallback_rewrite(question)
        self._append_variant(variants, fallback)
        return variants[:3]

    def _best_fallback_rewrite(self, question: str) -> str:
        stripped_source = self._strip_source_scope(question)
        stripped_org = self._strip_org_prefix(question)
        # 去掉机构名后的纯问题是最优检索变体，优先返回
        if stripped_org and stripped_org != question:
            return stripped_org
        if stripped_source and stripped_source != question:
            return stripped_source

        orgs = self._org_phrases(question)
        aliases: list[str] = []
        for org in orgs:
            aliases.extend(self._org_aliases(org))
        subject_terms = [*orgs, *aliases]
        important_terms = self._important_terms(question)
        keyword_terms = self._keyword_terms(stripped_source or question)
        focus_terms = self._question_focus_terms(stripped_source or question)
        constraints = self._essential_constraints(question)
        anchor_title = self._evidence_anchor_title(question)

        candidates: list[str] = []
        if stripped_source:
            candidates.append(stripped_source)

        base_terms = [*focus_terms, *subject_terms, *important_terms, *constraints, *keyword_terms]
        candidates.append(" ".join(dict.fromkeys(term for term in base_terms if term)))

        if anchor_title:
            anchor_terms = [anchor_title, *focus_terms, *constraints, *keyword_terms]
            candidates.append(" ".join(dict.fromkeys(term for term in anchor_terms if term)))

        if any(term in question for term in ("什么", "哪个", "哪些", "多少", "是否", "如何")):
            candidates.append(
                " ".join(
                    dict.fromkeys(term for term in [*focus_terms, *subject_terms, *keyword_terms] if term)
                )
            )

        candidates.append(self._compact_focus_query(stripped_source or question))
        for candidate in candidates:
            compact = re.sub(r"\s+", " ", candidate or "").strip()
            if compact and compact != question:
                return compact
        return ""

    def _compact_focus_query(self, question: str) -> str:
        focus_terms = self._question_focus_terms(question)
        constraints = self._essential_constraints(question)
        anchor_title = self._evidence_anchor_title(question)
        terms = [anchor_title or "", *focus_terms, *constraints]
        return " ".join(dict.fromkeys(term for term in terms if term)).strip()

    def _essential_constraints(self, question: str) -> list[str]:
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
            "呢",
            "啊",
            "呀",
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
        terms: list[str] = []
        for query in queries:
            terms.extend(self._important_terms(query))
        return list(dict.fromkeys(terms))

    def _important_terms(self, question: str) -> list[str]:
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
        phrases: list[str] = []
        for match in _ORG_RE.findall(question):
            phrase = re.sub(r"^(与|和|及|关于|有关|报告期内|请问)+", "", match.strip())
            if phrase and phrase not in phrases:
                phrases.append(phrase)
        return phrases

    def _org_aliases(self, org: str) -> list[str]:
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
        compact = re.sub(r"\s+", " ", text or "").strip(" ，,;；:：")
        if compact and compact not in variants:
            variants.append(compact)

    def _strip_source_scope(self, question: str) -> str:
        text = re.sub(r"\s+", " ", question).strip()
        if not text:
            return ""

        clauses = re.split(r"[，,；;：:]\s*", text)
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
            suffix = match.group("suffix").lstrip("，,；;：: ")
            if self._looks_like_answer_bearing(suffix):
                return suffix
        return ""

    def _strip_org_prefix(self, question: str) -> str:
        """如果问题以机构名（公司/有限公司等）开头且剩余部分语义完整，去掉机构名。

        "武汉兴图新科电子股份有限公司参与制定了哪个技术标准？"
        → "参与制定了哪个技术标准？"
        """
        text = re.sub(r"\s+", " ", question).strip()
        if not text:
            return ""

        # 先去掉句首常见的来源/时间限定前缀，再检查是否跟机构名
        lead_removed = re.sub(
            r"^(?:报告期内[，,]?\s*|根据[^，,]{0,30}?[，,]?\s*|从[^，,]{0,30}?[，,]?\s*)",
            "",
            text,
        ).strip()
        if not lead_removed or len(lead_removed) < 6:
            lead_removed = text

        # 检查开头是否是机构名
        org_match = _ORG_RE.match(lead_removed)
        if not org_match:
            return ""

        org_name = org_match.group(0)
        # 排除伪机构名: "没有公司" "某公司" "该公司" "本公司" 等泛称
        if re.match(r"^(没有|某|该|本|这|那|一家|这家|那家)", org_name):
            return ""
        suffix = lead_removed[len(org_name):].lstrip("，,；;：: ")
        if not suffix or len(suffix) < 6:
            return ""

        # 剩余部分必须像一个可独立回答的问题
        if self._looks_like_answer_bearing(suffix):
            return suffix
        return ""

    def _looks_like_source_scope(self, text: str) -> bool:
        compact = text.strip()
        if not compact:
            return False
        has_org = bool(self._org_phrases(compact))
        has_source_term = any(term in compact for term in _SOURCE_SCOPE_TERMS)
        ends_like_scope = compact.endswith(("中", "内", "里")) and not self._contains_evidence_anchor(compact)
        return has_org or has_source_term or ends_like_scope

    def _looks_like_answer_bearing(self, text: str) -> bool:
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
        text = re.sub(r"\s+", " ", question).strip()
        patterns = (
            r"(?:从|根据|在|对照|结合)?(?P<title>[\u4e00-\u9fffA-Za-z0-9（）()《》""\"'·\-\s]{4,80}?(?:图表|增长图|趋势图|柱状图|折线图|饼图|示意图|流程图|结构图|图片|图|表格|表))(?:中|内|里|上|可见|可以看出)?",
            r"(?P<title>[\u4e00-\u9fffA-Za-z0-9（）()《》""\"'·\-\s]{4,80}?(?:图表|增长图|趋势图|柱状图|折线图|饼图|示意图|流程图|结构图|图片|图|表格|表))(?:显示|反映|可以看出|可见)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            title = re.sub(r"\s+", " ", match.group("title")).strip(" ，,；;：:")
            if title and not self._looks_like_source_scope(title):
                return title
        return ""

    def _contains_visual_anchor(self, text: str) -> bool:
        return any(term in text for term in _VISUAL_HINT_TERMS)

    def _contains_table_anchor(self, text: str) -> bool:
        return any(term in text for term in _TABLE_HINT_TERMS)

    def _contains_evidence_anchor(self, text: str) -> bool:
        return self._contains_visual_anchor(text) or self._contains_table_anchor(text)

    def _has_source_scope(self, question: str) -> bool:
        return bool(self._strip_source_scope(question))
