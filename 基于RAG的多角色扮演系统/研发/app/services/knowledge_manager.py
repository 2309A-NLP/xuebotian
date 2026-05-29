import re
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pymilvus import MilvusClient

from app.core.config import DATA_DIR, MILVUS_COLLECTION_NAME, MILVUS_DB_NAME, MILVUS_URI
from app.core.logging_utils import get_logger
from app.services.data_loader import (
    SUPPORTED_UPLOAD_SUFFIXES,
    clean_inline_text,
    clean_name,
    load_data,
    load_single_data_file,
    normalize_knowledge_scope,
)


SAFE_FILE_NAME_PATTERN = re.compile(r"[^\w\-]+", re.UNICODE)
LOADED_FILE_COLLECTION_NAME = f"{MILVUS_COLLECTION_NAME }_loaded_files"
_milvus_client: Optional[MilvusClient] = None
logger = get_logger(__name__)


def _get_milvus_client() -> MilvusClient:
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient(uri=MILVUS_URI, db_name=MILVUS_DB_NAME)
    return _milvus_client


def _query_all_by_id(
    collection_name: str,
    output_fields: List[str],
    limit: int,
    batch_size: int = 5000,
) -> List[Dict]:
    client = _get_milvus_client()
    rows: List[Dict] = []
    last_id = -1
    normalized_batch_size = max(1, min(batch_size, 16000))
    normalized_limit = max(0, limit)

    while len(rows) < normalized_limit:
        current_limit = min(normalized_batch_size, normalized_limit - len(rows))
        query_rows = client.query(
            collection_name=collection_name,
            filter=f"id > {last_id }",
            output_fields=["id", *output_fields],
            limit=current_limit,
        )
        if not query_rows:
            break

        rows.extend(query_rows)
        last_id = max(int(row.get("id", last_id) or last_id) for row in query_rows)
        if len(query_rows) < current_limit:
            break

    return rows


def _sanitize_file_stem(file_name: str) -> str:
    stem = Path(file_name or "").stem or "knowledge"
    return SAFE_FILE_NAME_PATTERN.sub("_", stem).strip("._-") or "knowledge"


def build_random_saved_name(original_name: str) -> str:
    suffix = Path(original_name or "").suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise ValueError(
            f"Unsupported file type: {suffix or 'unknown'}, allowed: {', '.join (sorted (SUPPORTED_UPLOAD_SUFFIXES ))}"
        )
    random_part = uuid.uuid4().hex[:12]
    safe_stem = _sanitize_file_stem(original_name)
    return f"{random_part }_{safe_stem }{suffix }"


def _normalize_manifest_entry(item: Dict) -> Dict:

    saved_name = clean_inline_text(item.get("saved_name") or "")
    if not saved_name:
        return {}

    file_path = DATA_DIR / saved_name
    size = int(item.get("size") or item.get("file_size") or 0)
    mtime_ns = int(item.get("mtime_ns") or item.get("file_mtime_ns") or 0)
    if file_path.exists():
        stat = file_path.stat()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns

    normalized = {
        "saved_name": saved_name,
        "original_name": clean_inline_text(item.get("original_name") or saved_name)[
            :255
        ],
        "knowledge_scope": normalize_knowledge_scope(
            item.get("knowledge_scope") or "shared"
        ),
        "target_role": clean_name(item.get("target_role") or ""),
        "source_kind": clean_inline_text(
            item.get("source_kind") or file_path.suffix.lower()
        )[:32],
        "size": size,
        "mtime_ns": mtime_ns,
        "uploaded_at": clean_inline_text(item.get("uploaded_at") or ""),
    }

    if not normalized["uploaded_at"]:
        timestamp = (
            file_path.stat().st_mtime
            if file_path.exists()
            else datetime.now().timestamp()
        )
        normalized["uploaded_at"] = datetime.fromtimestamp(timestamp).isoformat()
    return normalized


def normalize_manifest_entries(files: Optional[List[Dict]]) -> List[Dict]:
    normalized_files = []
    for item in files or []:
        normalized = _normalize_manifest_entry(item)
        if not normalized:
            continue
        if not (DATA_DIR / normalized["saved_name"]).exists():
            continue
        normalized_files.append(normalized)
    return normalized_files


def _load_loaded_files_from_milvus(limit: int = 10000) -> List[Dict]:

    client = _get_milvus_client()
    try:
        if not client.has_collection(LOADED_FILE_COLLECTION_NAME):
            return []
    except Exception:
        logger.error(
            "检查 Milvus 已加载文件集合失败，已降级返回空列表。\n%s",
            traceback.format_exc(),
        )
        return []

    rows = _query_all_by_id(
        collection_name=LOADED_FILE_COLLECTION_NAME,
        output_fields=[
            "saved_name",
            "original_name",
            "knowledge_scope",
            "target_role",
            "source_kind",
            "file_size",
            "file_mtime_ns",
            "uploaded_at",
        ],
        limit=limit,
    )
    entries = [
        {
            "saved_name": row.get("saved_name", ""),
            "original_name": row.get("original_name", ""),
            "knowledge_scope": row.get("knowledge_scope", "shared"),
            "target_role": row.get("target_role", ""),
            "source_kind": row.get("source_kind", ""),
            "size": int(row.get("file_size", 0) or 0),
            "mtime_ns": int(row.get("file_mtime_ns", 0) or 0),
            "uploaded_at": row.get("uploaded_at", ""),
        }
        for row in rows
        if row.get("saved_name")
    ]

    return normalize_manifest_entries(entries)


def load_upload_manifest() -> Dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return {"version": 2, "files": _load_loaded_files_from_milvus()}


def _entry_matches_scope(entry: Dict, knowledge_scope: str, target_role: str) -> bool:
    normalized_scope = normalize_knowledge_scope(knowledge_scope)
    normalized_role = clean_name(target_role)
    entry_scope = normalize_knowledge_scope(entry.get("knowledge_scope") or "shared")
    entry_role = clean_name(entry.get("target_role") or "")

    if entry_scope != normalized_scope:
        return False
    if normalized_scope == "private":
        return bool(normalized_role) and entry_role == normalized_role
    return True


def _delete_manifest_files(entries: List[Dict]) -> None:
    for item in entries:
        saved_name = item.get("saved_name") or ""
        if not saved_name:
            continue
        file_path = DATA_DIR / saved_name
        if file_path.exists():
            file_path.unlink()


def load_registered_documents(
    manifest_entries: Optional[List[Dict]] = None,
) -> List[Dict]:

    entries = (
        normalize_manifest_entries(manifest_entries)
        if manifest_entries is not None
        else load_upload_manifest().get("files", [])
    )
    return load_data(manifest_entries=entries)


def list_uploaded_files() -> List[Dict]:
    items = []
    for item in load_upload_manifest().get("files", []):
        items.append(
            {
                "name": item.get("saved_name", ""),
                "saved_name": item.get("saved_name", ""),
                "original_name": item.get("original_name", ""),
                "size": int(item.get("size", 0) or 0),
                "updated_at": item.get("uploaded_at", ""),
                "knowledge_scope": item.get("knowledge_scope", "shared"),
                "target_role": item.get("target_role", ""),
                "source_kind": item.get("source_kind", ""),
            }
        )
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return items


def get_file_count() -> int:
    return len(load_upload_manifest().get("files", []))


def save_uploaded_file(
    raw: bytes,
    original_name: str,
    knowledge_scope: str,
    import_mode: str,
    target_role: str = "",
) -> Dict:
    if not original_name:
        raise ValueError("Please select a file to upload")

    normalized_scope = normalize_knowledge_scope(knowledge_scope)
    normalized_role = clean_name(target_role)
    normalized_mode = (
        "full" if (import_mode or "").strip().lower() == "full" else "incremental"
    )
    suffix = Path(original_name).suffix.lower()

    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise ValueError("Only JSON, TXT, PDF, and DOCX files are supported")
    if suffix in {".txt", ".pdf", ".docx"} and not normalized_role:
        raise ValueError("TXT、PDF、DOCX 文件上传时必须指定角色")
    if normalized_scope == "private" and not normalized_role:
        raise ValueError("独立知识库上传时必须指定角色")

    existing_entries = load_upload_manifest().get("files", [])

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved_name = build_random_saved_name(original_name)
    saved_path = DATA_DIR / saved_name
    saved_path.write_bytes(raw)

    manifest_entry = {
        "saved_name": saved_name,
        "original_name": clean_inline_text(original_name)[:255],
        "knowledge_scope": normalized_scope,
        "target_role": normalized_role,
        "source_kind": suffix,
        "size": saved_path.stat().st_size,
        "mtime_ns": saved_path.stat().st_mtime_ns,
        "uploaded_at": datetime.now().isoformat(),
    }

    try:
        records = load_single_data_file(saved_path, metadata=manifest_entry)
        if not records:
            raise ValueError("Uploaded file does not contain usable knowledge")

        removed_entries: List[Dict] = []
        if normalized_mode == "full":
            removed_entries = [
                item
                for item in existing_entries
                if _entry_matches_scope(item, normalized_scope, normalized_role)
            ]
            existing_entries = [
                item
                for item in existing_entries
                if not _entry_matches_scope(item, normalized_scope, normalized_role)
            ]

        next_entries = [*existing_entries, manifest_entry]
        if removed_entries:
            _delete_manifest_files(removed_entries)

        return {
            "entry": manifest_entry,
            "entries": next_entries,
            "records": records,
            "removed_count": len(removed_entries),
            "import_mode": normalized_mode,
        }
    except Exception:
        logger.error(
            "保存上传文件失败，准备清理临时文件。\n%s",
            traceback.format_exc(),
        )
        if saved_path.exists():
            saved_path.unlink()
        raise
