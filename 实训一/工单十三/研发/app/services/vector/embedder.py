from __future__ import annotations

import logging

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# BGE-M3 官方推荐的 query instruction 前缀，用于非对称检索
# 参考: https://huggingface.co/BAAI/bge-m3
_BGE_M3_QUERY_INSTRUCTION = (
    "Represent this sentence for searching relevant passages: "
)


class BgeM3Embedder:
    """封装 BGE-M3 向量模型的加载与文本编码能力。"""
    def __init__(self, model_name: str, device: str, batch_size: int) -> None:
        """初始化向量编码器所需的依赖和运行参数。"""
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None

    @property
    def dimension(self) -> int:
        """返回当前向量模型输出的维度。"""
        return self.model.get_sentence_embedding_dimension()

    @property
    def model(self) -> SentenceTransformer:
        """懒加载并返回底层模型实例。"""
        if self._model is None:
            logger.info("Loading embedding model: %s on %s", self.model_name, self.device)
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """对文档 chunk 进行向量化（不带 instruction 前缀）"""
        if not texts:
            return []
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        """对查询文本进行向量化（带 BGE-M3 query instruction 前缀）"""
        if not queries:
            return []
        instructed = [_BGE_M3_QUERY_INSTRUCTION + q for q in queries]
        embeddings = self.model.encode(
            instructed,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """将查询编码为向量。"""
        return self.embed_queries([text])[0]
