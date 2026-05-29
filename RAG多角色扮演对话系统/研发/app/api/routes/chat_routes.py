import asyncio
import json
from threading import Thread
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.auth import get_current_user
from app.api.schemas import CharacterItem, ChatRequest, ChatResponse, ClearRequest
from app.api.state import (
    build_character_items,
    ensure_knowledge_base_ready,
    get_rag_system,
)
from app.core.blocking import run_blocking
from app.core.logging_utils import get_logger
from app.repositories.database import (
    clear_chat_session,
    delete_chat_session,
    get_chat_session_messages,
    list_chat_sessions,
    save_chat_message,
)


router = APIRouter()
logger = get_logger(__name__)


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/api/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.get("/api/characters", response_model=List[CharacterItem])
async def get_characters(current_user: dict = Depends(get_current_user)):
    del current_user
    await run_blocking(ensure_knowledge_base_ready)
    return await run_blocking(build_character_items)


@router.get("/api/rag/sessions")
async def get_rag_sessions(current_user: dict = Depends(get_current_user)):
    sessions = await run_blocking(list_chat_sessions, current_user["id"])
    messages = await asyncio.gather(
        *[
            run_blocking(get_chat_session_messages, session["session_id"])
            for session in sessions
        ]
    )
    for session, session_messages in zip(sessions, messages):
        session["messages"] = session_messages
    logger.info(
        "已加载会话列表: 用户ID=%s 会话数量=%s",
        current_user["id"],
        len(sessions),
    )
    return sessions


@router.post("/api/rag/chat", response_model=ChatResponse)
async def rag_chat(
    request: ChatRequest, current_user: dict = Depends(get_current_user)
):
    try:
        rag = await run_blocking(ensure_knowledge_base_ready)
        result = await run_blocking(
            rag.chat,
            query=request.query,
            session_id=request.session_id,
            character_name=request.character_name,
            chat_mode=request.chat_mode,
        )
        await run_blocking(
            save_chat_message,
            user_id=current_user["id"],
            session_id=request.session_id,
            title=request.conversation_title or "",
            character_name=request.character_name,
            chat_mode=request.chat_mode,
            user_message=request.query,
            assistant_message=result.get("response", ""),
        )
        logger.info(
            "对话接口完成: 用户ID=%s 会话ID=%s 来源=%s",
            current_user["id"],
            request.session_id,
            [
                {
                    "name": item.get("name"),
                    "rerank_score": item.get("rerank_score"),
                    "text": (item.get("text") or "")[:160],
                }
                for item in result.get("sources", [])
            ],
        )
        return ChatResponse(**result)
    except RuntimeError as exc:
        logger.exception("对话服务不可用")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("对话请求失败")
        raise HTTPException(status_code=500, detail=f"服务暂时不可用: {exc}") from exc


@router.post("/api/rag/chat/stream")
async def rag_chat_stream(
    request: ChatRequest, current_user: dict = Depends(get_current_user)
):
    rag = await run_blocking(ensure_knowledge_base_ready)

    def event_stream():
        try:
            for item in rag.stream_chat(
                query=request.query,
                session_id=request.session_id,
                character_name=request.character_name,
                chat_mode=request.chat_mode,
            ):
                event = item.get("event") or "message"
                data = item.get("data") or {}

                if event == "done":
                    Thread(
                        target=save_chat_message,
                        kwargs={
                            "user_id": current_user["id"],
                            "session_id": request.session_id,
                            "title": request.conversation_title or "",
                            "character_name": request.character_name,
                            "chat_mode": request.chat_mode,
                            "user_message": request.query,
                            "assistant_message": data.get("response", ""),
                        },
                        daemon=True,
                    ).start()
                    logger.info(
                        "对话流式接口完成: 用户ID=%s 会话ID=%s ",
                        current_user["id"],
                        request.session_id
                    )

                yield _format_sse(event, data)
        except RuntimeError as exc:
            logger.exception("对话流式服务不可用")
            yield _format_sse("error", {"message": str(exc)})
        except Exception as exc:
            logger.exception("对话流式请求失败")
            yield _format_sse("error", {"message": f"服务暂时不可用: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream; charset=utf-8",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/rag/clear")
async def clear_rag_session(
    request: ClearRequest, current_user: dict = Depends(get_current_user)
):
    del current_user
    try:
        rag = await run_blocking(get_rag_system)
        await run_blocking(rag.delete_session, request.session_id)
        await run_blocking(
            clear_chat_session,
            session_id=request.session_id,
            title=request.conversation_title or "",
            character_name=request.character_name or "",
            chat_mode=request.chat_mode,
        )
        logger.info("已清空会话: 会话ID=%s", request.session_id)
        return {"message": f"Session {request.session_id} short-term memory cleared"}
    except Exception as exc:
        logger.exception("清空会话失败: 会话ID=%s", request.session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/rag/session/delete")
async def delete_rag_session(
    request: ClearRequest, current_user: dict = Depends(get_current_user)
):
    del current_user
    try:
        rag = await run_blocking(get_rag_system)
        await run_blocking(rag.delete_session, request.session_id)
        await run_blocking(delete_chat_session, request.session_id)
        logger.info("已删除会话: 会话ID=%s", request.session_id)
        return {"message": f"Session {request.session_id} deleted"}
    except Exception as exc:
        logger.exception("删除会话失败: 会话ID=%s", request.session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat", response_model=ChatResponse)
async def legacy_chat(
    request: ChatRequest, current_user: dict = Depends(get_current_user)
):
    return await rag_chat(request, current_user)


@router.post("/clear_session")
async def legacy_clear_session(
    request: ClearRequest, current_user: dict = Depends(get_current_user)
):
    return await clear_rag_session(request, current_user)
