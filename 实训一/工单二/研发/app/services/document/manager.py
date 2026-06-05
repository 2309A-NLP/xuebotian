from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.domain import ParsedDocument
from app.services.document.chunker import DocumentChunker
from app.services.document.cleaner import TextCleaner
from app.services.document.parser import PdfParser
from app.services.storage.file_store import FileStore
from app.services.storage.metadata_store import MetadataStore
from app.services.vector.embedder import BgeM3Embedder
from app.services.vector.milvus_store import BaseVectorStore
from app.utils.id_generator import generate_doc_id

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        file_store: FileStore,
        metadata_store: MetadataStore,
        parser: PdfParser,
        cleaner: TextCleaner,
        chunker: DocumentChunker,
        embedder: BgeM3Embedder,
        vector_store: BaseVectorStore,
    ) -> None:
        self.settings = settings
        self.file_store = file_store
        self.metadata_store = metadata_store
        self.parser = parser
        self.cleaner = cleaner
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store

    def ingest_pdf(self, upload: UploadFile) -> dict[str, Any]:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise AppError("Only PDF files are supported", status_code=400)

        doc_id = generate_doc_id(upload.filename)
        created_at = datetime.now()
        saved_path = self.file_store.save_upload(doc_id, upload)

        try:
            pages = self.parser.parse(saved_path)
            page_texts: list[tuple[int, str]] = []
            payload_pages: list[dict[str, Any]] = []
            for page in pages:
                merged_page_text = "\n".join([page.text, *page.tables]).strip()
                cleaned_page_text = self.cleaner.clean_text(merged_page_text)
                page_texts.append((page.page_number, cleaned_page_text))
                payload_pages.append(
                    {
                        "page_number": page.page_number,
                        "text": cleaned_page_text,
                        "tables": page.tables,
                    }
                )

            cleaned_text = self.cleaner.clean_pages([text for _, text in page_texts])
            parsed_document = ParsedDocument(
                doc_id=doc_id,
                file_name=upload.filename,
                file_path=str(saved_path),
                pages=pages,
                cleaned_text=cleaned_text,
                created_at=created_at,
            )

            chunks = self.chunker.split(doc_id, upload.filename, page_texts)
            embeddings = self.embedder.embed_texts([chunk.text for chunk in chunks]) if chunks else []
            self.vector_store.upsert_chunks(chunks, embeddings)

            parsed_path = self.file_store.save_parsed_document(
                doc_id,
                {
                    "doc_id": doc_id,
                    "file_name": upload.filename,
                    "source_path": str(saved_path),
                    "cleaned_text": cleaned_text,
                    "pages": payload_pages,
                    "chunk_count": len(chunks),
                    "created_at": created_at.isoformat(),
                },
            )
            record = {
                "doc_id": doc_id,
                "file_name": upload.filename,
                "source_path": str(saved_path),
                "parsed_path": str(parsed_path),
                "status": "ready",
                "page_count": len(parsed_document.pages),
                "chunk_count": len(chunks),
                "created_at": created_at.isoformat(),
                "metadata": {"cleaned_length": len(cleaned_text)},
            }
            self.metadata_store.upsert_document(record)
            logger.info("Document ingested: %s", doc_id)
            return record
        except Exception as exc:
            logger.exception("Failed to ingest PDF file=%s", upload.filename, exc_info=exc)
            parsed_placeholder = self.settings.parsed_dir / f"{doc_id}.json"
            record = {
                "doc_id": doc_id,
                "file_name": upload.filename,
                "source_path": str(saved_path),
                "parsed_path": str(parsed_placeholder),
                "status": "failed",
                "page_count": 0,
                "chunk_count": 0,
                "parse_error": str(exc),
                "created_at": created_at.isoformat(),
                "metadata": {},
            }
            self.metadata_store.upsert_document(record)
            raise

    def list_documents(self) -> list[dict[str, Any]]:
        return self.metadata_store.list_documents()

    def get_document(self, doc_id: str) -> dict[str, Any]:
        document = self.metadata_store.get_document(doc_id)
        if not document:
            raise AppError("Document not found", status_code=404, details={"doc_id": doc_id})
        return document

    def delete_document(self, doc_id: str) -> None:
        document = self.get_document(doc_id)
        self.vector_store.delete_by_doc_id(doc_id)
        self.metadata_store.delete_document(doc_id)
        self.file_store.delete_file(document["source_path"])
        self.file_store.delete_file(document["parsed_path"])
