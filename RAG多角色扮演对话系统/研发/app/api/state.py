import asyncio
from threading import Lock
from typing import List, Optional

from fastapi import FastAPI

from app.core.logging_utils import get_logger
from app.repositories.database import (
    init_database,
    list_character_profiles,
    sync_character_profiles,
)
from app.services.ingestion.loader import build_data_manifest
from app.services.knowledge_manager import (
    get_file_count,
    load_registered_documents,
    load_upload_manifest,
)
from app.services.rag import RAGSystem


logger = get_logger(__name__)
rag_system: Optional[RAGSystem] = None
rag_system_init_error: Optional[Exception] = None
database_ready = False
database_init_error: Optional[Exception] = None
rag_system_lock = Lock()
database_init_lock = Lock()
knowledge_base_init_lock = Lock()


def get_rag_system() -> RAGSystem:
    global rag_system
    global rag_system_init_error
    if rag_system is not None:
        return rag_system
    with rag_system_lock:
        if rag_system is not None:
            return rag_system
        try:
            rag_system = RAGSystem()
            rag_system_init_error = None
            return rag_system
        except Exception as exc:
            rag_system_init_error = exc
            logger.exception("初始化 RAG 系统失败")
            raise RuntimeError(f"RAG system initialization failed: {exc}") from exc


def ensure_database_ready() -> None:
    global database_ready
    global database_init_error
    if database_ready:
        return
    with database_init_lock:
        if database_ready:
            return
        try:
            init_database()
            database_ready = True
            database_init_error = None
        except Exception as exc:
            database_init_error = exc
            logger.exception("初始化数据库失败")
            raise RuntimeError(f"Database initialization failed: {exc}") from exc


def build_knowledge_summary(document_count: int, character_count: int) -> dict:
    return {
        "document_count": document_count,
        "character_count": character_count,
        "file_count": get_file_count(),
    }


def build_character_items() -> List[dict]:
    ensure_database_ready()
    return list_character_profiles()


def refresh_knowledge_base(
    documents: Optional[List[dict]] = None,
    loaded_files: Optional[List[dict]] = None,
) -> dict:
    ensure_database_ready()
    rag = get_rag_system()
    loaded_files = (
        loaded_files
        if loaded_files is not None
        else load_upload_manifest().get("files", [])
    )
    documents = (
        documents
        if documents is not None
        else load_registered_documents(manifest_entries=loaded_files)
    )
    loaded_count = rag.reload_knowledge(documents)
    rag.vector_store.reset_loaded_files_in_milvus(
        build_data_manifest(manifest_entries=loaded_files).get("files", [])
    )
    rag.response_cache.bump_knowledge_version()
    sync_character_profiles(documents, replace_existing=True)
    character_count = len(list_character_profiles())
    logger.info(
        "知识库已刷新: 文档数=%s 角色数=%s 文件数=%s",
        loaded_count,
        character_count,
        len(loaded_files),
    )
    return build_knowledge_summary(loaded_count, character_count)


def append_knowledge_base(
    documents: Optional[List[dict]] = None,
    loaded_files: Optional[List[dict]] = None,
) -> dict:
    ensure_database_ready()
    rag = ensure_knowledge_base_ready()
    documents = documents or []
    loaded_files = loaded_files or []
    rag.append_knowledge(documents)
    rag.vector_store.append_loaded_files_in_milvus(
        build_data_manifest(manifest_entries=loaded_files).get("files", [])
    )
    rag.response_cache.bump_knowledge_version()
    sync_character_profiles(documents, replace_existing=False)
    character_count = len(list_character_profiles())
    summary = build_knowledge_summary(
        rag.vector_store.get_document_count(),
        character_count,
    )
    logger.info(
        "知识库已追加: 文档总数=%s 角色数=%s 新文件数=%s",
        summary["document_count"],
        summary["character_count"],
        len(loaded_files),
    )
    return summary


def initialize_knowledge_base() -> dict:
    ensure_database_ready()
    rag = get_rag_system()
    if (
        rag.vector_store.has_character_collection()
        and rag.vector_store.character_collection_uses_builtin_bm25()
    ):
        document_count = rag.vector_store.get_document_count()
        rag._initialized = True
        sync_character_profiles(
            rag.vector_store.load_character_documents_from_milvus(),
            replace_existing=True,
        )
        character_count = len(list_character_profiles())
        summary = build_knowledge_summary(document_count, character_count)
        logger.info(
            "已从 Milvus 缓存初始化知识库: 文档数=%s 角色数=%s",
            document_count,
            character_count,
        )
        return summary
    return refresh_knowledge_base()


def ensure_knowledge_base_ready() -> RAGSystem:
    ensure_database_ready()
    with knowledge_base_init_lock:
        rag = get_rag_system()
        if not rag._initialized:
            initialize_knowledge_base()
        return rag


async def bootstrap_application(app: FastAPI) -> None:
    try:
        app.state.startup_stage = "initializing_database"
        logger.info("后台开始初始化数据库")
        await asyncio.to_thread(ensure_database_ready)

        app.state.startup_stage = "initializing_knowledge_base"
        logger.info("后台开始初始化知识库")
        summary = await asyncio.to_thread(initialize_knowledge_base)
        app.state.startup_ready = True
        app.state.startup_error = None
        app.state.startup_summary = summary
        app.state.startup_stage = "ready"
        logger.info("应用启动完成: 摘要=%s", summary)
    except Exception as exc:
        app.state.startup_ready = False
        app.state.startup_error = str(exc)
        app.state.startup_stage = "failed"
        logger.exception("应用启动失败")
