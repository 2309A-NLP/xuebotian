from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import Request, Response

from app.core.config import Settings
from app.core.exceptions import AppError

try:
    import pymysql
    from pymysql.cursors import DictCursor
    from pymysql.err import IntegrityError, MySQLError
except ImportError as exc:  # pragma: no cover - dependency check at runtime
    raise RuntimeError(
        "PyMySQL is required for MySQL authentication support. "
        "Please install dependencies from requirements.txt."
    ) from exc


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{4,20}$")


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            self._ensure_database()
            self._ensure_tables()
        except MySQLError as exc:
            raise RuntimeError(
                "无法连接或初始化 MySQL 用户库，请检查 .env 中的 MYSQL_* 配置，并确认数据库服务可用。"
            ) from exc

    def register_user(self, username: str, password: str, confirm_password: str) -> dict[str, Any]:
        normalized_username = self._normalize_username(username)
        self._validate_username(normalized_username)
        self._validate_password(password)

        if password != confirm_password:
            raise AppError("两次输入的密码不一致，请重新确认后再提交。", status_code=400)

        if self.get_user_by_username(normalized_username):
            raise AppError("该用户名已被注册，请换一个用户名后重试。", status_code=409)

        now = datetime.now()
        password_salt = secrets.token_hex(16)
        user = {
            "user_id": uuid4().hex,
            "username": normalized_username,
            "password_hash": self._hash_password(password, password_salt),
            "password_salt": password_salt,
            "created_at": now,
            "updated_at": now,
        }

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        user_id, username, password_hash, password_salt, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user["user_id"],
                        user["username"],
                        user["password_hash"],
                        user["password_salt"],
                        user["created_at"],
                        user["updated_at"],
                    ),
                )
            connection.commit()
        except IntegrityError as exc:
            raise AppError("该用户名已被注册，请换一个用户名后重试。", status_code=409) from exc
        finally:
            connection.close()

        return self._public_user(user)

    def authenticate_user(self, username: str, password: str) -> dict[str, Any]:
        normalized_username = self._normalize_username(username)
        if not normalized_username or not password:
            raise AppError("请输入完整的用户名和密码后再登录。", status_code=400)

        user = self.get_user_by_username(normalized_username, include_secret=True)
        if user and (
            "password_salt" not in user
            or "password_hash" not in user
            or not user.get("password_salt")
            or not user.get("password_hash")
        ):
            raise AppError(
                "当前用户数据不完整。请删除该账号后重新注册，或清空 users 表后重新创建账号。",
                status_code=500,
            )
        if not user or not self._verify_password(password, user["password_salt"], user["password_hash"]):
            raise AppError(
                "用户名或密码不正确，请检查后重试。如果你还没有账号，请先完成注册。",
                status_code=401,
            )

        return self._public_user(user)

    def get_user_by_username(
        self,
        username: str,
        *,
        include_secret: bool = False,
    ) -> dict[str, Any] | None:
        normalized_username = self._normalize_username(username)
        if not normalized_username:
            return None

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM users WHERE username = %s LIMIT 1",
                    (normalized_username,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if not row:
            return None
        return row if include_secret else self._public_user(row)

    def get_user_by_id(
        self,
        user_id: str,
        *,
        include_secret: bool = False,
    ) -> dict[str, Any] | None:
        if not user_id:
            return None

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM users WHERE user_id = %s LIMIT 1",
                    (user_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if not row:
            return None
        return row if include_secret else self._public_user(row)

    def issue_token(self, user: dict[str, Any]) -> str:
        payload = {
            "user_id": user["user_id"],
            "username": user["username"],
            "exp": int(time.time()) + self.settings.auth_token_ttl_hours * 3600,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        payload_part = self._urlsafe_b64encode(payload_json.encode("utf-8"))
        signature = hmac.new(
            self.settings.auth_secret_key.encode("utf-8"),
            payload_part.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature_part = self._urlsafe_b64encode(signature)
        return f"{payload_part}.{signature_part}"

    def decode_token(self, token: str) -> dict[str, Any] | None:
        if not token or "." not in token:
            return None

        payload_part, signature_part = token.split(".", 1)
        expected_signature = hmac.new(
            self.settings.auth_secret_key.encode("utf-8"),
            payload_part.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        try:
            provided_signature = self._urlsafe_b64decode(signature_part)
        except Exception:
            return None

        if not hmac.compare_digest(provided_signature, expected_signature):
            return None

        try:
            payload_json = self._urlsafe_b64decode(payload_part).decode("utf-8")
            payload = json.loads(payload_json)
        except Exception:
            return None

        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload

    def get_current_user_from_request(self, request: Request) -> dict[str, Any] | None:
        token = request.cookies.get(self.settings.auth_cookie_name)
        payload = self.decode_token(token or "")
        if not payload:
            return None
        return self.get_user_by_id(payload.get("user_id", ""))

    def require_current_user(self, request: Request) -> dict[str, Any]:
        user = self.get_current_user_from_request(request)
        if user is None:
            raise AppError(
                "当前登录状态不可用，请重新登录后再继续操作。",
                status_code=401,
                details={"code": "auth_required"},
            )
        return user

    def set_auth_cookie(self, response: Response, user: dict[str, Any]) -> None:
        response.set_cookie(
            key=self.settings.auth_cookie_name,
            value=self.issue_token(user),
            max_age=self.settings.auth_token_ttl_hours * 3600,
            httponly=True,
            secure=self.settings.auth_cookie_secure,
            samesite=self.settings.auth_cookie_samesite,
            path="/",
        )

    def clear_auth_cookie(self, response: Response) -> None:
        response.delete_cookie(
            key=self.settings.auth_cookie_name,
            path="/",
            samesite=self.settings.auth_cookie_samesite,
            secure=self.settings.auth_cookie_secure,
        )

    def _connect(self, *, include_database: bool = True):
        connection_options = {
            "host": self.settings.mysql_host,
            "port": self.settings.mysql_port,
            "user": self.settings.mysql_user,
            "password": self.settings.mysql_password,
            "charset": self.settings.mysql_charset,
            "cursorclass": DictCursor,
            "autocommit": False,
        }
        if include_database:
            connection_options["database"] = self.settings.mysql_database
        return pymysql.connect(**connection_options)

    def _ensure_database(self) -> None:
        connection = self._connect(include_database=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    (
                        f"CREATE DATABASE IF NOT EXISTS `{self.settings.mysql_database}` "
                        f"CHARACTER SET {self.settings.mysql_charset}"
                    )
                )
            connection.commit()
        finally:
            connection.close()

    def _ensure_tables(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        user_id VARCHAR(64) PRIMARY KEY,
                        username VARCHAR(64) NOT NULL UNIQUE,
                        password_hash VARCHAR(128) NOT NULL,
                        password_salt VARCHAR(64) NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            connection.commit()
        finally:
            connection.close()

    def _normalize_username(self, username: str) -> str:
        return (username or "").strip()

    def _validate_username(self, username: str) -> None:
        if not username:
            raise AppError("请输入用户名后再继续。", status_code=400)
        if not USERNAME_PATTERN.fullmatch(username):
            raise AppError(
                "用户名需为 4-20 位，只能包含中文、字母、数字或下划线。",
                status_code=400,
            )

    def _validate_password(self, password: str) -> None:
        if not password:
            raise AppError("请输入密码后再继续。", status_code=400)
        if len(password) < 8 or len(password) > 32:
            raise AppError("密码长度需要在 8 到 32 位之间。", status_code=400)
        if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            raise AppError("密码需要同时包含字母和数字，便于提升账号安全性。", status_code=400)

    def _hash_password(self, password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            390000,
        )
        return base64.b64encode(digest).decode("ascii")

    def _verify_password(self, password: str, salt: str, expected_hash: str) -> bool:
        actual_hash = self._hash_password(password, salt)
        return hmac.compare_digest(actual_hash, expected_hash)

    def _public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "created_at": user["created_at"],
            "updated_at": user["updated_at"],
        }

    def _urlsafe_b64encode(self, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    def _urlsafe_b64decode(self, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}")
