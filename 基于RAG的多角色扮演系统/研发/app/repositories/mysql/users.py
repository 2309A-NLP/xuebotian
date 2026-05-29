from typing import Dict, Optional

import pymysql

from app.repositories.mysql.connection import get_db
from app.repositories.mysql.validation import (
    hash_password,
    needs_password_rehash,
    normalize_email,
    normalize_username,
    validate_email,
    validate_password,
    validate_password_match,
    validate_username,
    verify_password,
)


def get_user_by_id(user_id: int) -> Optional[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, email, is_admin, created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        return cursor.fetchone()


def list_users() -> list[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, email, is_admin, created_at
            FROM users
            ORDER BY id ASC
            """
        )
        return cursor.fetchall()


def _count_admin_users(cursor) -> int:
    cursor.execute("SELECT COUNT(*) AS admin_count FROM users WHERE is_admin = 1")
    return int((cursor.fetchone() or {}).get("admin_count", 0) or 0)


def update_user_admin(target_user_id: int, is_admin: bool, actor_user_id: int) -> dict:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, is_admin FROM users WHERE id = %s", (target_user_id,)
        )
        target_user = cursor.fetchone()
        if not target_user:
            return {"success": False, "message": "目标用户不存在"}
        if (
            target_user_id == actor_user_id
            and not is_admin
            and _count_admin_users(cursor) <= 1
        ):
            return {"success": False, "message": "至少需要保留一名管理员"}
        cursor.execute(
            "UPDATE users SET is_admin = %s WHERE id = %s",
            (1 if is_admin else 0, target_user_id),
        )
        return {"success": True, "message": "用户管理员状态更新成功"}


def delete_user(target_user_id: int, actor_user_id: int) -> dict:
    del actor_user_id
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, is_admin FROM users WHERE id = %s", (target_user_id,)
        )
        target_user = cursor.fetchone()
        if not target_user:
            return {"success": False, "message": "目标用户不存在"}
        if (
            int(target_user.get("is_admin", 0) or 0) == 1
            and _count_admin_users(cursor) <= 1
        ):
            return {"success": False, "message": "至少需要保留一名管理员"}
        cursor.execute("DELETE FROM users WHERE id = %s", (target_user_id,))
        return {"success": True, "message": "用户删除成功"}


def register_user(
    username: str, email: str, password: str, confirm_password: str
) -> dict:
    username_error = validate_username(username)
    if username_error:
        return {"success": False, "message": username_error}
    email_error = validate_email(email)
    if email_error:
        return {"success": False, "message": email_error}
    password_error = validate_password(password)
    if password_error:
        return {"success": False, "message": password_error}
    password_match_error = validate_password_match(password, confirm_password)
    if password_match_error:
        return {"success": False, "message": password_match_error}

    normalized_username = normalize_username(username)
    normalized_email = normalize_email(email)
    password_hash = hash_password(password)

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM users WHERE email = %s OR username = %s",
                (normalized_email, normalized_username),
            )
            if cursor.fetchone():
                return {"success": False, "message": "邮箱或用户名已存在"}

            cursor.execute("SELECT COUNT(*) AS user_count FROM users")
            user_count = int((cursor.fetchone() or {}).get("user_count", 0) or 0)
            is_admin = 1 if user_count == 0 else 0
            cursor.execute(
                """
                INSERT INTO users (username, email, password, is_admin)
                VALUES (%s, %s, %s, %s)
                """,
                (normalized_username, normalized_email, password_hash, is_admin),
            )
            return {"success": True, "message": "注册成功", "is_admin": bool(is_admin)}
    except pymysql.err.IntegrityError:
        return {"success": False, "message": "邮箱或用户名已存在"}
    except pymysql.MySQLError as exc:
        raise RuntimeError(f"注册失败，数据库操作异常: {exc}") from exc


def authenticate_user(account: str, password: str) -> dict:
    normalized_account = (account or "").strip()
    if not normalized_account or not password:
        return {"success": False, "message": "账号和密码不能为空"}

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, username, email, password, is_admin, created_at
                FROM users
                WHERE email = %s OR username = %s
                LIMIT 1
                """,
                (normalize_email(normalized_account), normalized_account),
            )
            user = cursor.fetchone()
            if not user or not verify_password(password, user.get("password") or ""):
                return {"success": False, "message": "账号或密码错误"}

            if needs_password_rehash(user["password"]):
                cursor.execute(
                    "UPDATE users SET password = %s WHERE id = %s",
                    (hash_password(password), user["id"]),
                )

            return {
                "success": True,
                "message": "登录成功",
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "email": user["email"],
                    "is_admin": bool(user.get("is_admin", 0)),
                    "created_at": user.get("created_at"),
                },
            }
    except pymysql.MySQLError as exc:
        raise RuntimeError(f"登录失败，数据库操作异常: {exc}") from exc
