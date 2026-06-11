from __future__ import annotations

import re
from typing import Any

from app.models.domain import ChunkRecord
from app.services.document.chunk_models import _Counter
from app.utils.id_generator import generate_chunk_id


class ChunkRecordMixin:
    """提供统一的切片记录构造逻辑。

    文本块、表格块和图片块最终都会落到 ``ChunkRecord``，
    这个混入类负责把公共字段、检索辅助文本和去重规则收口到一处。
    """
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
        """把一段内容包装成可入库的 ``ChunkRecord``。

        这里会统一分配切片序号、生成稳定的 ``chunk_id``、
        组织元数据，并额外构建一份偏关键词检索的 ``bm25_text``。
        """
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
        """构建供 BM25 或关键词检索使用的增强文本。

        相比原始正文，这里会把标题、页码、结构范围、表头、图片标题等辅助信息
        一并拼进去，让传统倒排检索也能利用结构化线索召回更合适的结果。
        """
        lines = [f"文档：{file_name}"]
        document_title = str(metadata.get("document_title") or "").strip()
        if document_title:
            lines.append(f"文章标题：{document_title}")

        content_type = metadata.get("type")
        if content_type == "table":
            page_range = f"{page_start}-{page_end}" if page_end != page_start else str(page_start)
            pre_text = str(
                metadata.get("table_pre_text")
                or metadata.get("table_reference_text")
                or ""
            ).strip()
            if pre_text:
                lines.append(f"上文说明：{pre_text}")
            caption = str(metadata.get("table_caption") or "").strip()
            if caption:
                lines.append(f"表格标题：{caption}")
            header = metadata.get("table_header")
            if isinstance(header, list):
                header_text = "；".join(str(cell).strip() for cell in header if str(cell).strip())
                if header_text:
                    lines.append(f"表头：{header_text}")
            post_text = str(metadata.get("table_post_text") or "").strip()
            if post_text:
                lines.append(f"下文说明：{post_text}")
            lines.append(f"页码：{page_range}")
        elif content_type == "image":
            image_kind = str(metadata.get("image_kind") or "").strip()
            if image_kind:
                lines.append(f"图片类型：{image_kind}")
            caption = str(metadata.get("image_caption") or "").strip()
            if caption:
                lines.append(f"图片标题：{caption}")
        else:
            page_range = f"{page_start}-{page_end}" if page_end != page_start else str(page_start)
            lines.append(f"页码：{page_range}")
            heading = str(metadata.get("heading") or "").strip()
            chapter = str(metadata.get("chapter") or "").strip()
            section = str(metadata.get("section") or "").strip()
            structure_scope = str(metadata.get("structure_scope") or "").strip()
            is_heading_lead = bool(metadata.get("is_heading_lead"))
            paragraph_count = int(metadata.get("paragraph_count") or 0)
            if structure_scope:
                lines.append(f"结构范围：{structure_scope}")
            if heading:
                lines.append(f"标题：{heading}")
            else:
                if chapter:
                    lines.append(f"章节：{chapter}")
                if section:
                    lines.append(f"小节：{section}")
            if is_heading_lead:
                lines.append("结构位置：小节首块")
            if paragraph_count > 0:
                lines.append(f"段落数：{paragraph_count}")

        lines.append(f"正文：{text}")
        return "\n".join(line for line in lines if line.strip())

    def _dedupe_chunks(self, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
        """按内容签名去掉重复切片。

        某些 PDF 在解析或跨页拼接后可能生成内容高度重复的切片，
        这里通过归一化文本签名做一次轻量去重，减少冗余入库。
        """
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
        """生成用于切片去重的粗粒度签名。

        这里会忽略页码和尾部纯数字等弱区分信息，
        尽量只保留真正能代表内容主体的部分。
        """
        compact = self._content_signature(text)
        compact = re.sub(r"页码：\d+(?:-\d+)?", "", compact)
        compact = re.sub(r"\d{1,4}$", "", compact)
        return compact[:600]

    def _content_signature(self, text: str) -> str:
        """把文本压缩成便于比较的无空白签名。"""
        return re.sub(r"\s+", "", text)
