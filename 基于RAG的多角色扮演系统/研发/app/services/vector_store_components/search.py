from pymilvus import AnnSearchRequest, RRFRanker, WeightedRanker

from app.core.config import LONG_TERM_MEMORY_TOP_K, TOP_K
from app.core.logging_utils import get_logger
from app.services.data_loader import clean_name


logger = get_logger(__name__)


class VectorStoreSearchMixin:

    def _diversify_ranked_results(self, results, top_k: int):
        if top_k <= 0 or not results:
            return []

        selected = []

        overflow = []
        parent_counts = {}

        for result in results:
            parent_id = self._build_parent_id(result)
            if parent_counts.get(parent_id, 0) >= 1:
                overflow.append(result)
                continue
            selected.append(result)
            parent_counts[parent_id] = parent_counts.get(parent_id, 0) + 1
            if len(selected) >= top_k:
                return selected

        for result in overflow:
            selected.append(result)
            if len(selected) >= top_k:
                break
        return selected

    def _build_access_expr(self, character_name: str = None) -> str:
        expressions = []
        for access_key in self._resolve_access_keys(character_name):
            escaped_access_key = self._escape_filter_value(access_key)
            expressions.append(f"access_key == '{escaped_access_key }'")
        return " or ".join(expressions) if expressions else ""

    def _search_output_fields(self):
        return [
            "name",
            "message",
            "source_file",
            "parent_id",
            "source_title",
            "chunk_index",
            "chunk_count",
            "knowledge_scope",
            "scope_key",
            "access_key",
            "original_name",
            "source_kind",
        ]

    def _hit_to_payload(self, hit, fallback_access_key: str = "shared"):
        entity = hit.get("entity", {})
        return {
            "name": entity.get("name", ""),
            "message": entity.get("message", ""),
            "source_file": entity.get("source_file", ""),
            "parent_id": entity.get("parent_id", ""),
            "source_title": entity.get("source_title", ""),
            "chunk_index": int(entity.get("chunk_index", 0) or 0),
            "chunk_count": int(entity.get("chunk_count", 1) or 1),
            "knowledge_scope": entity.get("knowledge_scope", "shared"),
            "scope_key": entity.get("scope_key", ""),
            "access_key": entity.get("access_key", fallback_access_key),
            "original_name": entity.get("original_name", ""),
            "source_kind": entity.get("source_kind", ""),
            "score": float(
                hit.get("distance", hit.get("score", entity.get("score", 0.0))) or 0.0
            ),
        }

    def _apply_result_boosts(self, results, query: str, character_name: str = None):
        normalized_query = self._normalize_match_text(query)
        query_terms = set(self._tokenize(query))

        for result in results:
            normalized_name = self._normalize_match_text(result.get("name", ""))
            name_terms = set(self._tokenize(result.get("name", "")))

            if character_name and result.get("name") == character_name:
                result["score"] += 0.12

            if (
                result.get("access_key")
                == f"private::{clean_name (character_name or '')}"
            ):
                result["score"] += 0.04

            if normalized_name and normalized_name in normalized_query:
                result["score"] += 0.18

            if query_terms and name_terms:
                overlap_ratio = len(query_terms & name_terms) / max(1, len(name_terms))
                result["score"] += min(0.12, overlap_ratio * 0.12)

        return sorted(results, key=lambda item: item["score"], reverse=True)

    def _vector_search(
        self, query: str, top_k: int = TOP_K, character_name: str = None
    ):
        if not self.client.has_collection(self.collection_name):
            return []

        query_embedding = self.embedding_model.encode([query])
        expr = self._build_access_expr(character_name)
        results = self.client.search(
            collection_name=self.collection_name,
            data=query_embedding,
            anns_field="vector",
            limit=top_k,
            search_params={
                "metric_type": "COSINE",
                "params": {"nprobe": self.search_nprobe},
            },
            filter=expr,
            output_fields=self._search_output_fields(),
        )
        ranked = [self._hit_to_payload(hit) for hit in results[0]]
        ranked = self._apply_result_boosts(ranked, query, character_name=character_name)
        logger.info(
            "向量检索完成: 查询=%r 角色=%r 结果=%s",
            query,
            character_name,
            [
                {
                    "name": item.get("name", ""),
                    "score": round(float(item.get("score", 0.0) or 0.0), 6),
                    "text": (item.get("message", "") or "")[:120],
                }
                for item in ranked
            ],
        )
        return ranked

    def hybrid_search(
        self,
        query: str,
        top_k: int = TOP_K,
        character_name: str = None,
        query_embedding=None,
    ):
        if not self.client.has_collection(self.collection_name):
            return []

        candidate_limit = max(top_k * 5, top_k + 8)
        if query_embedding is None:
            query_embedding = self.embedding_model.encode([query])[0]
        expr = self._build_access_expr(character_name)

        dense_request = AnnSearchRequest(
            data=[query_embedding],
            anns_field="vector",
            param={
                "metric_type": "COSINE",
                "params": {"nprobe": self.search_nprobe},
            },
            limit=candidate_limit,
            expr=expr,
        )
        sparse_request = AnnSearchRequest(
            data=[query],
            anns_field="sparse",
            param={"metric_type": "BM25", "params": {}},
            limit=candidate_limit,
            expr=expr,
        )
        ranker = (
            RRFRanker()
            if self.hybrid_reranker == "rrf"
            else WeightedRanker(self.vector_weight, self.bm25_weight)
        )
        raw_results = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_request, sparse_request],
            ranker=ranker,
            limit=candidate_limit,
            output_fields=self._search_output_fields(),
        )

        deduped = {}
        for hit in raw_results[0]:
            payload = self._hit_to_payload(hit)
            key = self._build_document_key(payload)
            previous = deduped.get(key)
            if previous is None or payload["score"] > previous["score"]:
                deduped[key] = payload

        ranked = self._apply_result_boosts(
            list(deduped.values()),
            query,
            character_name=character_name,
        )
        logger.info(
            "混合检索完成: 查询=%r 角色=%r 结果=%s",
            query,
            character_name,
            [
                {
                    "name": item.get("name", ""),
                    "score": round(float(item.get("score", 0.0) or 0.0), 6),
                    "text": (item.get("message", "") or "")[:120],
                }
                for item in ranked
            ],
        )
        return self._diversify_ranked_results(ranked, top_k=top_k)

    def search_conversations(
        self, query: str, session_id: str, top_k: int = LONG_TERM_MEMORY_TOP_K
    ):
        query_embedding = self.embedding_model.encode([query])

        escaped_session_id = self._escape_filter_value(session_id)

        results = self.client.search(
            collection_name=self.conversation_collection_name,
            data=query_embedding,
            filter=f"session_id == '{escaped_session_id }'",
            limit=top_k,
            output_fields=[
                "user_message",
                "assistant_message",
                "character_name",
                "timestamp",
            ],
        )

        search_results = [
            {
                "user_message": hit["entity"]["user_message"],
                "assistant_message": hit["entity"]["assistant_message"],
                "character_name": hit["entity"].get("character_name", ""),
                "timestamp": hit["entity"]["timestamp"],
                "score": hit["distance"],
            }
            for hit in results[0]
        ]

        return sorted(search_results, key=lambda item: item["timestamp"])
