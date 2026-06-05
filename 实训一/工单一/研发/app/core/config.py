from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="RAG QA System", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    debug: bool = Field(default=True, alias="DEBUG")

    upload_dir: Path = Field(default=Path("data/uploads"), alias="UPLOAD_DIR")
    parsed_dir: Path = Field(default=Path("data/parsed"), alias="PARSED_DIR")
    document_db_path: Path = Field(
        default=Path("data/documents/documents.db"),
        alias="DOCUMENT_DB_PATH",
    )
    log_dir: Path = Field(default=Path("data/logs"), alias="LOG_DIR")

    vector_backend: str = Field(default="milvus", alias="VECTOR_BACKEND")
    vector_collection: str = Field(default="rag_chunks", alias="VECTOR_COLLECTION")
    milvus_uri: str = Field(default="http://127.0.0.1:19530", alias="MILVUS_URI")
    milvus_user: str = Field(default="", alias="MILVUS_USER")
    milvus_password: str = Field(default="", alias="MILVUS_PASSWORD")
    milvus_token: str = Field(default="", alias="MILVUS_TOKEN")

    embedding_model_name: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL_NAME")
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE")
    top_k: int = Field(default=5, alias="TOP_K")
    chunk_size: int = Field(default=700, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")

    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_timeout: int = Field(default=60, alias="LLM_TIMEOUT")
    llm_max_tokens: int = Field(default=1200, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")

    speech_enabled: bool = Field(default=True, alias="SPEECH_ENABLED")
    speech_model: str = Field(default="whisper-1", alias="SPEECH_MODEL")

    watermark_patterns: str = Field(
        default="机密,仅供内部使用,Confidential,版权所有,内部资料",
        alias="WATERMARK_PATTERNS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def watermark_pattern_list(self) -> list[str]:
        return [item.strip() for item in self.watermark_patterns.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.parsed_dir.mkdir(parents=True, exist_ok=True)
    settings.document_db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    return settings
