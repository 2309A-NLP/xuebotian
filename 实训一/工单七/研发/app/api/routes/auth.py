from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_auth_service, get_current_user
from app.schemas.auth import AuthUserData, AuthUserResponse, LoginRequest, RegisterRequest
from app.schemas.common import ApiResponse
from app.services.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthUserResponse:
    user = auth_service.register_user(
        username=request.username,
        password=request.password,
        confirm_password=request.confirm_password,
    )
    auth_service.set_auth_cookie(response, user)
    return AuthUserResponse(
        message="注册成功，已自动登录，正在进入聊天界面。",
        data=AuthUserData(**user),
    )


@router.post("/login", response_model=AuthUserResponse)
async def login(
    request: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthUserResponse:
    user = auth_service.authenticate_user(request.username, request.password)
    auth_service.set_auth_cookie(response, user)
    return AuthUserResponse(
        message="登录成功，正在进入聊天界面。",
        data=AuthUserData(**user),
    )


@router.post("/logout", response_model=ApiResponse)
async def logout(
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> ApiResponse:
    auth_service.clear_auth_cookie(response)
    return ApiResponse(message="你已安全退出登录。")


@router.get("/me", response_model=AuthUserResponse)
async def me(current_user: dict = Depends(get_current_user)) -> AuthUserResponse:
    return AuthUserResponse(
        message="当前登录状态有效。",
        data=AuthUserData(**current_user),
    )
