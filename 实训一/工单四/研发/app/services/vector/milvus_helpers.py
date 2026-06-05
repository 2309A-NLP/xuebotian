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
    def _describe_fields(self) -> set[str]:
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
        return (
            self.settings.hybrid_search_enabled
            and Function is not None
            and FunctionType is not None
            and hasattr(DataType, "SPARSE_FLOAT_VECTOR")
        )

    def _can_hybrid_search(self, query_text: str | None) -> bool:
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
        field_names = self._field_names or self._describe_fields()
        self._field_names = field_names
        if not field_names:
            return record
        return {key: value for key, value in record.items() if key in field_names}

    def _search_output_fields(self) -> list[str]:
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
        payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= 4096:
            return payload
        compact = dict(metadata)
        header = compact.get("table_header")
        if isinstance(header, list):
            compact["table_header"] = header[:30]
        caption = compact.get("table_caption")
        if isinstance(caption, str):
            compact["table_caption"] = caption[:512]
        payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= 4096:
            return payload
        return json.dumps(
            {
                "type": compact.get("type"),
                "page": compact.get("page"),
                "page_end": compact.get("page_end"),
                "table_caption": compact.get("table_caption"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )[:4096]

    def _load_metadata(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, str) or not value:
            return {}
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def warmup(self, dimension: int | None = None) -> None:
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

