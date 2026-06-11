from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ApiResponse


class LoginRequest(BaseModel):
    username: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=8, max_length=32)


class RegisterRequest(LoginRequest):
    confirm_password: str = Field(min_length=8, max_length=32)


class AuthUserData(BaseModel):
    user_id: str
    username: str
    created_at: datetime
    updated_at: datetime


class AuthUserResponse(ApiResponse):
    data: AuthUserData
