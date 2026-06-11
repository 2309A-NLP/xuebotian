from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ApiResponse


class UploadDocumentData(BaseModel):
    doc_id: str
    file_name: str
    status: str
    page_count: int
    chunk_count: int
    parsed_path: str
    created_at: datetime


class UploadDocumentResponse(ApiResponse):
    data: UploadDocumentData


class DocumentSummary(BaseModel):
    doc_id: str
    file_name: str
    status: str
    page_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    parsed_path: str
    source_path: str
    parse_error: str | None = None
    metadata: dict = Field(default_factory=dict)


class DocumentListResponse(ApiResponse):
    data: list[DocumentSummary]


class DocumentDetailResponse(ApiResponse):
    data: DocumentDetail
