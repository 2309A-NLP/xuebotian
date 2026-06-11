from __future__ import annotations

import json
import logging
from typing import Any

try:
    from pymilvus import DataType, Function, FunctionType
except ImportError:
    from pymilvus import DataType

    Function = None
    FunctionType = None

BM25_TEXT_FIELD_NAME = "bm25_text"
BM25_INDEX_FIELD_NAME = "bm25_keyword_index"

logger = logging.getLogger(__name__)


class MilvusHelperMixin:
    """封装 Milvus 字段、元数据和能力判断的公共辅助逻辑。"""
    def _describe_fields(self) -> set[str]:
        """处理describe字段列表。"""
        try:
            description = self.client.describe_collection(
                collection_name=self.collection_name
            )
        except Exception:
            logger.exception("Failed to describe Milvus collection: %s", self.collection_name)
            return {
                "chunk_id",
                "doc_id",
                "page",
                "page_end",
                "chunk_index",
                "chunk_type",
                "source_file",
                "metadata_json",
                "text",
                BM25_TEXT_FIELD_NAME,
                "embedding",
                BM25_INDEX_FIELD_NAME,
            }

        fields = description.get("fields") or description.get("schema", {}).get("fields", [])
        names: set[str] = set()
        for field in fields:
            if isinstance(field, dict):
                name = field.get("name") or field.get("field_name")
            else:
                name = getattr(field, "name", None)
            if name:
                names.add(str(name))
        return names

    def _hybrid_capable(self) -> bool:
        """处理混合检索能力capable。"""
        return (
            self.settings.hybrid_search_enabled
            and Function is not None
            and FunctionType is not None
            and hasattr(DataType, "SPARSE_FLOAT_VECTOR")
        )

    def _can_hybrid_search(self, query_text: str | None) -> bool:
        """判断是否可以混合检索能力search。"""
        field_names = self._field_names or self._describe_fields()
        self._field_names = field_names
        return (
            self._hybrid_capable()
            and bool(query_text and query_text.strip())
            and BM25_INDEX_FIELD_NAME in field_names
            and BM25_TEXT_FIELD_NAME in field_names
            and "embedding" in field_names
        )

    def _filter_record_fields(self, record: dict[str, Any]) -> dict[str, Any]:
        """处理字段过滤结果记录字段列表。"""
        field_names = self._field_names or self._describe_fields()
        self._field_names = field_names
        if not field_names:
            return record
        return {key: value for key, value in record.items() if key in field_names}

    def _search_output_fields(self) -> list[str]:
        """处理search输出字段字段列表。"""
        field_names = self._field_names or self._describe_fields()
        self._field_names = field_names
        wanted = [
            "chunk_id",
            "doc_id",
            "page",
            "page_end",
            "chunk_type",
            "source_file",
            "metadata_json",
            "text",
            BM25_TEXT_FIELD_NAME,
        ]
        if not field_names:
            return wanted
        return [field for field in wanted if field in field_names]

    def _metadata_json(self, metadata: dict[str, Any]) -> str:
        """处理元数据JSON 响应。"""
        compact = dict(metadata)
        if compact.get("type") == "table":
            compact.pop("table_pre_text", None)
            compact.pop("table_post_text", None)
        payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= 4096:
            return payload
        for key in ("table_pre_text", "table_post_text", "table_reference_text", "document_title"):
            value = compact.get(key)
            if isinstance(value, str):
                compact[key] = value[:512]
        header = compact.get("table_header")
        if isinstance(header, list):
            compact["table_header"] = [
                str(cell)[:64] for cell in header[:12] if str(cell).strip()
            ]
        caption = compact.get("table_caption")
        if isinstance(caption, str):
            compact["table_caption"] = caption[:256]
        payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= 4096:
            return payload
        for key in (
            "table_pre_text",
            "table_post_text",
            "table_reference_text",
            "table_header",
            "structure_scope",
            "heading",
            "chapter",
            "section",
            "document_title",
        ):
            compact.pop(key, None)
        payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= 4096:
            return payload
        return json.dumps(
            {
                "type": compact.get("type"),
                "page": compact.get("page"),
                "page_end": compact.get("page_end"),
                "table_caption": compact.get("table_caption"),
                "table_index": compact.get("table_index"),
                "table_row_count": compact.get("table_row_count"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )[:4096]

    def _load_metadata(self, value: Any) -> dict[str, Any]:
        """加载元数据。"""
        if not isinstance(value, str) or not value:
            return {}
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def warmup(self, dimension: int | None = None) -> None:
        """预热底层资源，降低首次调用的初始化开销。"""
        if dimension is not None:
            self._ensure_collection(dimension)
            logger.info("Milvus collection warmed up: %s", self.collection_name)
            return

        if self.client.has_collection(collection_name=self.collection_name):
            self.client.load_collection(
                collection_name=self.collection_name,
                replica_number=1,
            )
            self._loaded = True
            logger.info("Milvus collection warmed up: %s", self.collection_name)

