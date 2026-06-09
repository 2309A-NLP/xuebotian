from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = Field(default="RAGgd", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEBUG", "APP_DEBUG"),
    )
    host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("HOST", "APP_HOST"),
    )
    port: int = Field(
        default=8000,
        validation_alias=AliasChoices("PORT", "APP_PORT"),
    )
    cors_origins: list[str] = Field(default_factory=list, alias="CORS_ORIGINS")
    log_dir: Path = Field(default=Path("data/logs"), alias="LOG_DIR")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")

    llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    llm_model: str = Field(
        default="gpt-4.1-mini",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    llm_timeout: float = Field(default=120.0, alias="LLM_TIMEOUT")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=2048, alias="LLM_MAX_TOKENS")
    ragas_judge_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RAGAS_JUDGE_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"),
    )
    ragas_judge_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RAGAS_JUDGE_BASE_URL", "LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    ragas_judge_model: str = Field(
        default="gpt-4.1-mini",
        validation_alias=AliasChoices("RAGAS_JUDGE_MODEL", "LLM_MODEL", "OPENAI_MODEL"),
    )
    ragas_judge_timeout: float = Field(
        default=120.0,
        validation_alias=AliasChoices("RAGAS_JUDGE_TIMEOUT", "LLM_TIMEOUT"),
    )

    embedding_model: str = Field(default="text-embedding-3-large", alias="EMBEDDING_MODEL")
    embedding_model_name: str = Field(
        default="BAAI/bge-m3",
        validation_alias=AliasChoices("EMBEDDING_MODEL_NAME", "EMBEDDING_MODEL"),
    )
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE")
    ragas_judge_embedding_model_name: str = Field(
        default="BAAI/bge-m3",
        validation_alias=AliasChoices(
            "RAGAS_JUDGE_EMBEDDING_MODEL_NAME",
            "EMBEDDING_MODEL_NAME",
            "EMBEDDING_MODEL",
        ),
    )
    ragas_judge_embedding_device: str = Field(
        default="cpu",
        validation_alias=AliasChoices("RAGAS_JUDGE_EMBEDDING_DEVICE", "EMBEDDING_DEVICE"),
    )

    rerank_model: str = Field(default="gpt-4.1-mini", alias="RERANK_MODEL")
    rerank_model_name: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        validation_alias=AliasChoices("RERANK_MODEL_NAME", "RERANK_MODEL"),
    )
    rerank_batch_size: int = Field(default=8, alias="RERANK_BATCH_SIZE")
    rerank_enabled: bool = Field(default=True, alias="RERANK_ENABLED")

    mysql_host: str = Field(default="127.0.0.1", alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, alias="MYSQL_PORT")
    mysql_user: str = Field(default="root", alias="MYSQL_USER")
    mysql_password: str = Field(default="", alias="MYSQL_PASSWORD")
    mysql_database: str = Field(default="raggd", alias="MYSQL_DATABASE")
    mysql_charset: str = Field(default="utf8mb4", alias="MYSQL_CHARSET")

    auth_secret_key: str = Field(default="change-me", alias="AUTH_SECRET_KEY")
    auth_token_ttl_hours: int = Field(default=72, alias="AUTH_TOKEN_TTL_HOURS")
    auth_cookie_name: str = Field(default="raggd_token", alias="AUTH_COOKIE_NAME")
    auth_cookie_secure: bool = Field(default=False, alias="AUTH_COOKIE_SECURE")
    auth_cookie_samesite: str = Field(default="lax", alias="AUTH_COOKIE_SAMESITE")

    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")

    vector_backend: str = Field(default="milvus", alias="VECTOR_BACKEND")
    vector_collection: str = Field(
        default="rag_chunks5",
        validation_alias=AliasChoices("VECTOR_COLLECTION", "MILVUS_COLLECTION"),
    )
    milvus_uri: str = Field(default="http://127.0.0.1:19530", alias="MILVUS_URI")
    milvus_token: str | None = Field(default=None, alias="MILVUS_TOKEN")
    milvus_user: str | None = Field(default=None, alias="MILVUS_USER")
    milvus_password: str | None = Field(default=None, alias="MILVUS_PASSWORD")
    milvus_database: str = Field(default="default", alias="MILVUS_DATABASE")
    milvus_collection: str = Field(default="rag_chunks5", alias="MILVUS_COLLECTION")
    milvus_dim: int = Field(default=3072, alias="MILVUS_DIM")
    milvus_nprobe: int = Field(default=16, alias="MILVUS_NPROBE")
    hybrid_search_enabled: bool = Field(default=True, alias="HYBRID_SEARCH_ENABLED")
    hybrid_rrf_k: int = Field(default=60, alias="HYBRID_RRF_K")
    hybrid_dense_weight: float = Field(default=0.75, alias="HYBRID_DENSE_WEIGHT")
    hybrid_keyword_weight: float = Field(default=0.25, alias="HYBRID_KEYWORD_WEIGHT")

    upload_dir: Path = Field(default=Path("data/uploads"), alias="UPLOAD_DIR")
    parsed_dir: Path = Field(default=Path("data/parsed"), alias="PARSED_DIR")
    image_dir: Path = Field(default=Path("data/images"), alias="IMAGE_DIR")
    mineru_debug_dir: Path = Field(default=Path("data/mineru_debug"), alias="MINERU_DEBUG_DIR")
    document_db_path: Path = Field(default=Path("data/metadata.db"), alias="DOCUMENT_DB_PATH")
    max_upload_size_mb: int = Field(default=50, alias="MAX_UPLOAD_SIZE_MB")

    watermark_pattern_list: list[str] = Field(default_factory=list, alias="WATERMARK_PATTERN_LIST")

    chunk_size: int = Field(default=700, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=100, alias="CHUNK_OVERLAP")
    retrieval_candidate_count: int = Field(default=60, alias="RETRIEVAL_CANDIDATE_COUNT")
    recall_candidate_count: int = Field(
        default=60,
        validation_alias=AliasChoices("RECALL_CANDIDATE_COUNT", "RETRIEVAL_CANDIDATE_COUNT"),
    )
    rerank_candidate_count: int = Field(default=20, alias="RERANK_CANDIDATE_COUNT")
    top_k: int = Field(default=8, alias="TOP_K")
    prompt_max_context_chars: int = Field(default=12000, alias="PROMPT_MAX_CONTEXT_CHARS")
    prompt_chunk_char_limit: int = Field(default=2200, alias="PROMPT_CHUNK_CHAR_LIMIT")
    answer_history_max_messages: int = Field(default=12, alias="ANSWER_HISTORY_MAX_MESSAGES")
    chat_history_ttl_seconds: int = Field(default=86400, alias="CHAT_HISTORY_TTL_SECONDS")
    stream_emit_char_threshold: int = Field(default=80, alias="STREAM_EMIT_CHAR_THRESHOLD")

    pdf_parser: str = Field(default="mineru", alias="PDF_PARSER")
    pdf_parser_backend: str = Field(
        default="mineru",
        validation_alias=AliasChoices("PDF_PARSER_BACKEND", "PDF_PARSER"),
    )
    mineru_api_key: str | None = Field(default=None, alias="MINERU_API_KEY")
    mineru_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("MINERU_API_TOKEN", "MINERU_API_KEY"),
    )
    mineru_api_user_token: str = Field(default="", alias="MINERU_API_USER_TOKEN")
    mineru_api_base_url: str = Field(default="https://mineru.net/api/v4", alias="MINERU_API_BASE_URL")
    mineru_api_mode: str = Field(default="official", alias="MINERU_API_MODE")
    mineru_model_version: str = Field(default="vlm", alias="MINERU_MODEL_VERSION")
    mineru_language: str = Field(default="auto", alias="MINERU_LANGUAGE")
    mineru_backend: str | None = Field(default=None, alias="MINERU_BACKEND")
    mineru_enable_ocr: bool = Field(default=True, alias="MINERU_ENABLE_OCR")
    mineru_enable_table: bool = Field(default=True, alias="MINERU_ENABLE_TABLE")
    mineru_enable_formula: bool = Field(default=False, alias="MINERU_ENABLE_FORMULA")
    mineru_max_pages_per_part: int = Field(default=200, alias="MINERU_MAX_PAGES_PER_PART")
    mineru_max_pages_per_file: int = Field(
        default=200,
        validation_alias=AliasChoices("MINERU_MAX_PAGES_PER_FILE", "MINERU_MAX_PAGES_PER_PART"),
    )
    mineru_request_timeout_seconds: int = Field(default=600, alias="MINERU_REQUEST_TIMEOUT_SECONDS")
    mineru_poll_interval_seconds: float = Field(default=3.0, alias="MINERU_POLL_INTERVAL_SECONDS")
    mineru_poll_timeout_seconds: float = Field(default=1800.0, alias="MINERU_POLL_TIMEOUT_SECONDS")
    mineru_debug_save_results: bool = Field(default=True, alias="MINERU_DEBUG_SAVE_RESULTS")

    vision_enabled: bool = Field(default=False, alias="VISION_ENABLED")
    vision_model: str = Field(default="gpt-4.1-mini", alias="VISION_MODEL")
    vision_base_url: str | None = Field(default=None, alias="VISION_BASE_URL")
    vision_api_key: str | None = Field(default=None, alias="VISION_API_KEY")
    vision_max_workers: int = Field(default=4, alias="VISION_MAX_WORKERS")
    vision_max_tokens: int = Field(default=1024, alias="VISION_MAX_TOKENS")
    vision_debug_save_images: bool = Field(default=True, alias="VISION_DEBUG_SAVE_IMAGES")
    vision_debug_dir: Path = Field(default=Path("data/vision_debug"), alias="VISION_DEBUG_DIR")

    speech_enabled: bool = Field(default=False, alias="SPEECH_ENABLED")
    speech_model: str = Field(default="gpt-4o-mini-transcribe", alias="SPEECH_MODEL")

    use_llm_query_variants: bool = Field(default=True, alias="USE_LLM_QUERY_VARIANTS")
    query_rewrite_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("QUERY_REWRITE_ENABLED", "USE_LLM_QUERY_VARIANTS"),
    )
    query_rewrite_max_tokens: int = Field(default=256, alias="QUERY_REWRITE_MAX_TOKENS")
    llm_query_variant_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_QUERY_VARIANT_MODEL", "OPENAI_MODEL"),
    )
    llm_query_variant_count: int = Field(default=4, alias="LLM_QUERY_VARIANT_COUNT")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.parsed_dir.mkdir(parents=True, exist_ok=True)
    settings.image_dir.mkdir(parents=True, exist_ok=True)
    settings.mineru_debug_dir.mkdir(parents=True, exist_ok=True)
    settings.document_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.vision_debug_dir.mkdir(parents=True, exist_ok=True)
    return settings
