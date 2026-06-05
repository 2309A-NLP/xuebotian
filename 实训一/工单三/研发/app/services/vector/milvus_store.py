from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

try:
    from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient, RRFRanker
except ImportError:
    from pymilvus import DataType, MilvusClient

    AnnSearchRequest = None
    Function = None
    FunctionType = None
    RRFRanker = None

from app.core.config import Settings
from app.models.domain import ChunkRecord, SearchHit

logger = logging.getLogger(__name__)

BM25_TEXT_FIELD_NAME = "bm25_text"
BM25_INDEX_FIELD_NAME = "bm25_keyword_index"


class BaseVectorStore(ABC):
    @abstractmethod
    def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        embedding: list[float],
        top_k: int,
        doc_ids: list[str] | None = None,
        query_text: str | None = None,
    ) -> list[SearchHit]:
        raise NotImplementedError

    @abstractmethod
    def delete_by_doc_id(self, doc_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def warmup(self, dimension: int | None = None) -> None:
        return


class MilvusVectorStore(BaseVectorStore):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.collection_name = settings.vector_collection
        self._dimension: int | None = None
        self._loaded = False
        self._field_names: set[str] | None = None
        self.client = self._build_client()

    def _build_client(self) -> MilvusClient:
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
                "content_type": str(chunk.metadata.get("type", "text"))[:32],
                "source_file": chunk.source_file,
                "metadata_json": self._metadata_json(chunk.metadata),
                "text": chunk.text[:65535],
                BM25_TEXT_FIELD_NAME: chunk.text[:65535],
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
        self._ensure_collection(len(embedding))
        filter_expr = ""
        if doc_ids:
            quoted = ", ".join(f'"{doc_id}"' for doc_id in doc_ids)
            filter_expr = f"doc_id in [{quoted}]"

        if self._can_hybrid_search(query_text):
            try:
                return self._hybrid_search(
                    embedding=embedding,
                    query_text=query_text or "",
                    top_k=top_k,
                    filter_expr=filter_expr,
                )
            except Exception:
                logger.exception("Milvus hybrid BM25 search failed; falling back to dense search")

        return self._dense_search(
            embedding=embedding,
            top_k=top_k,
            filter_expr=filter_expr,
        )

    def _dense_search(
        self,
        embedding: list[float],
        top_k: int,
        filter_expr: str = "",
    ) -> list[SearchHit]:
        output_fields = self._search_output_fields()
        results = self.client.search(
            collection_name=self.collection_name,
            data=[embedding],
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
            search_params={"metric_type": "COSINE", "params": {"nprobe": 32}},
            anns_field="embedding",
        )
        return self._results_to_hits(results, retrieval_mode="dense")

    def _hybrid_search(
        self,
        embedding: list[float],
        query_text: str,
        top_k: int,
        filter_expr: str = "",
    ) -> list[SearchHit]:
        dense_request = AnnSearchRequest(
            data=[embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 32}},
            limit=top_k,
            expr=filter_expr,
        )
        bm25_keyword_request = AnnSearchRequest(
            # Milvus BM25 full-text search accepts raw query text here. The server
            # analyzes it and searches the generated sparse inverted index field.
            data=[query_text],
            anns_field=BM25_INDEX_FIELD_NAME,
            param={
                "metric_type": "BM25",
                "params": {"drop_ratio_search": 0.0},
            },
            limit=top_k,
            expr=filter_expr,
        )
        results = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_request, bm25_keyword_request],
            ranker=self._rrf_ranker(),
            limit=top_k,
            output_fields=self._search_output_fields(),
        )
        return self._results_to_hits(results, retrieval_mode="dense_bm25_rrf")

    def _results_to_hits(self, results: list, retrieval_mode: str) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for item in results[0]:
            entity = item.get("entity", {})
            metadata = self._load_metadata(entity.get("metadata_json"))
            chunk_type = entity.get("chunk_type") or entity.get("content_type")
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
        if not self.client.has_collection(collection_name=self.collection_name):
            return
        self._ensure_collection(self._dimension or 1024)
        self.client.delete(
            collection_name=self.collection_name,
            filter=f'doc_id == "{doc_id}"',
        )
        self.client.flush(collection_name=self.collection_name)

    def _delete_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self.client.delete(
            collection_name=self.collection_name,
            ids=chunk_ids,
        )

    def close(self) -> None:
        self.client.close()

    def _describe_fields(self) -> set[str]:
        try:
            description = self.client.describe_collection(
                collection_name=self.collection_name
            )
        except Exception:
            logger.exception("Failed to describe Milvus collection: %s", self.collection_name)
            return {
                "chunk_id",
                "doc_id",
                "page",
                "page_end",
                "chunk_index",
                "chunk_type",
                "content_type",
                "source_file",
                "metadata_json",
                "text",
                BM25_TEXT_FIELD_NAME,
                "embedding",
                BM25_INDEX_FIELD_NAME,
            }

        fields = description.get("fields") or description.get("schema", {}).get("fields", [])
        names: set[str] = set()
        for field in fields:
            if isinstance(field, dict):
                name = field.get("name") or field.get("field_name")
            else:
                name = getattr(field, "name", None)
            if name:
                names.add(str(name))
        return names

    def _hybrid_capable(self) -> bool:
        return (
            self.settings.hybrid_search_enabled
            and Function is not None
            and FunctionType is not None
            and AnnSearchRequest is not None
            and RRFRanker is not None
            and hasattr(DataType, "SPARSE_FLOAT_VECTOR")
            and hasattr(self.client, "hybrid_search")
        )

    def _can_hybrid_search(self, query_text: str | None) -> bool:
        field_names = self._field_names or self._describe_fields()
        self._field_names = field_names
        return (
            self._hybrid_capable()
            and bool(query_text and query_text.strip())
            and BM25_INDEX_FIELD_NAME in field_names
            and BM25_TEXT_FIELD_NAME in field_names
            and "embedding" in field_names
        )

    def _rrf_ranker(self):
        try:
            return RRFRanker(k=self.settings.hybrid_rrf_k)
        except TypeError:
            try:
                return RRFRanker(self.settings.hybrid_rrf_k)
            except TypeError:
                return RRFRanker()

    def _filter_record_fields(self, record: dict[str, Any]) -> dict[str, Any]:
        field_names = self._field_names or self._describe_fields()
        self._field_names = field_names
        if not field_names:
            return record
        return {key: value for key, value in record.items() if key in field_names}

    def _search_output_fields(self) -> list[str]:
        field_names = self._field_names or self._describe_fields()
        self._field_names = field_names
        wanted = [
            "chunk_id",
            "doc_id",
            "page",
            "page_end",
            "chunk_type",
            "content_type",
            "source_file",
            "metadata_json",
            "text",
            BM25_TEXT_FIELD_NAME,
        ]
        if not field_names:
            return wanted
        return [field for field in wanted if field in field_names]

    def _metadata_json(self, metadata: dict[str, Any]) -> str:
        payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= 4096:
            return payload
        compact = dict(metadata)
        header = compact.get("table_header")
        if isinstance(header, list):
            compact["table_header"] = header[:30]
        caption = compact.get("table_caption")
        if isinstance(caption, str):
            compact["table_caption"] = caption[:512]
        payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= 4096:
            return payload
        return json.dumps(
            {
                "type": compact.get("type"),
                "page": compact.get("page"),
                "page_end": compact.get("page_end"),
                "table_caption": compact.get("table_caption"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )[:4096]

    def _load_metadata(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, str) or not value:
            return {}
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def warmup(self, dimension: int | None = None) -> None:
        if dimension is not None:
            self._ensure_collection(dimension)
            logger.info("Milvus collection warmed up: %s", self.collection_name)
            return

        if self.client.has_collection(collection_name=self.collection_name):
            self.client.load_collection(
                collection_name=self.collection_name,
                replica_number=1,
            )
            self._loaded = True
            logger.info("Milvus collection warmed up: %s", self.collection_name)


class InMemoryVectorStore(BaseVectorStore):
    def __init__(self) -> None:
        self._records: list[tuple[ChunkRecord, list[float]]] = []

    def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        existing = {chunk.chunk_id for chunk, _ in self._records}
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            if chunk.chunk_id in existing:
                self._records = [
                    (saved_chunk, saved_embedding)
                    for saved_chunk, saved_embedding in self._records
                    if saved_chunk.chunk_id != chunk.chunk_id
                ]
            self._records.append((chunk, embedding))

    def search(
        self,
        embedding: list[float],
        top_k: int,
        doc_ids: list[str] | None = None,
        query_text: str | None = None,
    ) -> list[SearchHit]:
        scored: list[SearchHit] = []
        for chunk, stored_vector in self._records:
            if doc_ids and chunk.doc_id not in doc_ids:
                continue
            score = self._cosine(embedding, stored_vector)
            scored.append(
                SearchHit(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    page=chunk.page,
                    score=score,
                    source_file=chunk.source_file,
                    page_end=chunk.page_end,
                    metadata=chunk.metadata,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def delete_by_doc_id(self, doc_id: str) -> None:
        self._records = [
            (chunk, vector)
            for chunk, vector in self._records
            if chunk.doc_id != doc_id
        ]

    def close(self) -> None:
        return

    def _cosine(self, left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=False))
