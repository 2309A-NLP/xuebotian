from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.log_context import bind_doc_id, bind_request_id
from app.models.domain import ParsedDocument, TableBlock
from app.services.document.chunker import DocumentChunker
from app.services.document.cleaner import TextCleaner
from app.services.document.image_processor import PdfImageDescriber
from app.services.document.parser import PdfParser
from app.services.document.table_processor import merge_cross_page_tables, serialize_table
from app.services.storage.file_store import FileStore
from app.services.storage.metadata_store import MetadataStore
from app.services.vector.embedder import BgeM3Embedder
from app.services.vector.milvus_store import BaseVectorStore
from app.utils.id_generator import generate_doc_id
from app.utils.text import normalize_whitespace

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
        image_describer: PdfImageDescriber | None = None,
    ) -> None:
        self.settings = settings
        self.file_store = file_store
        self.metadata_store = metadata_store
        self.parser = parser
        self.cleaner = cleaner
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.image_describer = image_describer

    def ingest_pdf(self, upload: UploadFile) -> dict[str, Any]:
        record = self.create_upload(upload)
        return self.process_uploaded_pdf(record["doc_id"])

    def create_upload(self, upload: UploadFile) -> dict[str, Any]:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise AppError("Only PDF files are supported", status_code=400)

        doc_id = generate_doc_id(upload.filename)
        created_at = datetime.now()
        saved_path = self.file_store.save_upload(doc_id, upload)
        parsed_placeholder = self.settings.parsed_dir / f"{doc_id}.json"
        record = {
            "doc_id": doc_id,
            "file_name": upload.filename,
            "source_path": str(saved_path),
            "parsed_path": str(parsed_placeholder),
            "status": "uploaded",
            "page_count": 0,
            "chunk_count": 0,
            "created_at": created_at.isoformat(),
            "metadata": {
                "vision_enabled": self.settings.vision_enabled,
            },
        }
        self.metadata_store.upsert_document(record)
        logger.info("Document upload saved: %s", doc_id)
        return record

    def process_uploaded_pdf(self, doc_id: str, request_id: str | None = None) -> dict[str, Any]:
        document = self.get_document(doc_id)
        with bind_request_id(request_id or "-"), bind_doc_id(doc_id):
            return self._process_document_record(document)

    def process_uploaded_pdf_safely(self, doc_id: str, request_id: str | None = None) -> None:
        try:
            self.process_uploaded_pdf(doc_id, request_id)
        except Exception:
            logger.exception("Background document processing failed")

    def mark_processing(self, doc_id: str) -> None:
        self.metadata_store.update_document_status(doc_id, "processing")

    def _process_document_record(self, document: dict[str, Any]) -> dict[str, Any]:
        doc_id = document["doc_id"]
        file_name = document["file_name"]
        saved_path = Path(document["source_path"])
        created_at = datetime.fromisoformat(document["created_at"])
        try:
            logger.info("Document processing started")
            self.metadata_store.update_document_status(doc_id, "processing")
            pages = self.parser.parse(saved_path)
            table_bboxes_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
            for page in pages:
                for table in page.tables:
                    if table.bbox is not None:
                        table_bboxes_by_page.setdefault(page.page_number, []).append(table.bbox)
            image_descriptions = (
                self.image_describer.describe_pdf(saved_path, table_bboxes_by_page)
                if self.image_describer is not None
                else {}
            )

            # Clean body text per page and clean each table's cells in place.
            body_pages: list[tuple[int, str]] = []
            all_tables: list[TableBlock] = []
            cleaned_bodies = self.cleaner.clean_page_texts([page.text for page in pages])
            for page, cleaned_body in zip(pages, cleaned_bodies, strict=False):
                body_pages.append((page.page_number, cleaned_body))
                for table in page.tables:
                    table.caption = self.cleaner.clean_cell(table.caption)
                    table.reference_text = self.cleaner.clean_cell(table.reference_text)
                    table.header = [self.cleaner.clean_cell(cell) for cell in table.header]
                    table.rows = [
                        [self.cleaner.clean_cell(cell) for cell in row] for row in table.rows
                    ]
                    all_tables.append(table)

            # Merge tables that continue across page boundaries.
            merged_tables = merge_cross_page_tables(all_tables)

            # Build payload pages: body text plus serialized tables anchored to their start page.
            tables_by_page: dict[int, list[dict[str, Any]]] = {}
            for table in merged_tables:
                tables_by_page.setdefault(table.page_start, []).append(
                    {
                        "caption": table.caption,
                        "reference_text": table.reference_text,
                        "page_start": table.page_start,
                        "page_end": table.page_end,
                        "header": table.header,
                        "rows": table.rows,
                        "text": serialize_table(table),
                    }
                )

            page_texts: list[tuple[int, str]] = []
            payload_pages: list[dict[str, Any]] = []
            for page_number, body_text in body_pages:
                page_tables = tables_by_page.get(page_number, [])
                table_texts = [item["text"] for item in page_tables if item["text"]]
                merged_page_text = "\n".join([body_text, *table_texts]).strip()
                cleaned_page_text = normalize_whitespace(merged_page_text)
                page_texts.append((page_number, cleaned_page_text))
                payload_pages.append(
                    {
                        "page_number": page_number,
                        "text": cleaned_page_text,
                        "tables": page_tables,
                        "images": [
                            {
                                "image_index": item.image_index,
                                "kind": item.kind,
                                "width": item.width,
                                "height": item.height,
                                "caption": item.caption,
                                "debug_path": item.debug_path,
                                "description": item.description,
                            }
                            for item in image_descriptions.get(page_number, [])
                        ],
                    }
                )

            cleaned_text = self.cleaner.clean_pages([text for _, text in page_texts])
            table_count = len(merged_tables)
            image_count = sum(len(items) for items in image_descriptions.values())
            image_chunks = [
                item
                for page_number in sorted(image_descriptions)
                for item in image_descriptions[page_number]
            ]
            parsed_document = ParsedDocument(
                doc_id=doc_id,
                file_name=file_name,
                file_path=str(saved_path),
                pages=pages,
                cleaned_text=cleaned_text,
                created_at=created_at,
            )

            chunks = self.chunker.split(
                doc_id,
                file_name,
                body_pages,
                merged_tables,
                image_chunks,
            )
            table_chunk_count = sum(
                1 for chunk in chunks if chunk.metadata.get("type") == "table"
            )
            image_chunk_count = sum(
                1 for chunk in chunks if chunk.metadata.get("type") == "image"
            )
            self.metadata_store.update_document_status(
                doc_id,
                "indexing",
                page_count=len(parsed_document.pages),
                chunk_count=len(chunks),
                metadata={
                    "table_count": table_count,
                    "table_chunk_count": table_chunk_count,
                    "image_count": image_count,
                    "image_chunk_count": image_chunk_count,
                },
            )
            embeddings = self.embedder.embed_texts([chunk.text for chunk in chunks]) if chunks else []
            self.vector_store.upsert_chunks(chunks, embeddings)

            parsed_path = self.file_store.save_parsed_document(
                doc_id,
                {
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "source_path": str(saved_path),
                    "cleaned_text": cleaned_text,
                    "pages": payload_pages,
                    "chunks": [
                        {
                            "chunk_id": chunk.chunk_id,
                            "page": chunk.page,
                            "page_end": chunk.page_end,
                            "chunk_index": chunk.chunk_index,
                            "text": chunk.text,
                            "bm25_text": chunk.bm25_text,
                            "metadata": chunk.metadata,
                        }
                        for chunk in chunks
                    ],
                    "chunk_count": len(chunks),
                    "table_count": table_count,
                    "image_chunk_count": image_chunk_count,
                    "image_count": image_count,
                    "created_at": created_at.isoformat(),
                },
            )
            record = {
                "doc_id": doc_id,
                "file_name": file_name,
                "source_path": str(saved_path),
                "parsed_path": str(parsed_path),
                "status": "ready",
                "page_count": len(parsed_document.pages),
                "chunk_count": len(chunks),
                "created_at": created_at.isoformat(),
                "metadata": {
                    "cleaned_length": len(cleaned_text),
                    "table_count": table_count,
                    "table_chunk_count": table_chunk_count,
                    "image_count": image_count,
                    "image_chunk_count": image_chunk_count,
                    "vision_enabled": self.settings.vision_enabled,
                },
            }
            self.metadata_store.upsert_document(record)
            logger.info(
                "Document processing completed pages=%s chunks=%s tables=%s images=%s",
                len(parsed_document.pages),
                len(chunks),
                table_count,
                image_count,
            )
            return record
        except Exception as exc:
            logger.exception("Failed to process PDF file=%s", file_name, exc_info=exc)
            parsed_placeholder = self.settings.parsed_dir / f"{doc_id}.json"
            self._cleanup_failed_processing(doc_id, parsed_placeholder)
            self.metadata_store.update_document_status(
                doc_id,
                "failed",
                page_count=0,
                chunk_count=0,
                parse_error=str(exc),
                parsed_path=str(parsed_placeholder),
            )
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

    def _cleanup_failed_processing(self, doc_id: str, parsed_placeholder: Path) -> None:
        try:
            self.vector_store.delete_by_doc_id(doc_id)
        except Exception:
            logger.exception("Failed to cleanup vector records")
        self.file_store.delete_file(parsed_placeholder)
