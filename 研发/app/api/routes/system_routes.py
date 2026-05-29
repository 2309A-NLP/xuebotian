from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import state as app_state
from app.core.config import DATA_DIR
from app.core.blocking import run_blocking


STATIC_DIR = DATA_DIR.parent / "static"
router = APIRouter()


@router.get("/health")
async def health():
    from app.main import app

    startup_ready = bool(getattr(app.state, "startup_ready", False))
    startup_error = getattr(app.state, "startup_error", None)
    startup_summary = getattr(app.state, "startup_summary", None)
    startup_stage = getattr(app.state, "startup_stage", None)
    rag = app_state.rag_system
    if rag is None:
        redis_ok = False
        milvus_ok = False
        rag_ok = False
        rag_error = "RAG system not initialized"
    else:
        try:
            redis_ok = await run_blocking(rag.memory.ping)
            milvus_ok = await run_blocking(rag.vector_store.ping)
            rag_ok = True
            rag_error = None
        except Exception as exc:
            redis_ok = False
            milvus_ok = False
            rag_ok = False
            rag_error = str(exc)
    return {
        "status": "ok" if redis_ok and milvus_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        "milvus": "connected" if milvus_ok else "disconnected",
        "rag": "ready" if rag_ok else "unavailable",
        "error": rag_error,
        "startup_ready": startup_ready,
        "startup_error": startup_error,
        "startup_summary": startup_summary,
        "startup_stage": startup_stage,
        "data_dir": str(DATA_DIR),
    }


@router.get("/")
async def serve_login():
    return FileResponse(STATIC_DIR / "login.html")


@router.get("/login")
async def serve_login_alias():
    return FileResponse(STATIC_DIR / "login.html")


@router.get("/chat")
async def serve_chat_page():
    return FileResponse(STATIC_DIR / "chat.html")


@router.get("/admin")
async def serve_admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


def mount_static(app) -> None:
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
