from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import DATA_DIR, DATA_FILE
from app.services.ingestion.constants import SUPPORTED_UPLOAD_SUFFIXES
from app.services.ingestion.text_utils import clean_name, normalize_knowledge_scope


def iter_data_files(data_dir: Path = DATA_DIR) -> List[Path]:
    if not data_dir.exists():
        return []
    files = []
    for path in data_dir.iterdir():
        if path.is_file() and path.suffix.lower() in SUPPORTED_UPLOAD_SUFFIXES:
            files.append(path)
    return sorted(files)


def resolve_data_files(data_dir: Path = DATA_DIR) -> List[Path]:
    data_files = iter_data_files(data_dir)
    if not data_files and DATA_FILE.exists():
        return [DATA_FILE]
    return data_files


def build_data_manifest(
    file_path: Optional[Path] = None,
    manifest_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    files = []
    if manifest_entries is not None:
        for item in manifest_entries:
            saved_name = item.get("saved_name") or item.get("name") or ""
            if not saved_name:
                continue
            path = DATA_DIR / saved_name
            if not path.exists():
                continue
            stat = path.stat()
            files.append(
                {
                    "name": saved_name,
                    "saved_name": saved_name,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "original_name": item.get("original_name") or saved_name,
                    "knowledge_scope": normalize_knowledge_scope(
                        item.get("knowledge_scope")
                    ),
                    "target_role": clean_name(item.get("target_role") or ""),
                }
            )
        return {"version": 2, "files": files}

    paths = [file_path] if file_path else resolve_data_files(DATA_DIR)
    for path in paths:
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "saved_name": path.name,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return {"version": 2, "files": files}
