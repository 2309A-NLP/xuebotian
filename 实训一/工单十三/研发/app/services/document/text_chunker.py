from __future__ import annotations

import re

from app.models.domain import ChunkRecord
from app.services.document.chunk_models import _Counter
from app.services.document.chunk_models import _TextBlock
from app.utils.text import normalize_whitespace

_MIN_TEXT_CHARS = 24
_MIN_MERGE_PARAGRAPH_CHARS = 50
_MAX_SHORT_MERGE_CHARS = 250
_HEADING_MAX_CHARS = 48
_TABLE_ROW_RE = re.compile(r"^第\d+行：")
_PAGE_RE = re.compile(r"^页码：\d+(?:-\d+)?$")
_IMAGE_INDEX_RE = re.compile(r"^图片\s+\d+$")
_IMAGE_TYPE_RE = re.compile(r"^类型：(?:image|chart|table)$", re.I)
_IMAGE_SIZE_RE = re.compile(r"^尺寸：\d+x\d+$", re.I)


class TextChunkMixin:
    """提供正文按语义结构和长度约束进行分块的逻辑。"""
    def _prepare_body_pages(
        self, body_pages: list[tuple[int, str]]
    ) -> list[tuple[int, str]]:
        """准备正文页面列表。"""
        prepared: list[tuple[int, str]] = []
        for page_number, text in body_pages:
            prepared.append((page_number, self._strip_structured_noise(text)))
        return prepared

    def _chunk_body_pages(
        self,
        doc_id: str,
        file_name: str,
        body_pages: list[tuple[int, str]],
        chunks: list[ChunkRecord],
        counter: _Counter,
        document_title: str = "",
    ) -> None:
        """切分正文页面列表。"""
        blocks = self._semantic_page_blocks(body_pages)
        if not blocks:
            return

        for heading, heading_blocks in self._heading_runs(blocks):
            chapter, section = self._split_heading_path(heading)
            pieces = [
                (piece, page_start, page_end)
                for piece, page_start, page_end in self._recursive_split_page_units(heading_blocks)
                if len(self._content_signature(piece)) >= _MIN_TEXT_CHARS
            ]
            total_pieces = len(pieces)
            for piece_index, (piece, page_start, page_end) in enumerate(pieces):
                chunks.append(
                    self._make_chunk(
                        doc_id=doc_id,
                        file_name=file_name,
                        text=piece,
                        page_start=page_start,
                        page_end=page_end,
                        kind="text",
                        counter=counter,
                        extra_metadata=self._text_chunk_metadata(
                            piece=piece,
                            heading=heading,
                            chapter=chapter,
                            section=section,
                            document_title=document_title,
                            heading_chunk_index=piece_index,
                            heading_chunk_total=total_pieces,
                            page_start=page_start,
                            page_end=page_end,
                        ),
                    )
                )

    def _chunk_body(
        self,
        doc_id: str,
        file_name: str,
        page_number: int,
        text: str,
        chunks: list[ChunkRecord],
        counter: _Counter,
        document_title: str = "",
    ) -> None:
        """切分正文。"""
        blocks = self._semantic_blocks(text, page_number=page_number)
        if not blocks:
            return

        grouped: dict[str, list[_TextBlock]] = {}
        order: list[str] = []
        for block in blocks:
            key = block.heading
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(block)

        for heading in order:
            chapter, section = self._split_heading_path(heading)
            pieces = [
                piece
                for piece in self._recursive_split_units([block.text for block in grouped[heading]])
                if len(self._content_signature(piece)) >= _MIN_TEXT_CHARS
            ]
            total_pieces = len(pieces)
            for piece_index, piece in enumerate(pieces):
                chunks.append(
                    self._make_chunk(
                        doc_id=doc_id,
                        file_name=file_name,
                        text=piece,
                        page_start=page_number,
                        page_end=page_number,
                        kind="text",
                        counter=counter,
                        extra_metadata=self._text_chunk_metadata(
                            piece=piece,
                            heading=heading,
                            chapter=chapter,
                            section=section,
                            document_title=document_title,
                            heading_chunk_index=piece_index,
                            heading_chunk_total=total_pieces,
                            page_start=page_number,
                            page_end=page_number,
                        ),
                    )
                )

    def _document_title(self, body_pages: list[tuple[int, str]]) -> str:
        """处理文档标题。"""
        for _, text in body_pages[:3]:
            for raw_line in text.splitlines():
                line = normalize_whitespace(raw_line)
                if not line:
                    continue
                if self._is_list_item(line):
                    continue
                if len(line) <= 80:
                    return line
        return ""

    def _strip_structured_noise(self, text: str) -> str:
        """去除structured结构化噪声。"""
        cleaned = re.sub(r"```mermaid.*?```", "", text or "", flags=re.I | re.S)
        lines: list[str] = []
        in_fence = False
        for raw_line in cleaned.splitlines():
            line = normalize_whitespace(raw_line)
            if not line:
                lines.append("")
                continue
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or self._is_structured_noise_line(line):
                continue
            lines.append(line)
        return normalize_whitespace("\n".join(lines))

    def _is_structured_noise_line(self, line: str) -> bool:
        """判断structured结构化噪声文本行是否成立。"""
        if line.lower() == "text":
            return True
        if any(
            line.startswith(prefix)
            for prefix in ("表格：", "参考：", "表头：", "前导描述：", "描述：")
        ):
            return True
        if _TABLE_ROW_RE.match(line):
            return True
        if _PAGE_RE.match(line):
            return True
        if _IMAGE_INDEX_RE.match(line):
            return True
        if _IMAGE_TYPE_RE.match(line):
            return True
        if _IMAGE_SIZE_RE.match(line):
            return True
        if line.startswith("标题：```mermaid") or "```mermaid" in line:
            return True
        return False

    def _semantic_blocks(self, text: str, page_number: int = 0) -> list[_TextBlock]:
        """处理语义块块列表。"""
        blocks: list[_TextBlock] = []
        chapter_heading = ""
        section_heading = ""
        buffer: list[str] = []

        def current_heading() -> str:
            """返回当前缓冲块应继承的标题路径。"""
            return " / ".join(
                part for part in [chapter_heading, section_heading] if part
            )

        def flush() -> None:
            """将当前缓冲内容整理后写入结果集。"""
            if not buffer:
                return
            block_text = normalize_whitespace("\n".join(buffer))
            if block_text:
                blocks.append(
                    _TextBlock(
                        text=block_text,
                        heading=current_heading(),
                        page_start=page_number,
                        page_end=page_number,
                    )
                )
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
                blocks.append(
                    _TextBlock(
                        text=line,
                        heading=current_heading(),
                        page_start=page_number,
                        page_end=page_number,
                    )
                )
                continue

            buffer.append(line)

        flush()
        return blocks

    def _semantic_page_blocks(self, body_pages: list[tuple[int, str]]) -> list[_TextBlock]:
        """处理语义块页面块列表。"""
        blocks: list[_TextBlock] = []
        chapter_heading = ""
        section_heading = ""
        buffer: list[str] = []
        buffer_page_start = 0
        buffer_page_end = 0

        def current_heading() -> str:
            """返回当前缓冲块应继承的标题路径。"""
            return " / ".join(
                part for part in [chapter_heading, section_heading] if part
            )

        def append_buffer(line: str, page_number: int) -> None:
            """向当前缓冲区追加文本并维护页码信息。"""
            nonlocal buffer_page_start, buffer_page_end
            if not buffer:
                buffer_page_start = page_number
            buffer_page_end = page_number
            buffer.append(line)

        def flush() -> None:
            """将当前缓冲内容整理后写入结果集。"""
            nonlocal buffer_page_start, buffer_page_end
            if not buffer:
                return
            block_text = normalize_whitespace("\n".join(buffer))
            if block_text:
                blocks.append(
                    _TextBlock(
                        text=block_text,
                        heading=current_heading(),
                        page_start=buffer_page_start,
                        page_end=buffer_page_end,
                    )
                )
            buffer.clear()
            buffer_page_start = 0
            buffer_page_end = 0

        for page_number, text in body_pages:
            if not text or not text.strip():
                flush()
                continue
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
                    blocks.append(
                        _TextBlock(
                            text=line,
                            heading=current_heading(),
                            page_start=page_number,
                            page_end=page_number,
                        )
                    )
                    continue

                append_buffer(line, page_number)

        flush()
        return blocks

    def _recursive_page_chunks(
        self,
        blocks: list[_TextBlock],
    ) -> list[tuple[str, str, str, str, int, int]]:
        """处理recursive页面切片集合。"""
        chunks: list[tuple[str, str, str, str, int, int]] = []
        for heading, heading_blocks in self._heading_runs(blocks):
            chapter, section = self._split_heading_path(heading)
            for piece, page_start, page_end in self._recursive_split_page_units(heading_blocks):
                if piece:
                    chunks.append((piece, heading, chapter, section, page_start, page_end))
        return chunks

    def _heading_runs(self, blocks: list[_TextBlock]) -> list[tuple[str, list[_TextBlock]]]:
        """处理标题runs。"""
        runs: list[tuple[str, list[_TextBlock]]] = []
        current_heading: str | None = None
        current_blocks: list[_TextBlock] = []

        def flush() -> None:
            """将当前缓冲内容整理后写入结果集。"""
            nonlocal current_blocks
            if current_heading is not None and current_blocks:
                runs.append((current_heading, current_blocks))
            current_blocks = []

        for block in blocks:
            if current_heading is None:
                current_heading = block.heading
            elif block.heading != current_heading:
                flush()
                current_heading = block.heading
            current_blocks.append(block)

        flush()
        return runs

    def _recursive_split_page_units(
        self,
        units: list[_TextBlock],
    ) -> list[tuple[str, int, int]]:
        """处理recursivesplit页面units。"""
        units = self._merge_short_page_units(units)
        packed: list[tuple[str, int, int]] = []
        current: list[_TextBlock] = []
        current_len = 0

        def flush() -> None:
            """将当前缓冲内容整理后写入结果集。"""
            nonlocal current, current_len
            if current:
                packed.append(self._pack_text_blocks(current))
            current = []
            current_len = 0

        for unit in units:
            text = normalize_whitespace(unit.text)
            if not text:
                continue
            normalized_unit = _TextBlock(
                text=text,
                heading=unit.heading,
                page_start=unit.page_start,
                page_end=unit.page_end,
            )
            if len(text) > self.chunk_size:
                flush()
                packed.extend(
                    (piece, normalized_unit.page_start, normalized_unit.page_end)
                    for piece in self._recursive_split_text(text)
                )
                continue
            if current and current_len + len(text) + 1 > self.chunk_size:
                flush()
                overlap = self._overlap_context(packed[-1][0] if packed else "")
                if overlap:
                    overlap_page_start = packed[-1][1] if packed else normalized_unit.page_start
                    overlap_page_end = packed[-1][2] if packed else normalized_unit.page_start
                    current.append(
                        _TextBlock(
                            text=overlap,
                            heading=normalized_unit.heading,
                            page_start=overlap_page_start,
                            page_end=overlap_page_end,
                        )
                    )
                    current_len = len(overlap)
            current.append(normalized_unit)
            current_len += len(text) + 1
        flush()
        return [item for item in packed if item[0].strip()]

    def _pack_text_blocks(self, blocks: list[_TextBlock]) -> tuple[str, int, int]:
        """打包文本块列表。"""
        text = normalize_whitespace("\n\n".join(block.text for block in blocks if block.text.strip()))
        pages = [
            page
            for block in blocks
            for page in (block.page_start, block.page_end)
            if page > 0
        ]
        page_start = min(pages) if pages else 0
        page_end = max(pages) if pages else page_start
        return text, page_start, page_end

    def _recursive_chunks(self, blocks: list[_TextBlock]) -> list[tuple[str, str, str, str]]:
        """处理recursive切片集合。"""
        chunks: list[tuple[str, str, str, str]] = []
        grouped: dict[str, list[_TextBlock]] = {}
        order: list[str] = []
        for block in blocks:
            key = block.heading
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(block)

        for heading in order:
            chapter, section = self._split_heading_path(heading)
            texts = [block.text for block in grouped[heading]]
            for piece in self._recursive_split_units(texts):
                if piece:
                    chunks.append((piece, heading, chapter, section))
        return chunks

    def _recursive_split_units(
        self,
        units: list[str],
        *,
        merge_short_units: bool = True,
    ) -> list[str]:
        """处理recursivesplitunits。"""
        if merge_short_units:
            units = self._merge_short_units(units)
        packed: list[str] = []
        current: list[str] = []
        current_len = 0

        def flush() -> None:
            """将当前缓冲内容整理后写入结果集。"""
            nonlocal current, current_len
            if current:
                packed.append(normalize_whitespace("\n\n".join(current)))
            current = []
            current_len = 0

        for unit in units:
            text = normalize_whitespace(unit)
            if not text:
                continue
            if len(text) > self.chunk_size:
                flush()
                packed.extend(self._recursive_split_text(text))
                continue
            if current and current_len + len(text) + 1 > self.chunk_size:
                flush()
                overlap = self._overlap_context(packed[-1] if packed else "")
                if overlap:
                    current.append(overlap)
                    current_len = len(overlap)
            current.append(text)
            current_len += len(text) + 1
        flush()
        return [item for item in packed if item.strip()]

    def _recursive_split_text(self, text: str) -> list[str]:
        """处理recursivesplit文本。"""
        paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
        if len(paragraphs) > 1:
            merged_paragraphs = self._merge_short_units(paragraphs)
            if len(merged_paragraphs) > 1:
                return self._recursive_split_units(
                    merged_paragraphs,
                    merge_short_units=False,
                )
            paragraph_chunks: list[str] = []
            for paragraph in merged_paragraphs:
                compact = normalize_whitespace(paragraph)
                if not compact:
                    continue
                if len(compact) <= self.chunk_size:
                    paragraph_chunks.append(compact)
                    continue
                paragraph_chunks.extend(self._hard_split("", compact))
            if paragraph_chunks:
                return paragraph_chunks
        compact = normalize_whitespace(text)
        if not compact:
            return []
        return self._hard_split("", compact)

    def _merge_short_page_units(self, units: list[_TextBlock]) -> list[_TextBlock]:
        """合并short页面units。"""
        merged: list[_TextBlock] = []
        pending: list[_TextBlock] = []
        pending_len = 0

        def flush_pending() -> None:
            """处理flushpending。"""
            nonlocal pending, pending_len
            if not pending:
                return
            merged.append(self._combine_page_blocks(pending))
            pending = []
            pending_len = 0

        for unit in units:
            text = normalize_whitespace(unit.text)
            if not text:
                continue
            normalized = _TextBlock(
                text=text,
                heading=unit.heading,
                page_start=unit.page_start,
                page_end=unit.page_end,
            )
            if self._is_short_unit_text(text):
                text_len = len(self._content_signature(text))
                if pending and pending_len + text_len > _MAX_SHORT_MERGE_CHARS:
                    flush_pending()
                pending.append(normalized)
                pending_len += text_len
                continue
            if pending:
                flush_pending()
            merged.append(normalized)

        if pending:
            flush_pending()
        return merged

    def _merge_short_units(self, units: list[str]) -> list[str]:
        """合并shortunits。"""
        merged: list[str] = []
        pending: list[str] = []
        pending_len = 0

        def flush_pending() -> None:
            """处理flushpending。"""
            nonlocal pending, pending_len
            if not pending:
                return
            merged.append(normalize_whitespace("\n\n".join(pending)))
            pending = []
            pending_len = 0

        for unit in units:
            text = normalize_whitespace(unit)
            if not text:
                continue
            if self._is_short_unit_text(text):
                text_len = len(self._content_signature(text))
                if pending and pending_len + text_len > _MAX_SHORT_MERGE_CHARS:
                    flush_pending()
                pending.append(text)
                pending_len += text_len
                continue
            if pending:
                flush_pending()
            merged.append(text)

        if pending:
            flush_pending()
        return merged

    def _combine_page_blocks(self, blocks: list[_TextBlock]) -> _TextBlock:
        """合并整理页面块列表。"""
        text = normalize_whitespace("\n\n".join(block.text for block in blocks if block.text.strip()))
        page_start = min((block.page_start for block in blocks if block.page_start > 0), default=0)
        page_end = max((block.page_end for block in blocks if block.page_end > 0), default=page_start)
        heading = next((block.heading for block in blocks if block.heading), "")
        return _TextBlock(
            text=text,
            heading=heading,
            page_start=page_start,
            page_end=page_end,
        )

    def _is_short_unit_text(self, text: str) -> bool:
        """判断short单位说明文本是否成立。"""
        return len(self._content_signature(text)) < _MIN_MERGE_PARAGRAPH_CHARS

    def _split_sentence_units(self, sentences: list[str]) -> list[str]:
        """拆分句子列表units。"""
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for sentence in sentences:
            if len(sentence) > self.chunk_size:
                if current:
                    chunks.append(normalize_whitespace("".join(current)))
                    current = self._sentence_overlap(current)
                    current_len = sum(len(item) for item in current)
                chunks.extend(self._hard_split("", sentence))
                continue

            if current and current_len + len(sentence) > self.chunk_size:
                chunks.append(normalize_whitespace("".join(current)))
                current = self._sentence_overlap(current)
                current_len = sum(len(item) for item in current)

            current.append(sentence)
            current_len += len(sentence)

        if current:
            chunks.append(normalize_whitespace("".join(current)))
        return [item for item in chunks if item.strip()]

    def _split_heading_path(self, heading: str) -> tuple[str, str]:
        """拆分标题路径。"""
        parts = [part.strip() for part in heading.split(" / ") if part.strip()]
        chapter = parts[0] if parts else ""
        section = parts[-1] if len(parts) > 1 else ""
        return chapter, section

    def _text_chunk_metadata(
        self,
        *,
        piece: str,
        heading: str,
        chapter: str,
        section: str,
        document_title: str,
        heading_chunk_index: int,
        heading_chunk_total: int,
        page_start: int,
        page_end: int,
    ) -> dict[str, object]:
        """处理文本切片元数据。"""
        paragraphs = self._chunk_paragraphs(piece)
        short_paragraph_count = sum(
            1
            for paragraph in paragraphs
            if len(self._content_signature(paragraph)) < _MIN_MERGE_PARAGRAPH_CHARS
        )
        list_item_count = sum(1 for paragraph in paragraphs if self._chunk_paragraph_is_list(paragraph))
        metadata: dict[str, object] = {
            "heading_level": self._heading_level(chapter, section),
            "structure_scope": self._structure_scope(chapter, section),
            "heading_chunk_index": heading_chunk_index,
            "heading_chunk_total": heading_chunk_total,
            "is_heading_lead": heading_chunk_index == 0,
            "paragraph_count": len(paragraphs),
            "short_paragraph_count": short_paragraph_count,
            "merged_short_paragraphs": short_paragraph_count > 0 and len(paragraphs) > 1,
            "is_list_chunk": list_item_count > 0,
            "list_item_count": list_item_count,
            "chunk_char_length": len(self._content_signature(piece)),
            "chunk_text_length": len(piece),
            "cross_page": page_end > page_start,
        }
        for key, value in {
            "heading": heading,
            "chapter": chapter,
            "section": section,
            "document_title": document_title,
        }.items():
            if value:
                metadata[key] = value
        return metadata

    def _chunk_paragraphs(self, piece: str) -> list[str]:
        """切分paragraphs。"""
        return [item.strip() for item in re.split(r"\n{2,}", piece) if item.strip()]

    def _chunk_paragraph_is_list(self, paragraph: str) -> bool:
        """切分段落is列表。"""
        first_line = next((line.strip() for line in paragraph.splitlines() if line.strip()), "")
        return self._is_list_item(first_line) if first_line else False

    def _heading_level(self, chapter: str, section: str) -> int:
        """处理标题标题层级。"""
        if section:
            return 2
        if chapter:
            return 1
        return 0

    def _structure_scope(self, chapter: str, section: str) -> str:
        """处理结构范围范围限定。"""
        if section:
            return "section"
        if chapter:
            return "chapter"
        return "document"

    def _sentence_overlap(self, sentences: list[str]) -> list[str]:
        """处理句子列表重叠片段。"""
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
        """处理重叠片段上下文。"""
        if self.chunk_overlap <= 0 or not text:
            return ""
        compact = normalize_whitespace(text)
        if len(compact) <= self.chunk_overlap:
            return compact
        return compact[-self.chunk_overlap :]

    def _hard_split(self, prefix: str, sentence: str) -> list[str]:
        """处理hardsplit。"""
        max_body_len = max(self.chunk_size - len(prefix), 1)
        pieces: list[str] = []
        start = 0
        while start < len(sentence):
            hard_end = min(start + max_body_len, len(sentence))
            end = self._best_split_end(sentence, start, hard_end)
            if end <= start:
                end = hard_end
            pieces.append(normalize_whitespace(prefix + sentence[start:end]))
            if end >= len(sentence):
                break
            next_start = max(end - self.chunk_overlap, start + 1)
            start = self._trim_split_start(sentence, next_start, end)
        return pieces

    def _best_split_end(self, text: str, start: int, hard_end: int) -> int:
        """处理最佳片段splitend。"""
        if hard_end >= len(text):
            return hard_end
        window = text[start:hard_end]
        min_keep = max(int(len(window) * 0.65), 1)
        for separators in (
            ("。", "！", "？", ".", "!", "?"),
            ("；", ";", "：", ":"),
            ("，", ",", " "),
        ):
            best = max(window.rfind(separator) for separator in separators)
            if best >= min_keep:
                return start + best + 1
        return hard_end

    def _trim_split_start(self, text: str, start: int, previous_end: int) -> int:
        """处理trimsplitstart。"""
        if start >= len(text):
            return start
        if start < previous_end:
            window = text[start:previous_end]
            next_separator = min(
                [
                    index
                    for index in (
                        window.find(" "),
                        window.find("，"),
                        window.find(","),
                        window.find("。"),
                        window.find("."),
                    )
                    if index >= 0
                ],
                default=-1,
            )
            if 0 <= next_separator <= max(self.chunk_overlap // 2, 1):
                start += next_separator + 1
            else:
                previous_window = text[max(previous_end - self.chunk_overlap * 2, 0):start]
                previous_separator = max(
                    previous_window.rfind(" "),
                    previous_window.rfind("，"),
                    previous_window.rfind(","),
                    previous_window.rfind("。"),
                    previous_window.rfind("."),
                )
                if previous_separator >= 0:
                    start = max(previous_end - self.chunk_overlap * 2, 0) + previous_separator + 1
        while start < len(text) and text[start].isspace():
            start += 1
        return start

    def _is_heading(self, line: str) -> bool:
        """判断标题是否成立。"""
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
        """判断章节标题标题是否成立。"""
        return bool(re.match(r"^第[一二三四五六七八九十0-9]+[章节部分篇]", line.strip()))

    def _is_list_item(self, line: str) -> bool:
        """判断列表条目是否成立。"""
        compact = line.strip()
        return bool(
            re.match(r"^\d+(\.\d+)*[、.．)]", compact)
            or re.match(r"^[（(][0-9一二三四五六七八九十]+[）)]", compact)
            or compact.startswith(("注：", "说明：", "其中："))
        )
