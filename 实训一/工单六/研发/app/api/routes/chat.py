from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_container, get_current_user
from app.core.container import AppContainer
from app.schemas.common import ApiResponse
from app.schemas.chat import ChatData, ChatRequest, ChatResponse, RetrievedChunkView

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    container: AppContainer = Depends(get_container),
    current_user: dict = Depends(get_current_user),
) -> ChatResponse:
    session_id = request.session_id or "default"
    history = container.conversation_history.get_messages(current_user["user_id"], session_id)
    result = container.rag_pipeline.answer(
        question=request.question,
        doc_ids=request.doc_ids,
        top_k=request.top_k,
        history=history,
    )
    container.conversation_history.append_turn(
        current_user["user_id"],
        session_id,
        request.question,
        result["answer"],
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
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    session_id = request.session_id or "default"
    history = container.conversation_history.get_messages(current_user["user_id"], session_id)

    def event_generator():
        try:
            yield from container.rag_pipeline.stream_answer(
                question=request.question,
                doc_ids=request.doc_ids,
                top_k=request.top_k,
                history=history,
                on_complete=lambda answer: container.conversation_history.append_turn(
                    current_user["user_id"],
                    session_id,
                    request.question,
                    answer,
                ),
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


@router.delete("/sessions/{session_id}", response_model=ApiResponse)
async def clear_chat_session(
    session_id: str,
    container: AppContainer = Depends(get_container),
    current_user: dict = Depends(get_current_user),
) -> ApiResponse:
    container.conversation_history.clear_session(current_user["user_id"], session_id)
    return ApiResponse(message="会话历史已清空。")
