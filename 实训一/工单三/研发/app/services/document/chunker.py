from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.domain import ChunkRecord, TableBlock
from app.services.document.table_processor import format_page_range, serialize_table
from app.utils.id_generator import generate_chunk_id
from app.utils.text import normalize_whitespace, split_sentences

_MIN_TEXT_CHARS = 24
_HEADING_MAX_CHARS = 48


@dataclass(slots=True)
class _TextBlock:
    text: str
    heading: str = ""


class DocumentChunker:
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(
        self,
        doc_id: str,
        file_name: str,
        body_pages: list[tuple[int, str]],
        tables: list[TableBlock] | None = None,
    ) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        counter = _Counter()
        for page_number, text in body_pages:
            if text and text.strip():
                self._chunk_body(doc_id, file_name, page_number, text, chunks, counter)
        for table_index, table in enumerate(tables or [], start=1):
            self._chunk_table(doc_id, file_name, table, table_index, chunks, counter)
        return self._dedupe_chunks(chunks)

    def _chunk_body(
        self,
        doc_id: str,
        file_name: str,
        page_number: int,
        text: str,
        chunks: list[ChunkRecord],
        counter: _Counter,
    ) -> None:
        blocks = self._semantic_blocks(text)
        if not blocks:
            return

        for piece, heading in self._pack_blocks(blocks):
            if len(self._content_signature(piece)) < _MIN_TEXT_CHARS:
                continue
            chunks.append(
                self._make_chunk(
                    doc_id=doc_id,
                    file_name=file_name,
                    text=piece,
                    page_start=page_number,
                    page_end=page_number,
                    kind="text",
                    counter=counter,
                    extra_metadata={"heading": heading} if heading else None,
                )
            )

    def _semantic_blocks(self, text: str) -> list[_TextBlock]:
        blocks: list[_TextBlock] = []
        chapter_heading = ""
        section_heading = ""
        buffer: list[str] = []

        def current_heading() -> str:
            return " / ".join(
                part for part in [chapter_heading, section_heading] if part
            )

        def flush() -> None:
            if not buffer:
                return
            block_text = normalize_whitespace("\n".join(buffer))
            if block_text:
                blocks.append(_TextBlock(text=block_text, heading=current_heading()))
            buffer.clear()

        for raw_line in text.splitlines():
            line = normalize_whitespace(raw_line)
            if not line:
                flush()
                continue

            if self._is_heading(line):
                flush()
                if self._is_chapter_heading(line):
                    chapter_heading = line
                    section_heading = ""
                else:
                    section_heading = line
                continue

            if self._is_list_item(line):
                flush()
                blocks.append(_TextBlock(text=line, heading=current_heading()))
                continue

            buffer.append(line)

        flush()
        return blocks

    def _pack_blocks(self, blocks: list[_TextBlock]) -> list[tuple[str, str]]:
        packed: list[tuple[str, str]] = []
        current_parts: list[str] = []
        current_heading = ""
        current_len = 0
        last_block_text = ""

        def render_block(block: _TextBlock) -> str:
            if block.heading and block.heading != current_heading:
                return f"章节：{block.heading}\n{block.text}"
            return block.text

        def flush() -> None:
            nonlocal current_parts, current_len, last_block_text
            if not current_parts:
                return
            text = normalize_whitespace("\n".join(current_parts))
            if text:
                packed.append((text, current_heading))
            last_block_text = current_parts[-1] if current_parts else ""
            current_parts = []
            current_len = 0

        for block in blocks:
            if (
                current_parts
                and block.heading
                and current_heading
                and block.heading != current_heading
            ):
                flush()
            block_text = render_block(block)
            if len(block_text) > self.chunk_size:
                flush()
                packed.extend(self._split_oversized_block(block_text, block.heading))
                last_block_text = block_text
                current_heading = block.heading
                continue

            if current_parts and current_len + len(block_text) + 1 > self.chunk_size:
                flush()
                overlap = self._overlap_context(last_block_text)
                if overlap:
                    current_parts.append(overlap)
                    current_len = len(overlap)

            if block.heading:
                current_heading = block.heading
            current_parts.append(block_text)
            current_len += len(block_text) + 1

        flush()
        return packed

    def _split_oversized_block(self, text: str, heading: str) -> list[tuple[str, str]]:
        prefix = f"章节：{heading}\n" if heading and not text.startswith("章节：") else ""
        sentences = split_sentences(text)
        if not sentences:
            return [(text[: self.chunk_size], heading)]

        chunks: list[tuple[str, str]] = []
        current: list[str] = []
        current_len = len(prefix)
        for sentence in sentences:
            if len(sentence) > self.chunk_size:
                if current:
                    chunks.append((normalize_whitespace(prefix + "".join(current)), heading))
                    current, current_len = [], len(prefix)
                chunks.extend((piece, heading) for piece in self._hard_split(prefix, sentence))
                continue

            if current and current_len + len(sentence) > self.chunk_size:
                chunks.append((normalize_whitespace(prefix + "".join(current)), heading))
                tail = self._sentence_overlap(current)
                current = tail
                current_len = len(prefix) + sum(len(item) for item in current)

            current.append(sentence)
            current_len += len(sentence)

        if current:
            chunks.append((normalize_whitespace(prefix + "".join(current)), heading))
        return [(text, heading) for text, heading in chunks if text.strip()]

    def _sentence_overlap(self, sentences: list[str]) -> list[str]:
        if self.chunk_overlap <= 0:
            return []
        tail: list[str] = []
        total = 0
        for sentence in reversed(sentences):
            if total >= self.chunk_overlap:
                break
            tail.insert(0, sentence)
            total += len(sentence)
        return tail

    def _overlap_context(self, text: str) -> str:
        if self.chunk_overlap <= 0 or not text:
            return ""
        compact = normalize_whitespace(text)
        if len(compact) <= self.chunk_overlap:
            return compact
        return compact[-self.chunk_overlap :]

    def _hard_split(self, prefix: str, sentence: str) -> list[str]:
        max_body_len = max(self.chunk_size - len(prefix), 1)
        step = max(max_body_len - self.chunk_overlap, 1)
        pieces: list[str] = []
        start = 0
        while start < len(sentence):
            end = min(start + max_body_len, len(sentence))
            pieces.append(normalize_whitespace(prefix + sentence[start:end]))
            if end >= len(sentence):
                break
            start += step
        return pieces

    def _is_heading(self, line: str) -> bool:
        compact = line.strip()
        if not compact or len(compact) > _HEADING_MAX_CHARS:
            return False
        if re.search(r"[。！？!?；;]$", compact):
            return False
        patterns = (
            r"^第[一二三四五六七八九十0-9]+[章节部分篇]",
            r"^[一二三四五六七八九十]+[、.]",
            r"^[（(][一二三四五六七八九十0-9]+[）)]",
            r"^\d+(\.\d+)*[、.．]\s*",
        )
        return any(re.match(pattern, compact) for pattern in patterns)

    def _is_chapter_heading(self, line: str) -> bool:
        return bool(re.match(r"^第[一二三四五六七八九十0-9]+[章节部分篇]", line.strip()))

    def _is_list_item(self, line: str) -> bool:
        compact = line.strip()
        return bool(
            re.match(r"^\d+(\.\d+)*[、.．)]", compact)
            or re.match(r"^[（(][0-9一二三四五六七八九十]+[）)]", compact)
            or compact.startswith(("注：", "说明：", "其中："))
        )

    def _chunk_table(
        self,
        doc_id: str,
        file_name: str,
        table: TableBlock,
        table_index: int,
        chunks: list[ChunkRecord],
        counter: _Counter,
    ) -> None:
        serialized = serialize_table(table)
        if not serialized.strip():
            return

        metadata = self._table_metadata(table, table_index)
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

        prefix = self._table_prefix(table)
        for piece_index, piece in enumerate(self._split_table_rows(table, prefix), start=1):
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

    def _table_metadata(self, table: TableBlock, table_index: int) -> dict[str, Any]:
        return {
            "table_index": table_index,
            "table_caption": table.caption,
            "table_header": [cell for cell in table.header if cell],
            "table_row_count": len(table.rows),
            "page_range": format_page_range(table.page_start, table.page_end),
        }

    def _table_prefix(self, table: TableBlock) -> str:
        lines: list[str] = []
        if table.caption.strip():
            lines.append(f"表格：{table.caption.strip()}")
        lines.append(f"页码：{format_page_range(table.page_start, table.page_end)}")
        header = "，".join(name.strip() for name in table.header if name.strip())
        if header:
            lines.append(f"表头：{header}")
        return "\n".join(lines)

    def _split_table_rows(self, table: TableBlock, prefix: str) -> list[str]:
        pieces: list[str] = []
        buffer: list[list[str]] = []
        prefix_len = len(prefix) + 1 if prefix else 0
        current_len = prefix_len

        def flush() -> None:
            if not buffer:
                return
            sub_table = TableBlock(
                page_start=table.page_start,
                page_end=table.page_end,
                header=table.header,
                rows=list(buffer),
                caption="",
            )
            body = serialize_table(sub_table)
            pieces.append(f"{prefix}\n{body}" if prefix else body)
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
                current_len = prefix_len
            buffer.append(row)
            current_len += row_text_len
        flush()
        return [piece for piece in pieces if piece.strip()]

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
        return ChunkRecord(
            chunk_id=chunk_id,
            doc_id=doc_id,
            text=text,
            page=page_start,
            page_end=page_end,
            chunk_index=index,
            source_file=file_name,
            metadata=metadata,
        )

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
        compact = re.sub(r"页码：\d+(?:-\d+)?", "", compact)
        compact = re.sub(r"\d{1,4}$", "", compact)
        return compact[:600]

    def _content_signature(self, text: str) -> str:
        return re.sub(r"\s+", "", text)


class _Counter:
    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        value = self._value
        self._value += 1
        return value
