from __future__ import annotations

import json
import logging
from typing import Any

try:
    from pymilvus import DataType, Function, FunctionType, MilvusClient
except ImportError:
    from pymilvus import DataType, MilvusClient

    Function = None
    FunctionType = None

from app.core.config import Settings
from app.models.domain import ChunkRecord, SearchHit
from app.services.vector.base import BaseVectorStore
from app.services.vector.memory_store import InMemoryVectorStore
from app.services.vector.milvus_helpers import MilvusHelperMixin

logger = logging.getLogger(__name__)

BM25_TEXT_FIELD_NAME = "bm25_text"
BM25_INDEX_FIELD_NAME = "bm25_keyword_index"

class MilvusVectorStore(MilvusHelperMixin, BaseVectorStore):
    """基于 Milvus 实现向量写入、混合检索与结果转换。"""
    def __init__(self, settings: Settings) -> None:
        """初始化Milvus 向量存储所需的依赖和运行参数。"""
        self.settings = settings
        self.collection_name = settings.vector_collection
        self._dimension: int | None = None
        self._loaded = False
        self._field_names: set[str] | None = None
        self.client = self._build_client()

    def _build_client(self) -> MilvusClient:
        """构建客户端。"""
        kwargs: dict[str, Any] = {"uri": self.settings.milvus_uri}
        if self.settings.milvus_token:
            kwargs["token"] = self.settings.milvus_token
        elif self.settings.milvus_user:
            kwargs["user"] = self.settings.milvus_user
            kwargs["password"] = self.settings.milvus_password
        client = MilvusClient(**kwargs)
        logger.info("Connected to Milvus: %s", self.settings.milvus_uri)
        return client

    def _ensure_collection(self, dimension: int) -> None:
        """确保集合已就绪。"""
        self._dimension = dimension
        if not self.client.has_collection(collection_name=self.collection_name):
            hybrid_capable = self._hybrid_capable()
            schema = MilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field(
                field_name="chunk_id",
                datatype=DataType.VARCHAR,
                max_length=128,
                is_primary=True,
            )
            schema.add_field(
                field_name="doc_id",
                datatype=DataType.VARCHAR,
                max_length=128,
            )
            schema.add_field(field_name="page", datatype=DataType.INT64)
            schema.add_field(field_name="page_end", datatype=DataType.INT64)
            schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
            schema.add_field(
                field_name="chunk_type",
                datatype=DataType.VARCHAR,
                max_length=32,
            )
            schema.add_field(
                field_name="source_file",
                datatype=DataType.VARCHAR,
                max_length=512,
            )
            schema.add_field(
                field_name="metadata_json",
                datatype=DataType.VARCHAR,
                max_length=4096,
            )
            schema.add_field(
                field_name="text",
                datatype=DataType.VARCHAR,
                max_length=65535,
            )
            if hybrid_capable:
                schema.add_field(
                    field_name=BM25_TEXT_FIELD_NAME,
                    datatype=DataType.VARCHAR,
                    max_length=65535,
                    enable_analyzer=True,
                )
            schema.add_field(
                field_name="embedding",
                datatype=DataType.FLOAT_VECTOR,
                dim=dimension,
            )
            if hybrid_capable:
                schema.add_field(
                    field_name=BM25_INDEX_FIELD_NAME,
                    datatype=DataType.SPARSE_FLOAT_VECTOR,
                )
                schema.add_function(
                    Function(
                        name="bm25_keyword_function",
                        input_field_names=[BM25_TEXT_FIELD_NAME],
                        output_field_names=[BM25_INDEX_FIELD_NAME],
                        function_type=FunctionType.BM25,
                    )
                )

            index_params = MilvusClient.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                index_name="embedding_ivf_flat_index",
                metric_type="COSINE",
                params={"nlist": 128},
            )
            if hybrid_capable:
                index_params.add_index(
                    field_name=BM25_INDEX_FIELD_NAME,
                    index_type="SPARSE_INVERTED_INDEX",
                    index_name="bm25_keyword_inverted_index",
                    metric_type="BM25",
                    params={
                        "inverted_index_algo": "DAAT_MAXSCORE",
                        "bm25_k1": 1.2,
                        "bm25_b": 0.75,
                    },
                )

            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
            )
            self.client.create_index(
                collection_name=self.collection_name,
                index_params=index_params,
            )
            logger.info(
                "Created Milvus collection: %s hybrid_bm25=%s",
                self.collection_name,
                hybrid_capable,
            )

        self._field_names = self._describe_fields()
        if not self._loaded:
            self.client.load_collection(
                collection_name=self.collection_name,
                replica_number=1,
            )
            self._loaded = True

    def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        """新增或更新切片集合。"""
        if not chunks:
            return
        self._ensure_collection(len(embeddings[0]))
        doc_ids = sorted({chunk.doc_id for chunk in chunks})
        self._delete_by_chunk_ids([chunk.chunk_id for chunk in chunks])

        records = []
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            record = {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "page": chunk.page,
                "page_end": chunk.page_end,
                "chunk_index": chunk.chunk_index,
                "chunk_type": str(chunk.metadata.get("type", "text"))[:32],
                "source_file": chunk.source_file,
                "metadata_json": self._metadata_json(chunk.metadata),
                "text": chunk.text[:65535],
                BM25_TEXT_FIELD_NAME: chunk.bm25_text[:65535],
                "embedding": embedding,
            }
            records.append(self._filter_record_fields(record))

        self.client.insert(collection_name=self.collection_name, data=records)
        self.client.flush(collection_name=self.collection_name)
        logger.info(
            "Upserted chunks into Milvus collection=%s docs=%s chunks=%s",
            self.collection_name,
            ",".join(doc_ids),
            len(chunks),
        )

    def search(
        self,
        embedding: list[float],
        top_k: int,
        doc_ids: list[str] | None = None,
        query_text: str | None = None,
    ) -> list[SearchHit]:
        """执行检索并返回命中结果。"""
        self._ensure_collection(len(embedding))
        filter_expr = ""
        if doc_ids:
            quoted = ", ".join(f'"{doc_id}"' for doc_id in doc_ids)
            filter_expr = f"doc_id in [{quoted}]"
        compact_query = (query_text or "").strip()
        logger.info(
            "Milvus search | collection=%s query=%s top_k=%s doc_ids=%s hybrid=%s",
            self.collection_name,
            compact_query[:200],
            top_k,
            doc_ids or [],
            self._can_hybrid_search(compact_query),
        )

        dense_hits = self._dense_search(
            embedding=embedding,
            top_k=top_k,
            filter_expr=filter_expr,
        )

        if self._can_hybrid_search(query_text):
            try:
                keyword_hits = self._keyword_search(
                    query_text=query_text or "",
                    top_k=top_k,
                    filter_expr=filter_expr,
                )
                if keyword_hits:
                    return self._weighted_rrf_fuse(dense_hits, keyword_hits, top_k)
            except Exception:
                logger.exception("Milvus keyword BM25 search failed; falling back to dense search")

        return dense_hits

    def _dense_search(
        self,
        embedding: list[float],
        top_k: int,
        filter_expr: str = "",
    ) -> list[SearchHit]:
        """处理稠密检索结果search。"""
        output_fields = self._search_output_fields()
        results = self.client.search(
            collection_name=self.collection_name,
            data=[embedding],
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
            search_params={"metric_type": "COSINE", "params": {"nprobe": self.settings.milvus_nprobe}},
            anns_field="embedding",
        )
        return self._results_to_hits(results, retrieval_mode="dense")

    def _keyword_search(
        self,
        query_text: str,
        top_k: int,
        filter_expr: str = "",
    ) -> list[SearchHit]:
        """处理关键词search。"""
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_text],
            anns_field=BM25_INDEX_FIELD_NAME,
            search_params={
                "metric_type": "BM25",
                "params": {"drop_ratio_search": 0.0},
            },
            limit=top_k,
            filter=filter_expr,
            output_fields=self._search_output_fields(),
        )
        return self._results_to_hits(results, retrieval_mode="keyword_bm25")

    def _weighted_rrf_fuse(
        self,
        dense_hits: list[SearchHit],
        keyword_hits: list[SearchHit],
        top_k: int,
    ) -> list[SearchHit]:
        """使用加权 RRF 融合向量检索和关键词检索结果。"""
        k = max(int(self.settings.hybrid_rrf_k), 1)
        dense_weight = float(self.settings.hybrid_dense_weight)
        keyword_weight = float(self.settings.hybrid_keyword_weight)
        if dense_weight < 0 or keyword_weight < 0 or (dense_weight + keyword_weight) <= 0:
            dense_weight = 0.75
            keyword_weight = 0.25
        total_weight = dense_weight + keyword_weight
        dense_weight /= total_weight
        keyword_weight /= total_weight

        fused: dict[str, SearchHit] = {}
        dense_rank = {hit.chunk_id: index for index, hit in enumerate(dense_hits, start=1)}
        keyword_rank = {hit.chunk_id: index for index, hit in enumerate(keyword_hits, start=1)}
        dense_map = {hit.chunk_id: hit for hit in dense_hits}
        keyword_map = {hit.chunk_id: hit for hit in keyword_hits}

        for chunk_id in set(dense_map) | set(keyword_map):
            base_hit = dense_map.get(chunk_id) or keyword_map[chunk_id]
            metadata = dict(base_hit.metadata or {})
            vector_score = dense_map.get(chunk_id).score if chunk_id in dense_map else 0.0
            lexical_score = keyword_map.get(chunk_id).score if chunk_id in keyword_map else 0.0
            score = 0.0
            if chunk_id in dense_rank:
                score += dense_weight / (k + dense_rank[chunk_id])
            if chunk_id in keyword_rank:
                score += keyword_weight / (k + keyword_rank[chunk_id])
            metadata["vector_score"] = float(vector_score)
            metadata["lexical_score"] = float(lexical_score)
            metadata["retrieval_mode"] = "code_rrf_dense_keyword"
            fused[chunk_id] = SearchHit(
                chunk_id=base_hit.chunk_id,
                doc_id=base_hit.doc_id,
                text=base_hit.text,
                page=base_hit.page,
                score=float(score),
                source_file=base_hit.source_file,
                page_end=base_hit.page_end,
                metadata=metadata,
            )

        return sorted(fused.values(), key=lambda item: item.score, reverse=True)[:top_k]

    def _results_to_hits(self, results: list, retrieval_mode: str) -> list[SearchHit]:
        """处理结果列表to命中结果列表。"""
        hits: list[SearchHit] = []
        for item in results[0]:
            entity = item.get("entity", {})
            metadata = self._load_metadata(entity.get("metadata_json"))
            chunk_type = entity.get("chunk_type")
            if chunk_type and "type" not in metadata:
                metadata["type"] = chunk_type
            metadata["retrieval_mode"] = retrieval_mode
            page = int(entity.get("page", 0))
            hits.append(
                SearchHit(
                    chunk_id=entity.get("chunk_id") or str(item.get("id", "")),
                    doc_id=entity.get("doc_id", ""),
                    text=entity.get("text", ""),
                    page=page,
                    score=float(item.get("distance", 0.0)),
                    source_file=entity.get("source_file", ""),
                    page_end=int(entity.get("page_end") or page),
                    metadata=metadata,
                )
            )
        return hits

    def delete_by_doc_id(self, doc_id: str) -> None:
        """删除by文档id。"""
        if not self.client.has_collection(collection_name=self.collection_name):
            return
        self._ensure_collection(self._dimension or 1024)
        self.client.delete(
            collection_name=self.collection_name,
            filter=f'doc_id == "{doc_id}"',
        )
        self.client.flush(collection_name=self.collection_name)

    def _delete_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        """删除by切片ids。"""
        if not chunk_ids:
            return
        self.client.delete(
            collection_name=self.collection_name,
            ids=chunk_ids,
        )

    def close(self) -> None:
        """关闭当前对象持有的连接、模型或其他外部资源。"""
        self.client.close()
