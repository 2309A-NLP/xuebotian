from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import chat, documents, health, speech
from app.core.config import get_settings
from app.core.container import AppContainer
from app.core.exceptions import AppError, app_error_handler, unhandled_error_handler
from app.core.log_context import bind_request_id
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_dir, settings.debug)
    container = AppContainer(settings)
    container.warmup()
    app.state.settings = settings
    app.state.container = container
    try:
        yield
    finally:
        container.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(speech.router, prefix="/api")

    @app.middleware("http")
    async def request_log_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        with bind_request_id(request_id):
            logger.info("Request started %s %s", request.method, request.url.path)
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "Request completed %s %s status=%s",
                request.method,
                request.url.path,
                response.status_code,
            )
            return response

    frontend_dir = Path("frontend")
    assets_dir = frontend_dir / "assets"
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()
