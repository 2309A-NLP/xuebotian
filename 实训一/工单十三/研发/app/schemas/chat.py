from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ApiResponse


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    doc_ids: list[str] | None = None
    top_k: int | None = None


class RetrievedChunkView(BaseModel):
    chunk_id: str
    doc_id: str
    page: int
    page_end: int | None = None
    score: float
    source_file: str
    text: str
    metadata: dict = Field(default_factory=dict)


class ChatData(BaseModel):
    normalized_question: str
    intent: str
    answer: str
    references: list[RetrievedChunkView]
    timing: dict | None = None


class ChatResponse(ApiResponse):
    data: ChatData
