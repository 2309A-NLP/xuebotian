from __future__ import annotations

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = True
    message: str = "ok"
