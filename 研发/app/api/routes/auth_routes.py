from fastapi import APIRouter, HTTPException

from app.api.auth import create_access_token
from app.api.schemas import AuthResponse, LoginRequest, RegisterRequest
from app.api.state import ensure_database_ready
from app.core.logging_utils import get_logger
from app.repositories.database import authenticate_user, register_user
from app.core.blocking import run_blocking


router = APIRouter()
logger = get_logger(__name__)


@router.post("/api/register", response_model=AuthResponse)
async def register(request: RegisterRequest):
    try:
        await run_blocking(ensure_database_ready)
        result = await run_blocking(
            register_user,
            request.username,
            request.email,
            request.password,
            request.confirm_password,
        )
        if not result["success"]:
            logger.info(
                "注册被拒绝: 用户名=%s 邮箱=%s 原因=%s",
                request.username,
                request.email,
                result["message"],
            )
            return AuthResponse(success=False, message=result["message"])
        logger.info(
            "注册成功: 用户名=%s 邮箱=%s", request.username, request.email
        )
        return AuthResponse(success=True, message=result["message"])
    except RuntimeError as exc:
        logger.exception("注册服务不可用")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("注册请求失败")
        raise HTTPException(status_code=500, detail=f"注册接口异常: {exc}") from exc


@router.post("/api/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    try:
        await run_blocking(ensure_database_ready)
        result = await run_blocking(
            authenticate_user,
            request.account,
            request.password,
        )
        if not result["success"]:
            logger.info(
                "登录被拒绝: 账号=%s 原因=%s",
                request.account,
                result["message"],
            )
            return AuthResponse(success=False, message=result["message"])
        user = result["user"]
        token = create_access_token(
            {
                "sub": str(user["id"]),
                "email": user["email"],
                "username": user["username"],
            }
        )
        logger.info(
            "登录成功: 用户ID=%s 用户名=%s", user["id"], user["username"]
        )
        return AuthResponse(
            success=True,
            message=result["message"],
            token=token,
            user=user,
        )
    except RuntimeError as exc:
        logger.exception("登录服务不可用")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("登录请求失败")
        raise HTTPException(status_code=500, detail=f"登录接口异常: {exc}") from exc
