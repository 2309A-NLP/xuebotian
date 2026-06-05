from __future__ import annotations

from typing import Any

from app.models.domain import ChunkRecord, TableBlock
from app.services.document.chunk_models import _Counter
from app.services.document.table_processor import format_page_range, serialize_table


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
        if not serialized.strip():
            return

        metadata = self._table_metadata(table, table_index, document_title)
        if len(serialized) <= self.chunk_size:
            chunks.append(
                self._make_chunk(
                    doc_id=doc_id,
                    file_name=file_name,
                    text=serialized,
                    page_start=table.page_start,
                    page_end=table.page_end,
                    kind="table",
                    counter=counter,
                    extra_metadata=metadata,
                )
            )
            return

        for piece_index, piece in enumerate(self._split_table_rows(table), start=1):
            chunks.append(
                self._make_chunk(
                    doc_id=doc_id,
                    file_name=file_name,
                    text=piece,
                    page_start=table.page_start,
                    page_end=table.page_end,
                    kind="table",
                    counter=counter,
                    extra_metadata={**metadata, "table_piece": piece_index},
                )
            )

    def _table_metadata(
        self,
        table: TableBlock,
        table_index: int,
        document_title: str = "",
    ) -> dict[str, Any]:
        metadata = {
            "table_index": table_index,
            "table_caption": table.caption,
            "table_reference_text": table.reference_text,
            "table_header": [cell for cell in table.header if cell],
            "table_row_count": len(table.rows),
            "page_range": format_page_range(table.page_start, table.page_end),
        }
        if document_title:
            metadata["document_title"] = document_title
        return metadata

    def _split_table_rows(self, table: TableBlock) -> list[str]:
        pieces: list[str] = []
        buffer: list[list[str]] = []
        current_len = 0

        def flush() -> None:
            if not buffer:
                return
            sub_table = TableBlock(
                page_start=table.page_start,
                page_end=table.page_end,
                header=table.header,
                rows=list(buffer),
                caption=table.caption,
                reference_text=table.reference_text,
            )
            pieces.append(serialize_table(sub_table))
            buffer.clear()

        for row in table.rows:
            row_table = TableBlock(
                page_start=table.page_start,
                page_end=table.page_end,
                header=table.header,
                rows=[row],
                caption="",
            )
            row_text_len = len(serialize_table(row_table))
            if buffer and current_len + row_text_len > self.chunk_size:
                flush()
                current_len = 0
            buffer.append(row)
            current_len += row_text_len
        flush()
        return [piece for piece in pieces if piece.strip()]
