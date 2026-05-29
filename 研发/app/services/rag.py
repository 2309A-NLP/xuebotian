from app.services.embedding import EmbeddingModel
from app.services.llm import ChatRouterLLM
from app.services.memory import ConversationMemory
from app.services.response_cache import ResponseCache
from app.services.rag_components.history import RAGHistoryMixin
from app.services.rag_components.prompting import RAGPromptingMixin
from app.services.rag_components.retrieval import RAGRetrievalMixin
from app.services.rag_components.runtime import RAGRuntimeMixin
from app.services.rag_components.text_utils import RAGTextUtilsMixin
from app.services.reranker import Reranker
from app.services.vector_store import VectorStore


class RAGSystem(
    RAGRuntimeMixin,
    RAGTextUtilsMixin,
    RAGHistoryMixin,
    RAGRetrievalMixin,
    RAGPromptingMixin,
):
    def __init__(self):
        self.embedding_model = EmbeddingModel()
        self.vector_store = VectorStore(self.embedding_model)
        self.reranker = Reranker()
        self.llm = ChatRouterLLM()
        self.memory = ConversationMemory()
        self.response_cache = ResponseCache()
        self._initialized = False
