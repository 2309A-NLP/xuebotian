import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import configure_auth
from app.api.routes.admin_routes import router as admin_router
from app.api.routes.auth_routes import router as auth_router
from app.api.routes.chat_routes import router as chat_router
from app.api.routes.system_routes import mount_static, router as system_router
from app.api.state import bootstrap_application, ensure_database_ready
from app.core.logging_utils import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    app.state.startup_ready = False
    app.state.startup_error = None
    app.state.startup_summary = None
    app.state.startup_stage = "starting"
    app.state.startup_task = asyncio.create_task(bootstrap_application(app))
    yield


app = FastAPI(title="多角色扮演 RAG 系统", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

configure_auth(ensure_database_ready)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(system_router)
mount_static(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
