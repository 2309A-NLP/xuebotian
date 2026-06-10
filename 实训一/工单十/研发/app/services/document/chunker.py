from __future__ import annotations

from app.models.domain import ChunkRecord, TableBlock
from app.services.document.chunk_models import _Counter
from app.services.document.chunk_records import ChunkRecordMixin
from app.services.document.image_chunker import ImageChunkMixin
from app.services.document.image_models import ImageDescription
from app.services.document.table_chunker import TableChunkMixin
from app.services.document.text_chunker import TextChunkMixin


class DocumentChunker(TextChunkMixin, TableChunkMixin, ImageChunkMixin, ChunkRecordMixin):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(
        self,
        doc_id: str,
        file_name: str,
        body_pages: list[tuple[int, str]],
        tables: list[TableBlock] | None = None,
        images: list[ImageDescription] | None = None,
    ) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        counter = _Counter()
        prepared_body_pages = self._prepare_body_pages(body_pages)
        document_title = self._document_title(prepared_body_pages)
        self._chunk_body_pages(
            doc_id,
            file_name,
            prepared_body_pages,
            chunks,
            counter,
            document_title,
        )
        for table_index, table in enumerate(tables or [], start=1):
            self._chunk_table(
                doc_id,
                file_name,
                table,
                table_index,
                chunks,
                counter,
                document_title,
            )
        for image_index, image in enumerate(images or [], start=1):
            self._chunk_image(
                doc_id,
                file_name,
                image,
                image_index,
                chunks,
                counter,
                document_title,
            )
        return self._dedupe_chunks(chunks)
