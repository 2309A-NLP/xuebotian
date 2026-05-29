from typing import Dict, List

from FlagEmbedding import FlagReranker

from app.core.config import DEVICE, RERANK_TOP_K, RERANKER_MODEL_PATH, USE_FP16
from app.core.logging_utils import get_logger


logger = get_logger(__name__)


class Reranker:
    def __init__(self, model_path: str = None):
        self.model_path = model_path or RERANKER_MODEL_PATH
        self.model = FlagReranker(
            self.model_path,
            use_fp16=USE_FP16,
            device=DEVICE,
        )

    def _build_document_text(self, doc: Dict) -> str:
        parts = [f"character: {(doc .get ('name')or '').strip ()}"]
        source_title = (doc.get("source_title") or "").strip()
        if source_title:
            parts.append(f"title: {source_title }")
        source_file = (doc.get("source_file") or "").strip()
        if source_file:
            parts.append(f"source: {source_file }")
        parts.append(f"content: {(doc .get ('message')or '').strip ()}")
        return "\n".join(part for part in parts if part.strip())

    def rerank(
        self, query: str, documents: List[Dict], top_k: int = RERANK_TOP_K
    ) -> List[Dict]:
        if not documents:
            return []

        pairs = [[query, self._build_document_text(doc)] for doc in documents]
        scores = self.model.compute_score(pairs)

        if isinstance(scores, (int, float)):
            scores = [float(scores)]

        for i, score in enumerate(scores):
            documents[i]["rerank_score"] = float(score)

        sorted_docs = sorted(documents, key=lambda x: x["rerank_score"], reverse=True)
        logger.info(
            "重排完成: 查询=%r ",
            query,
            
        )
        return sorted_docs[:top_k]
