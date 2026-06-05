from __future__ import annotations

import re
from typing import Any

from app.models.domain import ChunkRecord
from app.services.document.chunk_models import _Counter
from app.utils.id_generator import generate_chunk_id


class ChunkRecordMixin:
    def _make_chunk(
        self,
        doc_id: str,
        file_name: str,
        text: str,
        page_start: int,
        page_end: int,
        kind: str,
        counter: _Counter,
        extra_metadata: dict[str, Any] | None = None,
    ) -> ChunkRecord:
        text = text.strip()
        index = counter.next()
        chunk_id = generate_chunk_id(doc_id, index, text)
        metadata: dict[str, Any] = {
            "page": page_start,
            "page_end": page_end,
            "chunk_index": index,
            "type": kind,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        bm25_text = self._build_bm25_text(
            file_name=file_name,
            text=text,
            page_start=page_start,
            page_end=page_end,
            metadata=metadata,
        )
        return ChunkRecord(
            chunk_id=chunk_id,
            doc_id=doc_id,
            text=text,
            bm25_text=bm25_text,
            page=page_start,
            page_end=page_end,
            chunk_index=index,
            source_file=file_name,
            metadata=metadata,
        )

    def _build_bm25_text(
        self,
        file_name: str,
        text: str,
        page_start: int,
        page_end: int,
        metadata: dict[str, Any],
    ) -> str:
        lines = [f"\u6587\u6863\uff1a{file_name}"]
        document_title = str(metadata.get("document_title") or "").strip()
        if document_title:
            lines.append(f"\u6587\u7ae0\u6807\u9898\uff1a{document_title}")
        page_range = f"{page_start}-{page_end}" if page_end != page_start else str(page_start)
        lines.append(f"\u9875\u7801\uff1a{page_range}")

        content_type = metadata.get("type")
        if content_type == "table":
            caption = str(metadata.get("table_caption") or "").strip()
            if caption:
                lines.append(f"\u8868\u683c\uff1a{caption}")
            reference_text = str(metadata.get("table_reference_text") or "").strip()
            if reference_text:
                lines.append(f"\u53c2\u8003\uff1a{reference_text}")
            header = metadata.get("table_header")
            if isinstance(header, list):
                header_text = "\uff0c".join(
                    str(cell).strip() for cell in header if str(cell).strip()
                )
                if header_text:
                    lines.append(f"\u8868\u5934\uff1a{header_text}")
        elif content_type == "image":
            image_kind = str(metadata.get("image_kind") or "").strip()
            caption = str(metadata.get("image_caption") or "").strip()
            width = metadata.get("image_width")
            height = metadata.get("image_height")
            if image_kind:
                lines.append(f"图片类型：{image_kind}")
            if width and height:
                lines.append(f"图片尺寸：{width}x{height}")
            if caption:
                lines.append(f"图片标题：{caption}")
        else:
            heading = str(metadata.get("heading") or "").strip()
            chapter = str(metadata.get("chapter") or "").strip()
            section = str(metadata.get("section") or "").strip()
            if heading:
                lines.append(f"\u6807\u9898\uff1a{heading}")
            else:
                if chapter:
                    lines.append(f"\u7ae0\u8282\uff1a{chapter}")
                if section:
                    lines.append(f"\u5c0f\u8282\uff1a{section}")

        lines.append(f"\u6b63\u6587\uff1a{text}")
        return "\n".join(line for line in lines if line.strip())

    def _dedupe_chunks(self, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
        seen: set[str] = set()
        deduped: list[ChunkRecord] = []
        for chunk in chunks:
            signature = self._chunk_signature(chunk.text)
            if not signature or signature in seen:
                continue
            seen.add(signature)
            deduped.append(chunk)
        return deduped

    def _chunk_signature(self, text: str) -> str:
        compact = self._content_signature(text)
        compact = re.sub(r"\u9875\u7801\uff1a\d+(?:-\d+)?", "", compact)
        compact = re.sub(r"\d{1,4}$", "", compact)
        return compact[:600]

    def _content_signature(self, text: str) -> str:
        return re.sub(r"\s+", "", text)
