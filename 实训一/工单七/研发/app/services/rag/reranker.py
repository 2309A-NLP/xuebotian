from __future__ import annotations

import os
import logging
from pathlib import Path

from app.models.domain import SearchHit

logger = logging.getLogger(__name__)


class BgeReranker:
    def __init__(
        self,
        model_name: str,
        device: str,
        batch_size: int,
        enabled: bool = True,
    ) -> None:
        self.model_name = self._normalize_model_name(model_name)
        self.device = device
        self.batch_size = batch_size
        self.enabled = enabled
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("Loading rerank model: %s on %s", self.model_name, self.device)
            load_kwargs = {"device": self.device}
            if Path(self.model_name).exists() or os.getenv("HF_HUB_OFFLINE") == "1":
                load_kwargs["local_files_only"] = True
            self._model = CrossEncoder(self.model_name, **load_kwargs)
        return self._model

    def rerank(self, query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
        if not self.enabled or not hits:
            return hits[:top_k]
        try:
            pairs = [(query, hit.text[:1600]) for hit in hits]
            scores = self.model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
        except Exception:
            logger.exception("Rerank failed; falling back to vector order")
            return hits[:top_k]

        for hit, score in zip(hits, scores, strict=False):
            hit.metadata.setdefault("vector_score", hit.score)
            hit.metadata["rerank_score"] = float(score)
            hit.score = float(score)
        return sorted(hits, key=lambda item: item.score, reverse=True)[:top_k]

    def _normalize_model_name(self, value: str) -> str:
        model_name = value.strip()
        if len(model_name) >= 3 and model_name[0].lower() == "r" and model_name[1] in {"'", '"'}:
            model_name = model_name[2:]
            if model_name and model_name[-1] in {"'", '"'}:
                model_name = model_name[:-1]
        model_name = model_name.strip().strip("'\"")
        path = Path(model_name)
        return str(path) if path.exists() else model_name
