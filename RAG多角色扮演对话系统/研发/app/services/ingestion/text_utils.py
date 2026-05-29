import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.services.ingestion.constants import (
    ALIAS_FIELD_CANDIDATES,
    WHITESPACE_TRANSLATION,
    ZERO_WIDTH_TRANSLATION,
)


def normalize_knowledge_scope(scope: str) -> str:
    return "private" if (scope or "").strip().lower() == "private" else "shared"


def build_access_key(scope: str, scope_key: str = "") -> str:
    normalized_scope = normalize_knowledge_scope(scope)
    normalized_scope_key = clean_name(scope_key)
    if normalized_scope == "private" and normalized_scope_key:
        return f"private::{normalized_scope_key}"
    return "shared"


def coerce_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(
            part for part in (coerce_to_text(item) for item in value) if part
        )
    if isinstance(value, dict):
        return "\n".join(
            f"{key}: {text_value}"
            for key, item_value in value.items()
            if (text_value := coerce_to_text(item_value))
        )
    return str(value)


def normalize_unicode(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.translate(ZERO_WIDTH_TRANSLATION)
    return normalized.translate(WHITESPACE_TRANSLATION)


def clean_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_unicode(text)).strip()


def clean_name(text: str) -> str:
    normalized = clean_inline_text(text)
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_\-\s]+", normalized):
        normalized = re.sub(r"\s+", "", normalized)
    return normalized[:255]


def _clean_slash_noise(text: str) -> str:
    cleaned = re.sub(r"(?<!\S)/{2,}(?!\S)", " ", text)
    cleaned = re.sub(r"(?<![:\w\u4e00-\u9fff])/(?![:\w\u4e00-\u9fff])", " ", cleaned)
    cleaned = re.sub(
        r"(?:(?<=\s)/(?=\s)|(?<=^)/(?=\s)|(?<=\s)/(?=$))",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def clean_text(text: str) -> str:
    normalized = re.sub(r"\n{3,}", "\n\n", normalize_unicode(text))
    cleaned_lines: List[str] = []
    previous_line_key = ""
    for raw_line in normalized.split("\n"):
        line = re.sub(r"[ \f\v]+", " ", raw_line).strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            previous_line_key = ""
            continue
        line = _clean_slash_noise(line)
        line = re.sub(r"\s*([：])\s*", r"\1 ", line)
        line = re.sub(r"\s*:(?!//)\s*", ": ", line)
        line = re.sub(r"\s{2,}", " ", line).strip()
        dedupe_key = re.sub(r"\s+", "", line).lower()
        if dedupe_key == previous_line_key:
            continue
        cleaned_lines.append(line)
        previous_line_key = dedupe_key
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines).strip())


def canonical_text(text: str) -> str:
    return re.sub(r"\s+", "", clean_text(text).lower())


def extract_first_value(item: Dict[str, Any], candidates: Iterable[str]) -> str:
    for field_name in candidates:
        if field_name in item:
            value = coerce_to_text(item.get(field_name))
            if value and value.strip():
                return value
    return ""


def extract_aliases(item: Dict[str, Any]) -> List[str]:
    aliases: List[str] = []
    seen = set()
    for field_name in ALIAS_FIELD_CANDIDATES:
        if field_name not in item:
            continue
        raw_value = item.get(field_name)
        values = (
            raw_value
            if isinstance(raw_value, list)
            else re.split(r"[,/|;，、\s]+", coerce_to_text(raw_value))
        )
        for value in values:
            alias = clean_name(coerce_to_text(value))
            if alias and alias not in seen:
                seen.add(alias)
                aliases.append(alias)
    return aliases


def build_source_title(source_file: str) -> str:
    source_name = Path(source_file or "").name
    stem = Path(source_name).stem if source_name else ""
    return clean_inline_text(stem)


def build_summary(text: str, max_length: int = 280) -> str:
    normalized = clean_text(text)
    if not normalized:
        return ""
    selected_lines: List[str] = []
    seen = set()
    for raw_line in normalized.split("\n"):
        line = clean_inline_text(raw_line)
        if not line:
            continue
        normalized_line = line.lower()
        if normalized_line in seen:
            continue
        seen.add(normalized_line)
        selected_lines.append(line)
        if len(" ".join(selected_lines)) >= max_length:
            break
    summary = " ".join(selected_lines).strip()
    if len(summary) <= max_length:
        return summary
    return summary[: max_length - 3].rstrip() + "..."


def build_parent_id(name: str, source_file: str, message: str) -> str:
    payload = "||".join(
        [clean_name(name), clean_inline_text(source_file), canonical_text(message)]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    source_part = clean_inline_text(source_file) or "memory"
    return f"{source_part}::{clean_name(name)}::{digest}"[:512]
