from __future__ import annotations

from app.models.domain import ChunkRecord, SearchHit
from app.services.vector.base import BaseVectorStore


class InMemoryVectorStore(BaseVectorStore):
    """提供便于开发测试的内存版向量存储实现。"""
    def __init__(self) -> None:
        """初始化内存向量存储所需的依赖和运行参数。"""
        self._records: list[tuple[ChunkRecord, list[float]]] = []

    def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        """新增或更新切片集合。"""
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
        """执行检索并返回命中结果。"""
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
        """删除by文档id。"""
        self._records = [
            (chunk, vector)
            for chunk, vector in self._records
            if chunk.doc_id != doc_id
        ]

    def close(self) -> None:
        """关闭当前对象持有的连接、模型或其他外部资源。"""
        return

    def _cosine(self, left: list[float], right: list[float]) -> float:
        """处理cosine。"""
        return sum(a * b for a, b in zip(left, right, strict=False))
