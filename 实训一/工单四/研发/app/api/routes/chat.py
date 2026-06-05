from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

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
            page_end=item.page_end,
            score=item.score,
            source_file=item.source_file,
            text=item.text,
            metadata=item.metadata,
        )
        for item in result["references"]
    ]
    return ChatResponse(
        data=ChatData(
            normalized_question=result["normalized_question"],
            intent=result["intent"],
            answer=result["answer"],
            references=references,
            timing=result.get("timing"),
        )
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    def event_generator():
        try:
            yield from container.rag_pipeline.stream_answer(
                question=request.question,
                doc_ids=request.doc_ids,
                top_k=request.top_k,
            )
        except Exception as exc:
            payload = json.dumps({"message": str(exc)}, ensure_ascii=False)
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
