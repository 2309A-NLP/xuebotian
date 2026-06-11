from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.domain import ChunkRecord, SearchHit

class BaseVectorStore(ABC):
    """定义向量存储需要实现的基础接口。"""
    @abstractmethod
    def upsert_chunks(self, chunks: list[ChunkRecord], embeddings: list[list[float]]) -> None:
        """新增或更新切片集合。"""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        embedding: list[float],
        top_k: int,
        doc_ids: list[str] | None = None,
        query_text: str | None = None,
    ) -> list[SearchHit]:
        """执行检索并返回命中结果。"""
        raise NotImplementedError

    @abstractmethod
    def delete_by_doc_id(self, doc_id: str) -> None:
        """删除by文档id。"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """关闭当前对象持有的连接、模型或其他外部资源。"""
        raise NotImplementedError

    def warmup(self, dimension: int | None = None) -> None:
        """预热底层资源，降低首次调用的初始化开销。"""
        return

