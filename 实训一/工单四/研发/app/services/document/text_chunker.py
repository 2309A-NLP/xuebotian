from __future__ import annotations

import re

from app.models.domain import ChunkRecord
from app.services.document.chunk_models import _Counter
from app.services.document.chunk_models import _TextBlock
from app.utils.text import normalize_whitespace, split_sentences

_MIN_TEXT_CHARS = 24
_HEADING_MAX_CHARS = 48


class TextChunkMixin:
    def _chunk_body_pages(
        self,
        doc_id: str,
        file_name: str,
        body_pages: list[tuple[int, str]],
        chunks: list[ChunkRecord],
        counter: _Counter,
        document_title: str = "",
    ) -> None:
        blocks = self._semantic_page_blocks(body_pages)
        if not blocks:
            return

        for piece, heading, chapter, section, page_start, page_end in self._recursive_page_chunks(blocks):
            if len(self._content_signature(piece)) < _MIN_TEXT_CHARS:
                continue
            chunks.append(
                self._make_chunk(
                    doc_id=doc_id,
                    file_name=file_name,
                    text=piece,
                    page_start=page_start,
                    page_end=page_end,
                    kind="text",
                    counter=counter,
                    extra_metadata={
                        key: value
                        for key, value in {
                            "heading": heading,
                            "chapter": chapter,
                            "section": section,
                            "document_title": document_title,
                        }.items()
                        if value
                    },
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
        blocks = self._semantic_blocks(text, page_number=page_number)
        if not blocks:
            return

        for piece, heading, chapter, section in self._recursive_chunks(blocks):
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
                    extra_metadata={
                        key: value
                        for key, value in {
                            "heading": heading,
                            "chapter": chapter,
                            "section": section,
                            "document_title": document_title,
                        }.items()
                        if value
                    },
                )
            )

    def _document_title(self, body_pages: list[tuple[int, str]]) -> str:
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

    def _semantic_blocks(self, text: str, page_number: int = 0) -> list[_TextBlock]:
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
        blocks: list[_TextBlock] = []
        chapter_heading = ""
        section_heading = ""
        buffer: list[str] = []
        buffer_page_start = 0
        buffer_page_end = 0

        def current_heading() -> str:
            return " / ".join(
                part for part in [chapter_heading, section_heading] if part
            )

        def append_buffer(line: str, page_number: int) -> None:
            nonlocal buffer_page_start, buffer_page_end
            if not buffer:
                buffer_page_start = page_number
            buffer_page_end = page_number
            buffer.append(line)

        def flush() -> None:
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
        chunks: list[tuple[str, str, str, str, int, int]] = []
        for heading, heading_blocks in self._heading_runs(blocks):
            chapter, section = self._split_heading_path(heading)
            for piece, page_start, page_end in self._recursive_split_page_units(heading_blocks):
                if piece:
                    chunks.append((piece, heading, chapter, section, page_start, page_end))
        return chunks

    def _heading_runs(self, blocks: list[_TextBlock]) -> list[tuple[str, list[_TextBlock]]]:
        runs: list[tuple[str, list[_TextBlock]]] = []
        current_heading: str | None = None
        current_blocks: list[_TextBlock] = []

        def flush() -> None:
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
        packed: list[tuple[str, int, int]] = []
        current: list[_TextBlock] = []
        current_len = 0

        def flush() -> None:
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
        text = normalize_whitespace("\n".join(block.text for block in blocks if block.text.strip()))
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

    def _recursive_split_units(self, units: list[str]) -> list[str]:
        packed: list[str] = []
        current: list[str] = []
        current_len = 0

        def flush() -> None:
            nonlocal current, current_len
            if current:
                packed.append(normalize_whitespace("\n".join(current)))
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
        paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
        if len(paragraphs) > 1:
            return self._recursive_split_units(paragraphs)

        sentences = split_sentences(text)
        if len(sentences) > 1:
            return self._split_sentence_units(sentences)

        return self._hard_split("", text)

    def _split_sentence_units(self, sentences: list[str]) -> list[str]:
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
        parts = [part.strip() for part in heading.split(" / ") if part.strip()]
        chapter = parts[0] if parts else ""
        section = parts[-1] if len(parts) > 1 else ""
        return chapter, section

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
        if hard_end >= len(text):
            return hard_end
        window = text[start:hard_end]
        min_keep = max(int(len(window) * 0.65), 1)
        candidates = [
            window.rfind(separator)
            for separator in ("。", "；", "，", ".", ";", ",", " ")
        ]
        best = max(candidates)
        if best >= min_keep:
            return start + best + 1
        return hard_end

    def _trim_split_start(self, text: str, start: int, previous_end: int) -> int:
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
