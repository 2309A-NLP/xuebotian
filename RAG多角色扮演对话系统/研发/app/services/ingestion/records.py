from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.services.ingestion.constants import (
    NAME_FIELD_CANDIDATES,
    SOURCE_FIELD_CANDIDATES,
    SUMMARY_FIELD_CANDIDATES,
    TEXT_FIELD_CANDIDATES,
)
from app.services.ingestion.text_utils import (
    build_access_key,
    build_parent_id,
    build_source_title,
    build_summary,
    canonical_text,
    clean_inline_text,
    clean_name,
    clean_text,
    extract_aliases,
    extract_first_value,
    normalize_knowledge_scope,
)

MAX_RECORD_MESSAGE_LENGTH = 60000
MAX_SOURCE_FILE_LENGTH = 512
MAX_SOURCE_TITLE_LENGTH = 255
MAX_ORIGINAL_NAME_LENGTH = 255


def normalize_items(
    data: Iterable[Dict[str, Any]],
    source_name: str,
    source_file_name: str = "",
) -> List[Dict[str, Any]]:
    cleaned_data: List[Dict[str, Any]] = []
    seen_records = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"{source_name} must contain object items")
        name = clean_name(extract_first_value(item, NAME_FIELD_CANDIDATES))
        message = clean_text(extract_first_value(item, TEXT_FIELD_CANDIDATES))
        if not name or not message:
            continue
        if len(message) > MAX_RECORD_MESSAGE_LENGTH:
            message = message[:MAX_RECORD_MESSAGE_LENGTH].rstrip()
        source_file = (
            clean_inline_text(extract_first_value(item, SOURCE_FIELD_CANDIDATES))
            or source_file_name
        )
        source_file = source_file[:MAX_SOURCE_FILE_LENGTH]
        aliases = extract_aliases(item)
        summary = build_summary(
            extract_first_value(item, SUMMARY_FIELD_CANDIDATES) or message
        )
        record_key = (name, source_file, canonical_text(message))
        if record_key in seen_records:
            continue
        seen_records.add(record_key)
        normalized_item = {
            "name": name,
            "message": message,
            "summary": summary,
            "parent_id": build_parent_id(name, source_file, message),
            "source_title": build_source_title(source_file)[:MAX_SOURCE_TITLE_LENGTH],
            "aliases": aliases,
        }
        if source_file:
            normalized_item["source_file"] = source_file
        cleaned_data.append(normalized_item)
    return cleaned_data


def apply_ingestion_metadata(
    records: List[Dict[str, Any]],
    file_path: Path,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    metadata = metadata or {}
    target_role = clean_name(metadata.get("target_role") or "")
    knowledge_scope = normalize_knowledge_scope(
        metadata.get("knowledge_scope") or "shared"
    )
    scope_key = target_role if knowledge_scope == "private" else ""
    access_key = build_access_key(knowledge_scope, scope_key)
    saved_name = clean_inline_text(metadata.get("saved_name") or file_path.name)[
        :MAX_SOURCE_FILE_LENGTH
    ]
    original_name = clean_inline_text(metadata.get("original_name") or file_path.name)[
        :MAX_ORIGINAL_NAME_LENGTH
    ]
    source_title = build_source_title(original_name or saved_name)[
        :MAX_SOURCE_TITLE_LENGTH
    ]
    source_kind = file_path.suffix.lower()

    cleaned_records: List[Dict[str, Any]] = []
    seen = set()
    for record in records:
        resolved_name = target_role or clean_name(record.get("name") or "")
        message = clean_text(record.get("message") or "")
        if not resolved_name or not message:
            continue
        if len(message) > MAX_RECORD_MESSAGE_LENGTH:
            message = message[:MAX_RECORD_MESSAGE_LENGTH].rstrip()
        aliases = (
            record.get("aliases") if isinstance(record.get("aliases"), list) else []
        )
        normalized_record = {
            "name": resolved_name,
            "message": message,
            "summary": build_summary(record.get("summary") or message),
            "parent_id": build_parent_id(resolved_name, saved_name, message),
            "source_title": source_title,
            "aliases": aliases,
            "source_file": saved_name,
            "original_name": original_name,
            "source_kind": source_kind,
            "knowledge_scope": knowledge_scope,
            "scope_key": scope_key,
            "access_key": access_key,
        }
        dedupe_key = (
            normalized_record["name"],
            normalized_record["access_key"],
            normalized_record["source_file"],
            canonical_text(normalized_record["message"]),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        cleaned_records.append(normalized_record)
    return cleaned_records
