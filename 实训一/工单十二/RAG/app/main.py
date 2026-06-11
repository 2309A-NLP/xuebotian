from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, chat, documents, health, speech
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
    app.include_router(auth.router, prefix="/api")
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

    def is_authenticated(request: Request) -> bool:
        container: AppContainer = request.app.state.container
        return container.auth_service.get_current_user_from_request(request) is not None

    @app.get("/", include_in_schema=False)
    async def root(request: Request) -> RedirectResponse:
        target = "/chat" if is_authenticated(request) else "/login"
        return RedirectResponse(url=target, status_code=302)

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        if is_authenticated(request):
            return RedirectResponse(url="/chat", status_code=302)
        return FileResponse(frontend_dir / "login.html")

    @app.get("/register", include_in_schema=False)
    async def register_page(request: Request):
        if is_authenticated(request):
            return RedirectResponse(url="/chat", status_code=302)
        return FileResponse(frontend_dir / "register.html")

    @app.get("/chat", include_in_schema=False)
    async def chat_page(request: Request):
        if not is_authenticated(request):
            return RedirectResponse(url="/login?message=login_required", status_code=302)
        return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()
