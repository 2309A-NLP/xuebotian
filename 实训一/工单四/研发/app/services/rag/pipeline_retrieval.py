from __future__ import annotations

from app.models.domain import SearchHit


class RagRetrievalMixin:
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
        return reranked[:target_top_k]
