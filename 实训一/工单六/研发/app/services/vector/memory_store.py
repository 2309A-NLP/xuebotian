from __future__ import annotations

from app.models.domain import ChunkRecord, SearchHit
from app.services.vector.base import BaseVectorStore


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
