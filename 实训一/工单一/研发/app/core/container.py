from __future__ import annotations

from app.core.config import Settings
from app.services.document.chunker import DocumentChunker
from app.services.document.cleaner import TextCleaner
from app.services.document.manager import DocumentService
from app.services.document.parser import PdfParser
from app.services.intent.analyzer import IntentAnalyzer
from app.services.llm.client import OpenAICompatibleLLMClient
from app.services.rag.pipeline import RagPipeline
from app.services.speech.transcriber import AudioTranscriber
from app.services.storage.file_store import FileStore
from app.services.storage.metadata_store import MetadataStore
from app.services.vector.embedder import BgeM3Embedder
from app.services.vector.milvus_store import InMemoryVectorStore, MilvusVectorStore


class AppContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.file_store = FileStore(settings)
        self.metadata_store = MetadataStore(settings.document_db_path)
        self.parser = PdfParser()
        self.cleaner = TextCleaner(settings.watermark_pattern_list)
        self.chunker = DocumentChunker(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        self.embedder = BgeM3Embedder(
            model_name=settings.embedding_model_name,
            device=settings.embedding_device,
            batch_size=settings.embedding_batch_size,
        )
        self.vector_store = self._build_vector_store()
        self.intent_analyzer = IntentAnalyzer()
        self.llm_client = OpenAICompatibleLLMClient(settings)
        self.speech_transcriber = AudioTranscriber(settings, self.llm_client)
        self.document_service = DocumentService(
            settings=settings,
            file_store=self.file_store,
            metadata_store=self.metadata_store,
            parser=self.parser,
            cleaner=self.cleaner,
            chunker=self.chunker,
            embedder=self.embedder,
            vector_store=self.vector_store,
        )
        self.rag_pipeline = RagPipeline(
            settings=settings,
            intent_analyzer=self.intent_analyzer,
            embedder=self.embedder,
            vector_store=self.vector_store,
            llm_client=self.llm_client,
        )

    def _build_vector_store(self):
        if self.settings.vector_backend.lower() == "memory":
            return InMemoryVectorStore()
        return MilvusVectorStore(self.settings)

    def close(self) -> None:
        self.vector_store.close()
        self.llm_client.close()
