from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pymilvus import DataType, MilvusClient

from app.core.config import Settings
from app.models.domain import ChunkRecord, SearchHit

logger = logging.getLogger(__name__)


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
    ) -> list[SearchHit]:
        raise NotImplementedError

    @abstractmethod
    def delete_by_doc_id(self, doc_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def warmup(self) -> None:
        return


class MilvusVectorStore(BaseVectorStore):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.collection_name = settings.vector_collection
        self._dimension: int | None = None
        self._loaded = False
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
            schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
            schema.add_field(
                field_name="source_file",
                datatype=DataType.VARCHAR,
                max_length=512,
            )
            schema.add_field(
                field_name="text",
                datatype=DataType.VARCHAR,
                max_length=65535,
            )
            schema.add_field(
                field_name="embedding",
                datatype=DataType.FLOAT_VECTOR,
                dim=dimension,
            )

            index_params = MilvusClient.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="AUTOINDEX",
                index_name="embedding_index",
                metric_type="COSINE",
                params={},
            )

            self.client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
            )
            self.client.create_index(
                collection_name=self.collection_name,
                index_params=index_params,
            )
            logger.info("Created Milvus collection: %s", self.collection_name)

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
        self._delete_by_chunk_ids([chunk.chunk_id for chunk in chunks])

        records = []
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            records.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "page": chunk.page,
                    "chunk_index": chunk.chunk_index,
                    "source_file": chunk.source_file,
                    "text": chunk.text[:65535],
                    "embedding": embedding,
                }
            )

        self.client.insert(collection_name=self.collection_name, data=records)
        self.client.flush(collection_name=self.collection_name)
        logger.info("Inserted chunks into Milvus: %s", len(chunks))

    def search(
        self,
        embedding: list[float],
        top_k: int,
        doc_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        self._ensure_collection(len(embedding))
        filter_expr = ""
        if doc_ids:
            quoted = ", ".join(f'"{doc_id}"' for doc_id in doc_ids)
            filter_expr = f"doc_id in [{quoted}]"

        results = self.client.search(
            collection_name=self.collection_name,
            data=[embedding],
            filter=filter_expr,
            limit=top_k,
            output_fields=["chunk_id", "doc_id", "page", "source_file", "text"],
            search_params={"metric_type": "COSINE", "params": {}},
            anns_field="embedding",
        )

        hits: list[SearchHit] = []
        for item in results[0]:
            entity = item.get("entity", {})
            hits.append(
                SearchHit(
                    chunk_id=entity.get("chunk_id") or str(item.get("id", "")),
                    doc_id=entity.get("doc_id", ""),
                    text=entity.get("text", ""),
                    page=int(entity.get("page", 0)),
                    score=float(item.get("distance", 0.0)),
                    source_file=entity.get("source_file", ""),
                    metadata={},
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

    def warmup(self) -> None:
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
