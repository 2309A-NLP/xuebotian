from __future__ import annotations

from app.models.domain import SearchHit


class RagRetrievalMixin:
    """提供向量检索结果的聚合和多模态补召回逻辑。"""
    def _search(
        self,
        query_vectors: list[list[float]],
        query_variants: list[str],
        question: str,
        intent: str,
        target_top_k: int,
        doc_ids: list[str] | None,
    ) -> list[SearchHit]:
        # 增大单路召回量，确保多路合并后有足够的候选进入 rerank
        """执行多查询检索、去重并返回排序前候选结果。"""
        candidate_top_k = max(self.settings.recall_candidate_count, target_top_k * 12)
        merged: dict[str, SearchHit] = {}

        for query_text, query_vector in zip(query_variants, query_vectors, strict=False):
            hits = self.vector_store.search(
                embedding=query_vector,
                top_k=candidate_top_k,
                doc_ids=doc_ids,
                query_text=query_text,
            )
            for hit in hits:
                hit.metadata.setdefault("matched_queries", [])
                hit.metadata["matched_queries"].append(query_text)
                existing = merged.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    merged[hit.chunk_id] = hit

        candidates = self._soft_rank(question, intent, list(merged.values()))
        # 放宽 rerank 候选池：取 max(target_top_k*15, min(200, len(candidates)))
        rerank_limit = min(max(target_top_k * 20, min(200, len(candidates))), len(candidates))
        candidates = candidates[:rerank_limit]
        # rerank 后保留更多候选给最终排序
        reranked_top_k = min(max(target_top_k * 8, target_top_k * 2), len(candidates))
        reranked = self.reranker.rerank(question, candidates, reranked_top_k)
        finalized = self._final_rank(question, intent, reranked)
        return self._append_modal_hits(finalized, target_top_k)

    def _append_modal_hits(self, hits: list[SearchHit], target_top_k: int) -> list[SearchHit]:
        """追加多模态命中结果命中结果列表。"""
        base_limit = min(max(int(target_top_k), 0), len(hits))
        if base_limit <= 0:
            return []

        selected = list(hits[:base_limit])
        selected_ids = {hit.chunk_id for hit in selected}
        extras: list[SearchHit] = []

        for required_type in ("table", "image"):
            extra_hit = next(
                (
                    hit
                    for hit in hits[base_limit:]
                    if self._hit_content_type(hit) == required_type and hit.chunk_id not in selected_ids
                ),
                None,
            )
            if extra_hit is None:
                continue
            extras.append(extra_hit)
            selected_ids.add(extra_hit.chunk_id)

        return selected + extras

    def _hit_content_type(self, hit: SearchHit) -> str:
        """处理命中结果内容type。"""
        return str((hit.metadata or {}).get("type") or "").strip().lower()
