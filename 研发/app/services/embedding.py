import inspect
from typing import List

from FlagEmbedding import BGEM3FlagModel

from app.core.config import DEVICE, EMBEDDING_BATCH_SIZE, EMBEDDING_MODEL_PATH, USE_FP16


class EmbeddingModel:
    def __init__(self, model_path: str = None):
        self.model_path = model_path or EMBEDDING_MODEL_PATH
        self.model = BGEM3FlagModel(
            self.model_path,
            use_fp16=USE_FP16,
            device=DEVICE,
        )
        self.default_batch_size = max(1, EMBEDDING_BATCH_SIZE)
        try:
            self._encode_signature = inspect.signature(self.model.encode)
        except (TypeError, ValueError):
            self._encode_signature = None

    def encode(self, texts: List[str], batch_size: int = None) -> List[List[float]]:
        encode_kwargs = {}
        resolved_batch_size = max(1, batch_size or self.default_batch_size)
        if self._encode_signature and "batch_size" in self._encode_signature.parameters:
            encode_kwargs["batch_size"] = resolved_batch_size
        embeddings = self.model.encode(texts, **encode_kwargs)["dense_vecs"]
        return embeddings.tolist()

    def get_dim(self) -> int:
        return 1024
