from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    logger.warning("Application error: %s | details=%s", exc.message, exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.message, "details": exc.details},
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception captured", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "details": {"type": exc.__class__.__name__},
        },
    )
