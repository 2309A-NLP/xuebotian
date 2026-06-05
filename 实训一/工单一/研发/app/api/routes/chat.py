from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import AppContainer
from app.schemas.chat import ChatData, ChatRequest, ChatResponse, RetrievedChunkView

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    container: AppContainer = Depends(get_container),
) -> ChatResponse:
    result = container.rag_pipeline.answer(
        question=request.question,
        doc_ids=request.doc_ids,
        top_k=request.top_k,
    )
    references = [
        RetrievedChunkView(
            chunk_id=item.chunk_id,
            doc_id=item.doc_id,
            page=item.page,
            score=item.score,
            source_file=item.source_file,
            text=item.text,
        )
        for item in result["references"]
    ]
    return ChatResponse(
        data=ChatData(
            normalized_question=result["normalized_question"],
            intent=result["intent"],
            answer=result["answer"],
            references=references,
        )
    )
