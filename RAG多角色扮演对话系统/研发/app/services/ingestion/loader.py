from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import DATA_DIR
from app.services.ingestion.constants import SUPPORTED_UPLOAD_SUFFIXES
from app.services.ingestion.manifest import (
    build_data_manifest,
    iter_data_files,
    resolve_data_files,
)
from app.services.ingestion.readers import load_json_records, load_plain_text_records
from app.services.ingestion.records import apply_ingestion_metadata
from app.services.ingestion.text_utils import (
    build_access_key,
    clean_inline_text,
    clean_name,
    clean_text,
    normalize_knowledge_scope,
)


def load_single_data_file(
    file_path: Path, metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        records = load_json_records(file_path)
    elif suffix in {".txt", ".pdf", ".docx"}:
        records = load_plain_text_records(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    return apply_ingestion_metadata(records, file_path=file_path, metadata=metadata)


def load_data(
    file_path: Optional[Path] = None,
    manifest_entries: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if file_path:
        return load_single_data_file(file_path)

    all_data: List[Dict[str, Any]] = []
    if manifest_entries is not None:
        for item in manifest_entries:
            saved_name = item.get("saved_name") or item.get("name") or ""
            if not saved_name:
                continue
            current_path = DATA_DIR / saved_name
            if current_path.exists():
                all_data.extend(load_single_data_file(current_path, metadata=item))
        return all_data

    for current_file in resolve_data_files(DATA_DIR):
        all_data.extend(load_single_data_file(current_file))
    return all_data
