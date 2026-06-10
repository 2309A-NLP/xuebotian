from __future__ import annotations

from fastapi import Request

from app.core.container import AppContainer
from app.services.auth.service import AuthService


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_auth_service(request: Request) -> AuthService:
    return get_container(request).auth_service


def get_current_user(request: Request) -> dict:
    return get_auth_service(request).require_current_user(request)
