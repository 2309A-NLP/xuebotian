from __future__ import annotations

from app.models.domain import SearchHit


class RagRankingMixin:
    def _soft_rank(
        self, question: str, intent: str, hits: list[SearchHit]
    ) -> list[SearchHit]:
        if not hits:
            return hits

        orgs = self._org_phrases(question)
        terms = self._important_terms(question)
        anchor_title = self._evidence_anchor_title(question)
        has_source_scope = self._has_source_scope(question)

        def adjusted_score(hit: SearchHit) -> float:
            score = hit.score
            text = hit.text
            metadata = hit.metadata or {}
            content_type = str(metadata.get("type", "")).lower()
            lexical_score = float(metadata.get("lexical_score", 0.0))
            if lexical_score:
                score += min(lexical_score * 0.08, 0.5)

            org_boost = 0.04 if has_source_scope else 0.10
            if orgs and any(org in text for org in orgs):
                score += org_boost

            if anchor_title and anchor_title in text:
                score += 0.18

            if intent == "table_lookup":
                if content_type == "table" or "表头：" in text or "第" in text and "行：" in text:
                    score += 0.08
                if metadata.get("table_caption"):
                    score += 0.02
            elif intent == "visual_lookup":
                if content_type == "image":
                    score += 0.18
                if metadata.get("image_caption"):
                    score += 0.05
                if any(token in text for token in ("Caption:", "Description:", "图片", "图中", "曲线")):
                    score += 0.04

            for term in terms:
                if term and term in text:
                    score += 0.015

            asks_existing_control = (
                "存在控制关系" in question and "不存在控制关系" not in question
            )
            if asks_existing_control and "不存在控制关系" in text:
                score -= 0.35
            if asks_existing_control and "表格：八、存在控制关系的关联方" in text:
                score += 0.35
            if "不存在控制关系" in question and "关联方" in question:
                if "表格：九、不存在控制关系的关联方" in text:
                    score += 0.45
                if "表格：八、存在控制关系的关联方" in text:
                    score -= 0.35
            return score

        return sorted(hits, key=adjusted_score, reverse=True)

    def _final_rank(
        self, question: str, intent: str, hits: list[SearchHit]
    ) -> list[SearchHit]:
        orgs = self._org_phrases(question)
        terms = self._important_terms(question)
        anchor_title = self._evidence_anchor_title(question)
        has_source_scope = self._has_source_scope(question)

        def final_score(hit: SearchHit) -> float:
            metadata = hit.metadata or {}
            rerank_score = float(metadata.get("rerank_score", hit.score))
            vector_score = float(metadata.get("vector_score", hit.score))
            lexical_score = float(metadata.get("lexical_score", 0.0))
            text = hit.text
            score = rerank_score * 0.85 + vector_score * 0.10
            if lexical_score:
                score += min(lexical_score * 0.12, 0.8)

            org_boost = 0.03 if has_source_scope else 0.08
            for org in orgs:
                if org in text:
                    score += org_boost

            if anchor_title and anchor_title in text:
                score += 0.24

            for term in terms:
                if term and term in text:
                    score += 0.05

            if intent == "table_lookup":
                if "表头：" in text or "第" in text and "行：" in text:
                    score += 0.06
            elif intent == "visual_lookup":
                if str(metadata.get("type", "")).lower() == "image":
                    score += 0.20
                if metadata.get("image_caption"):
                    score += 0.06
                if any(token in text for token in ("Caption:", "Description:", "图片", "图中", "曲线")):
                    score += 0.05

            asks_existing_control = (
                "存在控制关系" in question
                and "不存在控制关系" not in question
                and "关联方" in question
            )
            if asks_existing_control:
                if "表格：八、存在控制关系的关联方" in text:
                    score += 0.45
                if "持股比例" in text and "与本公司关系" in text:
                    score += 0.25
                if "不存在控制关系" in text and "表格：八、存在控制关系的关联方" not in text:
                    score -= 0.50
            if "不存在控制关系" in question and "关联方" in question:
                if "表格：九、不存在控制关系的关联方" in text:
                    score += 0.60
                if "企业名称" in text and "与本公司关系" in text:
                    score += 0.25
                if "表格：八、存在控制关系的关联方" in text:
                    score -= 0.45

            metadata["final_score"] = score
            return score

        return sorted(hits, key=final_score, reverse=True)
