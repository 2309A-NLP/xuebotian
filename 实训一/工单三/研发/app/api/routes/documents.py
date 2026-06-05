from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_container
from app.core.container import AppContainer
from app.schemas.common import ApiResponse
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListResponse,
    UploadDocumentData,
    UploadDocumentResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadDocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
) -> UploadDocumentResponse:
    record = container.document_service.ingest_pdf(file)
    return UploadDocumentResponse(
        message="document uploaded",
        data=UploadDocumentData(**record),
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    container: AppContainer = Depends(get_container),
) -> DocumentListResponse:
    records = container.document_service.list_documents()
    return DocumentListResponse(data=records)


@router.get("/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(
    doc_id: str,
    container: AppContainer = Depends(get_container),
) -> DocumentDetailResponse:
    record = container.document_service.get_document(doc_id)
    return DocumentDetailResponse(data=record)


@router.get("/{doc_id}/content")
async def get_document_content(
    doc_id: str,
    container: AppContainer = Depends(get_container),
) -> dict:
    record = container.document_service.get_document(doc_id)
    parsed_path = Path(record["parsed_path"])
    payload = {}
    if parsed_path.exists():
        payload = json.loads(parsed_path.read_text(encoding="utf-8"))
    return {"success": True, "message": "ok", "data": payload}


@router.delete("/{doc_id}", response_model=ApiResponse)
async def delete_document(
    doc_id: str,
    container: AppContainer = Depends(get_container),
) -> ApiResponse:
    container.document_service.delete_document(doc_id)
    return ApiResponse(message="document deleted")
