from __future__ import annotations

from typing import Any

from app.models.domain import ChunkRecord, TableBlock
from app.services.document.chunk_models import _Counter
from app.services.document.table_processor import (
    format_page_range,
    serialize_table,
)


class TableChunkMixin:
    def _chunk_table(
        self,
        doc_id: str,
        file_name: str,
        table: TableBlock,
        table_index: int,
        chunks: list[ChunkRecord],
        counter: _Counter,
        document_title: str = "",
    ) -> None:
        serialized = serialize_table(table)
        metadata = self._table_metadata(table, table_index, document_title)
        if serialized.strip():
            chunks.append(
                self._make_chunk(
                    doc_id=doc_id,
                    file_name=file_name,
                    text=serialized,
                    page_start=table.page_start,
                    page_end=table.page_end,
                    kind="table",
                    counter=counter,
                    extra_metadata={**metadata, "table_granularity": "table"},
                )
            )

    def _table_metadata(
        self,
        table: TableBlock,
        table_index: int,
        document_title: str = "",
    ) -> dict[str, Any]:
        pre_text = table.pre_text or table.reference_text
        metadata = {
            "table_index": table_index,
            "table_caption": table.caption,
            "table_reference_text": table.reference_text,
            "table_pre_text": pre_text,
            "table_post_text": table.post_text,
            "table_header": [cell for cell in table.header if cell],
            "table_row_count": len(table.rows),
            "page_range": format_page_range(table.page_start, table.page_end),
        }
        if document_title:
            metadata["document_title"] = document_title
        return metadata
