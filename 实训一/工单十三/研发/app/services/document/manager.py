from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.log_context import bind_doc_id, bind_request_id
from app.models.domain import ParsedDocument, ParsedPage, TableBlock
from app.services.document.chunker import DocumentChunker
from app.services.document.cleaner import TextCleaner
from app.services.document.image_processor import PdfImageDescriber
from app.services.document.table_processor import merge_cross_page_tables, serialize_table
from app.services.storage.file_store import FileStore
from app.services.storage.metadata_store import MetadataStore
from app.services.vector.embedder import BgeM3Embedder
from app.services.vector.milvus_store import BaseVectorStore
from app.utils.id_generator import generate_doc_id
from app.utils.text import normalize_whitespace

logger = logging.getLogger(__name__)
_TABLE_CONTEXT_SPLITTERS = {"。", "；", "：", ";", ":"}


class DocumentParser(Protocol):
    """约束文档解析器的统一输出格式。

    只要某个解析器能把原始 PDF 转成 ``ParsedPage`` 列表，
    ``DocumentService`` 就可以继续复用后面的清洗、切分和入库流程。
    """
    def parse(self, file_path: Path) -> list[ParsedPage]:
        """将已落盘的 PDF 文件解析为按页组织的结构化结果。

        返回值中的每一页通常会带正文、表格和解析阶段收集到的辅助元数据，
        供后续清洗、表格合并、图片描述和切片阶段继续消费。
        """
        ...


class DocumentService:
    """负责文档处理全链路编排的总服务。

    这个类不直接实现 PDF 解析、文本清洗或向量检索，而是把这些能力串起来，
    对外提供“上传文档并最终变成可检索索引”的统一入口。
    """
    def __init__(
        self,
        settings: Settings,
        file_store: FileStore,
        metadata_store: MetadataStore,
        parser: DocumentParser,
        cleaner: TextCleaner,
        chunker: DocumentChunker,
        embedder: BgeM3Embedder,
        vector_store: BaseVectorStore,
        image_describer: PdfImageDescriber | None = None,
    ) -> None:
        """注入文档处理链路中的各个基础组件。

        这些依赖分别负责文件持久化、元数据记录、PDF 解析、文本清洗、
        分块、向量编码和向量存储，组合后才能完成完整入库流程。
        """
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
        """同步处理一个上传的 PDF。

        这是最直接的入口：先保存上传文件并登记元数据，
        再立即执行解析、切片、向量化和入库，最后返回最终文档记录。
        """
        record = self.create_upload(upload)
        return self.process_uploaded_pdf(record["doc_id"])

    def create_upload(self, upload: UploadFile) -> dict[str, Any]:
        """保存原始 PDF，并创建一条初始元数据记录。

        这个阶段只做输入校验和文件落盘，不会真正解析 PDF。
        生成的记录状态为 ``uploaded``，供后续异步或同步处理继续推进。
        """
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
        """根据文档 ID 执行一次完整的处理流程。

        这里会先加载文档元数据，再绑定请求上下文日志，
        最终把工作委托给内部的主处理函数。
        """
        document = self.get_document(doc_id)
        with bind_request_id(request_id or "-"), bind_doc_id(doc_id):
            return self._process_document_record(document)

    def process_uploaded_pdf_safely(self, doc_id: str, request_id: str | None = None) -> None:
        """以“吞掉异常并记录日志”的方式处理文档。

        这个包装方法更适合后台任务场景，避免单个文档失败导致整个任务线程退出。
        """
        try:
            self.process_uploaded_pdf(doc_id, request_id)
        except Exception:
            logger.exception("Background document processing failed")

    def mark_processing(self, doc_id: str) -> None:
        """将文档状态显式标记为 ``processing``。"""
        self.metadata_store.update_document_status(doc_id, "processing")

    def _table_context_before_period(self, text: str) -> str:
        """截取表格后文中靠前的说明片段。

        这个函数会把文本裁剪到第一个句读符之前，适合提取“表格后紧跟的一句总结”
        之类的短上下文，避免把过长正文一起塞进表格元数据。
        """
        cleaned = normalize_whitespace(text).strip()
        if not cleaned:
            return ""
        end_positions = [index for index, char in enumerate(cleaned) if char in _TABLE_CONTEXT_SPLITTERS]
        if end_positions:
            return cleaned[: min(end_positions) + 1].strip()
        return cleaned

    def _table_context_after_period(self, text: str) -> str:
        """截取表格前文中最靠近表格的尾部说明。

        如果前文有多个句读符，这里优先保留最后一个句读符之后的尾句，
        让表格引用文本更聚焦于紧邻表格的上下文线索。
        """
        cleaned = normalize_whitespace(text).strip()
        if not cleaned:
            return ""
        end_positions = [index for index, char in enumerate(cleaned) if char in _TABLE_CONTEXT_SPLITTERS]
        if not end_positions:
            return cleaned

        tail = cleaned[end_positions[-1] + 1 :].strip()
        if not tail:
            return cleaned
        return tail

    def _process_document_record(self, document: dict[str, Any]) -> dict[str, Any]:
        """完成单个文档从原始 PDF 到可检索索引的全部处理。

        主要步骤包括：解析页面、提取图片描述、清洗正文和表格、合并跨页表格、
        生成切片、编码向量、写入向量库，并同步更新元数据和解析产物文件。
        如果中途失败，还会负责清理半成品数据并标记失败状态。
        """
        doc_id = document["doc_id"]
        file_name = document["file_name"]
        saved_path = Path(document["source_path"])
        created_at = datetime.fromisoformat(document["created_at"])
        parser_debug_artifacts: dict[str, Any] = {}
        try:
            logger.info("Document processing started")
            self.metadata_store.update_document_status(doc_id, "processing")
            pages = self.parser.parse(saved_path)
            parser_debug_artifacts = self._consume_parser_debug_artifacts()
            mineru_visual_pages = {
                page.page_number
                for page in pages
                if page.metadata.get("mineru_visual_text")
            }
            mineru_manifest_path = (parser_debug_artifacts or {}).get("mineru_debug_manifest_path")
            if self.image_describer is not None and mineru_manifest_path:
                image_descriptions = self.image_describer.describe_mineru_md_images(
                    saved_path,
                    Path(str(mineru_manifest_path)),
                )
            else:
                image_descriptions = {}

            # Clean body text per page and clean each table's cells in place.
            body_pages: list[tuple[int, str]] = []
            all_tables: list[TableBlock] = []
            cleaned_bodies = self.cleaner.clean_page_texts([page.text for page in pages])
            for page, cleaned_body in zip(pages, cleaned_bodies, strict=False):
                body_pages.append((page.page_number, cleaned_body))
                for table in page.tables:
                    table.caption = self.cleaner.clean_cell(table.caption)
                    table.reference_text = self._table_context_after_period(
                        self.cleaner.clean_cell(table.reference_text)
                    )
                    table.pre_text = self._table_context_after_period(
                        self.cleaner.clean_cell(table.pre_text or table.reference_text)
                    )
                    table.reference_text = table.pre_text
                    table.post_text = self._table_context_before_period(
                        self.cleaner.clean_cell(table.post_text)
                    )
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
                        "pre_text": table.pre_text,
                        "post_text": table.post_text,
                        "page_start": table.page_start,
                        "page_end": table.page_end,
                        "header": table.header,
                        "rows": table.rows,
                        "text": serialize_table(table),
                    }
                )

            page_texts: list[tuple[int, str]] = []
            chunk_body_pages: list[tuple[int, str]] = []
            payload_pages: list[dict[str, Any]] = []
            for page_number, body_text in body_pages:
                page_tables = tables_by_page.get(page_number, [])
                cleaned_body_text = normalize_whitespace(body_text)
                for item in page_tables:
                    table_text = normalize_whitespace(str(item.get("text") or ""))
                    if table_text:
                        cleaned_body_text = cleaned_body_text.replace(table_text, " ")
                cleaned_page_text = normalize_whitespace(cleaned_body_text)
                page_texts.append((page_number, cleaned_page_text))
                chunk_body_pages.append((page_number, cleaned_page_text))
                payload_pages.append(
                    {
                        "page_number": page_number,
                        "text": cleaned_page_text,
                        "tables": page_tables,
                        "metadata": next(
                            (page.metadata for page in pages if page.page_number == page_number),
                            {},
                        ),
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
                chunk_body_pages,
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
                    "mineru_visual_pages": sorted(mineru_visual_pages),
                    **parser_debug_artifacts,
                },
            )
            embeddings = self.embedder.embed_texts([chunk.text for chunk in chunks]) if chunks else []
            # Replace the document's entire vector footprint on reprocessing.
            self.vector_store.delete_by_doc_id(doc_id)
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
                    "mineru_visual_pages": sorted(mineru_visual_pages),
                    "parser_debug": parser_debug_artifacts,
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
                    "mineru_visual_pages": sorted(mineru_visual_pages),
                    **parser_debug_artifacts,
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
            if not parser_debug_artifacts:
                parser_debug_artifacts = self._consume_parser_debug_artifacts()
            logger.exception("Failed to process PDF file=%s", file_name, exc_info=exc)
            parsed_placeholder = self.settings.parsed_dir / f"{doc_id}.json"
            self._cleanup_failed_processing(doc_id, parsed_placeholder, parser_debug_artifacts)
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
        """列出当前所有文档的元数据记录。"""
        return self.metadata_store.list_documents()

    def get_document(self, doc_id: str) -> dict[str, Any]:
        """按文档 ID 获取元数据记录，不存在时抛出 404 异常。"""
        document = self.metadata_store.get_document(doc_id)
        if not document:
            raise AppError("Document not found", status_code=404, details={"doc_id": doc_id})
        return document

    def delete_document(self, doc_id: str) -> None:
        """删除文档相关的向量、元数据和本地文件。

        这一步会同时清理原始 PDF、解析后的 JSON 文件，以及 MinerU 调试目录，
        用于彻底移除一个已入库文档的全部痕迹。
        """
        document = self.get_document(doc_id)
        self.vector_store.delete_by_doc_id(doc_id)
        self.metadata_store.delete_document(doc_id)
        self.file_store.delete_file(document["source_path"])
        self.file_store.delete_file(document["parsed_path"])
        mineru_debug_dir = (document.get("metadata") or {}).get("mineru_debug_dir")
        if mineru_debug_dir:
            self.file_store.delete_tree(mineru_debug_dir)

    def _cleanup_failed_processing(
        self,
        doc_id: str,
        parsed_placeholder: Path,
        parser_debug_artifacts: dict[str, Any] | None = None,
    ) -> None:
        """在处理失败后清理已写入的中间产物。

        主要是删除可能已经写入的向量记录、解析结果占位文件，
        以及失败前生成的调试目录，避免后续重试时读到脏数据。
        """
        try:
            self.vector_store.delete_by_doc_id(doc_id)
        except Exception:
            logger.exception("Failed to cleanup vector records")
        self.file_store.delete_file(parsed_placeholder)
        mineru_debug_dir = (parser_debug_artifacts or {}).get("mineru_debug_dir")
        if mineru_debug_dir:
            self.file_store.delete_tree(mineru_debug_dir)

    def _consume_parser_debug_artifacts(self) -> dict[str, Any]:
        """尝试从解析器读取一次性调试产物。

        某些解析器会在解析完成后缓存中间文件路径、调试清单等信息。
        这里以可选接口的方式取出它们，供元数据记录和错误排查使用。
        """
        getter = getattr(self.parser, "consume_debug_artifacts", None)
        if callable(getter):
            artifacts = getter()
            if isinstance(artifacts, dict):
                return artifacts
        return {}
