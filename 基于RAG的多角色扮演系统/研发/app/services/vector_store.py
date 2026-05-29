import os
from typing import Dict, List

import jieba
from pymilvus import MilvusClient

from app.core.config import (
    EMBEDDING_BATCH_SIZE,
    HYBRID_BM25_WEIGHT,
    HYBRID_VECTOR_WEIGHT,
    KNOWLEDGE_CHUNK_OVERLAP,
    KNOWLEDGE_CHUNK_SIZE,
    MILVUS_COLLECTION_NAME,
    MILVUS_DB_NAME,
    MILVUS_HYBRID_RERANKER,
    MILVUS_INDEX_NLIST,
    MILVUS_INSERT_BATCH_SIZE,
    MILVUS_SEARCH_NPROBE,
    MILVUS_TEXT_ANALYZER,
    MILVUS_URI,
)
from app.services.embedding import EmbeddingModel
from app.services.vector_store_components.chunking import VectorStoreChunkingMixin
from app.services.vector_store_components.collections import VectorStoreCollectionsMixin
from app.services.vector_store_components.conversations import (
    VectorStoreConversationsMixin,
)
from app.services.vector_store_components.documents import VectorStoreDocumentsMixin
from app.services.vector_store_components.search import VectorStoreSearchMixin


class VectorStore(
    VectorStoreChunkingMixin,
    VectorStoreCollectionsMixin,
    VectorStoreDocumentsMixin,
    VectorStoreSearchMixin,
    VectorStoreConversationsMixin,
):
    def __init__(self, embedding_model: EmbeddingModel):
        self.embedding_model = embedding_model
        self.collection_name = MILVUS_COLLECTION_NAME
        self.conversation_collection_name = f"{MILVUS_COLLECTION_NAME }_conversations"
        self.loaded_file_collection_name = f"{MILVUS_COLLECTION_NAME }_loaded_files"
        self.documents: List[Dict] = []
        self.chunk_size = max(1, KNOWLEDGE_CHUNK_SIZE)
        self.chunk_overlap = max(0, min(KNOWLEDGE_CHUNK_OVERLAP, self.chunk_size - 1))
        self.embedding_batch_size = max(1, EMBEDDING_BATCH_SIZE)
        self.insert_batch_size = max(1, MILVUS_INSERT_BATCH_SIZE)
        self.index_nlist = max(1, MILVUS_INDEX_NLIST)
        self.search_nprobe = max(1, MILVUS_SEARCH_NPROBE)
        self.vector_weight = max(0.0, HYBRID_VECTOR_WEIGHT)
        self.bm25_weight = max(0.0, HYBRID_BM25_WEIGHT)
        self.text_analyzer = (MILVUS_TEXT_ANALYZER or "chinese").strip() or "chinese"
        self.hybrid_reranker = (
            MILVUS_HYBRID_RERANKER or "weighted"
        ).strip().lower()
        self._jieba_cut = jieba.cut

        milvus_dir = os.path.dirname(MILVUS_URI)
        if milvus_dir and not any(
            milvus_dir.startswith(prefix) for prefix in ["http:", "https:"]
        ):
            os.makedirs(milvus_dir, exist_ok=True)

        self.client = MilvusClient(uri=MILVUS_URI, db_name=MILVUS_DB_NAME)
        self._create_conversation_collection()
        self._create_loaded_file_collection()
