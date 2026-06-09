from __future__ import annotations

from app.models.domain import SearchHit

_ENUMERATION_TERMS = (
    "哪些",
    "哪几",
    "分别",
    "列出",
    "包括",
    "清单",
    "名单",
)

_VISUAL_DETAIL_TERMS = (
    "图",
    "图中",
    "图里",
    "图上",
    "图片",
    "图表",
    "配图",
    "示意图",
    "流程图",
    "结构图",
    "架构图",
    "关系图",
)

_CHART_TERMS = (
    "图表",
    "曲线",
    "柱状图",
    "折线图",
    "饼图",
    "趋势图",
)


class RagRankingMixin:
    def _soft_rank(
        self, question: str, intent: str, hits: list[SearchHit]
    ) -> list[SearchHit]:
        return self._rank_hits(question, intent, hits, stage="soft")

    def _final_rank(
        self, question: str, intent: str, hits: list[SearchHit]
    ) -> list[SearchHit]:
        return self._rank_hits(question, intent, hits, stage="final")

    def _rank_hits(
        self,
        question: str,
        intent: str,
        hits: list[SearchHit],
        *,
        stage: str,
    ) -> list[SearchHit]:
        if not hits:
            return []
        scale = self._rank_score_scale(hits)
        enumerative = self._is_enumeration_question(question)
        ranking_terms = self._ranking_terms(question)
        ranked: list[SearchHit] = []
        for hit in hits:
            base_score = float(hit.score)
            structure_bonus = self._structure_bonus(
                question,
                intent,
                hit,
                stage=stage,
                enumerative=enumerative,
                ranking_terms=ranking_terms,
            )
            metadata = dict(hit.metadata or {})
            adjusted_score = base_score + structure_bonus * scale
            metadata[f"{stage}_rank_base_score"] = base_score
            metadata[f"{stage}_rank_structure_bonus"] = float(structure_bonus)
            metadata[f"{stage}_rank_score"] = float(adjusted_score)
            hit.metadata = metadata
            hit.score = adjusted_score
            ranked.append(hit)
        return sorted(
            ranked,
            key=lambda item: (item.score, self._rank_tiebreak(item)),
            reverse=True,
        )

    def _structure_bonus(
        self,
        question: str,
        intent: str,
        hit: SearchHit,
        *,
        stage: str,
        enumerative: bool,
        ranking_terms: list[str],
    ) -> float:
        metadata = hit.metadata or {}
        content_type = str(metadata.get("type") or "").lower()
        if content_type == "image":
            return self._image_bonus(
                question,
                intent,
                hit,
                stage=stage,
                ranking_terms=ranking_terms,
            )
        if content_type == "table":
            return self._table_bonus(
                question,
                intent,
                hit,
                stage=stage,
                ranking_terms=ranking_terms,
            )
        if content_type != "text":
            return 0.0

        heading = str(metadata.get("heading") or "")
        chapter = str(metadata.get("chapter") or "")
        section = str(metadata.get("section") or "")
        document_title = str(metadata.get("document_title") or "")

        heading_hits = self._term_hit_count(heading, ranking_terms)
        section_hits = self._term_hit_count(section, ranking_terms)
        chapter_hits = self._term_hit_count(chapter, ranking_terms)
        document_title_hits = self._term_hit_count(document_title, ranking_terms)
        heading_match_hits = heading_hits + section_hits + chapter_hits

        bonus = 0.0
        bonus += min(heading_hits * 0.06, 0.18)
        bonus += min(section_hits * 0.05, 0.12)
        bonus += min(chapter_hits * 0.04, 0.08)
        bonus += min(document_title_hits * 0.03, 0.06)

        heading_level = int(metadata.get("heading_level") or 0)
        if heading_match_hits and heading_level > 0:
            bonus += 0.02 * min(heading_level, 2)
        if heading_match_hits and bool(metadata.get("is_heading_lead")):
            bonus += 0.05 if stage == "soft" else 0.035
        if (
            int(metadata.get("heading_chunk_index") or 0) == 0
            and heading_level > 0
            and (heading_match_hits > 0 or document_title_hits > 0)
        ):
            bonus += 0.015

        if enumerative and bool(metadata.get("is_list_chunk")):
            bonus += 0.045
        if intent in {"table_lookup", "table"} and bool(metadata.get("is_list_chunk")):
            bonus += 0.02

        paragraph_count = int(metadata.get("paragraph_count") or 0)
        if 1 <= paragraph_count <= 3:
            bonus += 0.015
        elif paragraph_count >= 6:
            bonus -= 0.015

        short_paragraph_count = int(metadata.get("short_paragraph_count") or 0)
        if bool(metadata.get("merged_short_paragraphs")) and not heading_match_hits:
            bonus -= min(short_paragraph_count * 0.01, 0.03)

        chunk_char_length = int(metadata.get("chunk_char_length") or 0)
        if chunk_char_length >= max(self.settings.chunk_size - 40, 1):
            bonus -= 0.01

        if stage == "final":
            bonus *= 0.7
        return bonus

    def _table_bonus(
        self,
        question: str,
        intent: str,
        hit: SearchHit,
        *,
        stage: str,
        ranking_terms: list[str],
    ) -> float:
        metadata = hit.metadata or {}
        caption = str(metadata.get("table_caption") or "").strip()
        header = metadata.get("table_header")
        header_text = ""
        if isinstance(header, list):
            header_text = " ".join(str(cell).strip() for cell in header if str(cell).strip())
        text = hit.text or ""
        anchor_title = self._evidence_anchor_title(question)

        caption_hits = self._term_hit_count(caption, ranking_terms)
        header_hits = self._term_hit_count(header_text, ranking_terms)
        document_title_hits = self._term_hit_count(
            str(metadata.get("document_title") or "").strip(), ranking_terms
        )

        bonus = 0.0
        if intent in {"table_lookup", "table"}:
            bonus += 0.16 if stage == "soft" else 0.11
        bonus += min(caption_hits * 0.08, 0.24)
        bonus += min(header_hits * 0.06, 0.18)
        bonus += min(document_title_hits * 0.03, 0.06)

        if anchor_title:
            if anchor_title in caption:
                bonus += 0.14
            elif anchor_title in header_text:
                bonus += 0.09
            elif anchor_title in text:
                bonus += 0.05

        row_count = int(metadata.get("table_row_count") or 0)
        if 1 <= row_count <= 8:
            bonus += 0.02

        if stage == "final":
            bonus *= 0.7
        return bonus

    def _image_bonus(
        self,
        question: str,
        intent: str,
        hit: SearchHit,
        *,
        stage: str,
        ranking_terms: list[str],
    ) -> float:
        metadata = hit.metadata or {}
        caption = str(metadata.get("image_caption") or "").strip()
        image_kind = str(metadata.get("image_kind") or "").strip()
        text = hit.text or ""
        anchor_title = self._evidence_anchor_title(question)

        bonus = 0.0
        if intent == "visual_lookup":
            bonus += 0.18 if stage == "soft" else 0.12

        caption_hits = self._term_hit_count(caption, ranking_terms)
        bonus += min(caption_hits * 0.05, 0.15)

        if anchor_title:
            if anchor_title in caption:
                bonus += 0.12
            elif anchor_title in text:
                bonus += 0.06

        if any(term in question for term in _VISUAL_DETAIL_TERMS):
            bonus += 0.03
        if any(term in question for term in _CHART_TERMS) and "图表" in image_kind:
            bonus += 0.04
        if any(term in question for term in ("架构图", "流程图", "关系图", "示意图")):
            if any(term in text for term in ("主要元素", "关系与方向", "节点", "箭头")):
                bonus += 0.04

        if stage == "final":
            bonus *= 0.7
        return bonus

    def _ranking_terms(self, question: str) -> list[str]:
        terms: list[str] = []
        for term in (
            self._important_terms(question)
            + self._question_focus_terms(question)
            + self._keyword_terms(question)
        ):
            compact = str(term or "").strip()
            if len(compact) < 2 or compact in terms:
                continue
            terms.append(compact)
        return terms[:16]

    def _term_hit_count(self, text: str, terms: list[str]) -> int:
        compact = str(text or "").strip()
        if not compact:
            return 0
        return sum(1 for term in terms if term and term in compact)

    def _is_enumeration_question(self, question: str) -> bool:
        return any(term in question for term in _ENUMERATION_TERMS)

    def _rank_score_scale(self, hits: list[SearchHit]) -> float:
        peak = max((abs(float(hit.score)) for hit in hits), default=0.0)
        return min(max(peak, 0.02), 1.0)

    def _rank_tiebreak(self, hit: SearchHit) -> float:
        metadata = hit.metadata or {}
        if str(metadata.get("type") or "").lower() == "image":
            caption = str(metadata.get("image_caption") or "").strip()
            return 20.0 + (2.0 if caption else 0.0)
        if str(metadata.get("type") or "").lower() == "table":
            caption = str(metadata.get("table_caption") or "").strip()
            header = metadata.get("table_header")
            header_count = len(header) if isinstance(header, list) else 0
            return 15.0 + (2.0 if caption else 0.0) + min(header_count * 0.1, 1.0)
        heading_lead = 1.0 if metadata.get("is_heading_lead") else 0.0
        heading_level = float(metadata.get("heading_level") or 0.0)
        heading_index = float(metadata.get("heading_chunk_index") or 0.0)
        list_chunk = 1.0 if metadata.get("is_list_chunk") else 0.0
        return heading_lead * 10.0 + heading_level + list_chunk * 0.5 - heading_index * 0.01
