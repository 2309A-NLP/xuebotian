from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.domain import ChunkRecord, SearchHit

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

