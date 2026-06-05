import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "output.json"

EMBEDDING_MODEL_PATH = os.getenv("EMBEDDING_MODEL_PATH", "G:/eight_dim/model/BGE-m3")
RERANKER_MODEL_PATH = os.getenv(
    "RERANKER_MODEL_PATH", "G:/eight_dim/model/bge-reranker-base"
)

MILVUS_URI = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
MILVUS_DB_NAME = os.getenv("MILVUS_DB_NAME", "rag_user_cosplay")
MILVUS_COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "character_rag")
MILVUS_TEXT_ANALYZER = os.getenv("MILVUS_TEXT_ANALYZER", "chinese")
MILVUS_HYBRID_RERANKER = os.getenv("MILVUS_HYBRID_RERANKER", "weighted")

_legacy_ollama_base_url = os.getenv("OLLAMA_BASE_URL", "")
_legacy_ollama_model = os.getenv("OLLAMA_MODEL", "")
DEFAULT_SGLANG_BASE_URL = os.getenv(
    "DEFAULT_SGLANG_BASE_URL",
    "https://u966061-b0d8-72e6f251.westb.seetacloud.com:8443/v1",
)
SGLANG_BASE_URL = os.getenv(
    "SGLANG_BASE_URL",
    _legacy_ollama_base_url or DEFAULT_SGLANG_BASE_URL,
)
SGLANG_MODEL = os.getenv(
    "SGLANG_MODEL",
    _legacy_ollama_model or "qwen-0.8b",
)
SGLANG_API_KEY = os.getenv(
    "SGLANG_API_KEY",
    os.getenv("OLLAMA_API_KEY", "EMPTY"),
)

ONLINE_LLM_BASE_URL = os.getenv(
    "ONLINE_LLM_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions"
)
ONLINE_LLM_API_KEY = os.getenv(
    "ONLINE_LLM_API_KEY", ""
)
ONLINE_LLM_MODEL = os.getenv("ONLINE_LLM_MODEL", "Pro/deepseek-ai/DeepSeek-V3")
ONLINE_LLM_TIMEOUT = int(os.getenv("ONLINE_LLM_TIMEOUT", "120"))

MINERU_API_BASE_URL = os.getenv("MINERU_API_BASE_URL", "https://mineru.net")
MINERU_API_TOKEN = os.getenv("MINERU_API_TOKEN", "")
MINERU_API_USER_TOKEN = os.getenv("MINERU_API_USER_TOKEN", "")
MINERU_PDF_MODEL_VERSION = os.getenv("MINERU_PDF_MODEL_VERSION", "vlm")
MINERU_PDF_LANGUAGE = os.getenv("MINERU_PDF_LANGUAGE", "auto")
MINERU_PDF_ENABLE_OCR = os.getenv("MINERU_PDF_ENABLE_OCR", "true").lower() == "true"
MINERU_PDF_ENABLE_TABLE = (
    os.getenv("MINERU_PDF_ENABLE_TABLE", "true").lower() == "true"
)
MINERU_PDF_ENABLE_FORMULA = (
    os.getenv("MINERU_PDF_ENABLE_FORMULA", "true").lower() == "true"
)
MINERU_PDF_REQUEST_TIMEOUT = int(os.getenv("MINERU_PDF_REQUEST_TIMEOUT", "180"))
MINERU_PDF_POLL_TIMEOUT_SECONDS = int(
    os.getenv("MINERU_PDF_POLL_TIMEOUT_SECONDS", "600")
)
MINERU_PDF_POLL_INTERVAL_SECONDS = int(
    os.getenv("MINERU_PDF_POLL_INTERVAL_SECONDS", "5")
)

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
_redis_password = os.getenv("REDIS_PASSWORD", "")
REDIS_PASSWORD = _redis_password if _redis_password else None
CONVERSATION_EXPIRE_SECONDS = int(os.getenv("CONVERSATION_EXPIRE_SECONDS", "3600"))
RESPONSE_CACHE_ENABLED = os.getenv("RESPONSE_CACHE_ENABLED", "true").lower() == "true"
RESPONSE_CACHE_EXPIRE_SECONDS = int(
    os.getenv("RESPONSE_CACHE_EXPIRE_SECONDS", "1800")
)
RESPONSE_CACHE_MAX_HISTORY_CHARS = int(
    os.getenv("RESPONSE_CACHE_MAX_HISTORY_CHARS", "500")
)

SHORT_TERM_MEMORY_ROUNDS = int(os.getenv("SHORT_TERM_MEMORY_ROUNDS", "10"))

LONG_TERM_MEMORY_TOP_K = int(os.getenv("LONG_TERM_MEMORY_TOP_K", "3"))

KNOWLEDGE_RERANK_SCORE_THRESHOLD = float(
    os.getenv("KNOWLEDGE_RERANK_SCORE_THRESHOLD", "0.1")
)

FACT_QUERY_RERANK_SCORE_THRESHOLD = float(
    os.getenv("FACT_QUERY_RERANK_SCORE_THRESHOLD", "0.18")
)

RECENT_HISTORY_PROMPT_TURNS = int(os.getenv("RECENT_HISTORY_PROMPT_TURNS", "5"))

RECENT_HISTORY_MESSAGE_TURNS = int(os.getenv("RECENT_HISTORY_MESSAGE_TURNS", "5"))

RETRIEVAL_HISTORY_QUERY_LIMIT = int(os.getenv("RETRIEVAL_HISTORY_QUERY_LIMIT", "3"))

RETRIEVAL_HISTORY_DIALOGUE_TURNS = int(
    os.getenv("RETRIEVAL_HISTORY_DIALOGUE_TURNS", "4")
)

RETRIEVAL_QUERY_REWRITE_ENABLED = (
    os.getenv("RETRIEVAL_QUERY_REWRITE_ENABLED", "true").lower() == "true"
)

RETRIEVAL_QUERY_REWRITE_MAX_TURNS = int(
    os.getenv("RETRIEVAL_QUERY_REWRITE_MAX_TURNS", "3")
)

RETRIEVAL_QUERY_REWRITE_MAX_CHARS = int(
    os.getenv("RETRIEVAL_QUERY_REWRITE_MAX_CHARS", "80")
)

SHORT_TERM_RELEVANT_HISTORY_TURNS = int(
    os.getenv("SHORT_TERM_RELEVANT_HISTORY_TURNS", "3")
)

UNKNOWN_KNOWLEDGE_RESPONSE = os.getenv(
    "UNKNOWN_KNOWLEDGE_RESPONSE",
    "我暂时没有检索到足够可靠的信息，这个问题不敢贸然回答。",
)

STRICT_GROUNDED_ANSWERING = (
    os.getenv("STRICT_GROUNDED_ANSWERING", "true").lower() == "true"
)

TOP_K = int(os.getenv("TOP_K", "5"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "3"))
KNOWLEDGE_CHUNK_SIZE = int(os.getenv("KNOWLEDGE_CHUNK_SIZE", "400"))
KNOWLEDGE_CHUNK_OVERLAP = int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", "80"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "128"))
MILVUS_INSERT_BATCH_SIZE = int(os.getenv("MILVUS_INSERT_BATCH_SIZE", "256"))
MILVUS_INDEX_NLIST = int(os.getenv("MILVUS_INDEX_NLIST", "128"))
MILVUS_SEARCH_NPROBE = int(os.getenv("MILVUS_SEARCH_NPROBE", "32"))
HYBRID_VECTOR_WEIGHT = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.65"))
HYBRID_BM25_WEIGHT = float(os.getenv("HYBRID_BM25_WEIGHT", "0.35"))
DEVICE = os.getenv("DEVICE", "cuda")
USE_FP16 = os.getenv("USE_FP16", "false").lower() == "true"

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "rag_user_cosplay")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "rag-chat-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
