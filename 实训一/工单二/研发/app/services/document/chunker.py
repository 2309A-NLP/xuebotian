from __future__ import annotations

from app.models.domain import ChunkRecord
from app.utils.id_generator import generate_chunk_id


class DocumentChunker:
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, doc_id: str, file_name: str, pages: list[tuple[int, str]]) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        chunk_index = 0
        for page_number, text in pages:
            if not text.strip():
                continue
            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                chunk_text = text[start:end].strip()
                if chunk_text:
                    chunk_id = generate_chunk_id(doc_id, chunk_index, chunk_text)
                    chunks.append(
                        ChunkRecord(
                            chunk_id=chunk_id,
                            doc_id=doc_id,
                            text=chunk_text,
                            page=page_number,
                            chunk_index=chunk_index,
                            source_file=file_name,
                            metadata={"page": page_number, "chunk_index": chunk_index},
                        )
                    )
                    chunk_index += 1
                if end >= len(text):
                    break
                start = max(end - self.chunk_overlap, start + 1)
        return chunks
