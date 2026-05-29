import re
from typing import Optional

import bcrypt as bcrypt_lib
from passlib.hash import pbkdf2_sha256


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
USERNAME_REGEX = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{2,24}$")
USERNAME_SANITIZE_REGEX = re.compile(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+")
PASSWORD_MIN_LENGTH = 8


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_username(username: str) -> str:
    return (username or "").strip()


def validate_email(email: str) -> Optional[str]:
    email = normalize_email(email)
    if not email:
        return "邮箱不能为空"
    if not EMAIL_REGEX.match(email):
        return "邮箱格式不正确"
    return None


def validate_username(username: str) -> Optional[str]:
    username = normalize_username(username)
    if not username:
        return "用户名不能为空"
    if not USERNAME_REGEX.match(username):
        return "用户名需为 2-24 位，可使用中文、字母、数字、下划线或短横线"
    return None


def validate_password(password: str) -> Optional[str]:
    if not password:
        return "密码不能为空"
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"密码长度不能少于 {PASSWORD_MIN_LENGTH} 位"
    if not re.search(r"[A-Z]", password):
        return "密码必须包含至少一个大写字母"
    if not re.search(r"[a-z]", password):
        return "密码必须包含至少一个小写字母"
    if not re.search(r"\d", password):
        return "密码必须包含至少一个数字"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", password):
        return "密码必须包含至少一个特殊字符"
    return None


def validate_password_match(password: str, confirm_password: str) -> Optional[str]:
    if password != confirm_password:
        return "两次输入的密码不一致"
    return None


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    if hashed_password.startswith("$pbkdf2-sha256$"):
        return pbkdf2_sha256.verify(plain_password, hashed_password)
    if hashed_password.startswith("$2"):
        password_bytes = plain_password.encode("utf-8")
        if len(password_bytes) > 72:
            return False
        try:
            return bcrypt_lib.checkpw(password_bytes, hashed_password.encode("utf-8"))
        except ValueError:
            return False
    return False


def needs_password_rehash(hashed_password: str) -> bool:
    return not hashed_password.startswith("$pbkdf2-sha256$")


def _sanitize_username_seed(seed: str) -> str:
    cleaned = USERNAME_SANITIZE_REGEX.sub("", normalize_username(seed))
    return cleaned[:24]


def _generate_unique_username(cursor, seed: str, user_id: Optional[int] = None) -> str:
    base = _sanitize_username_seed(seed)
    if len(base) < 2:
        base = _sanitize_username_seed(f"user{user_id or ''}") or "user"

    candidate = base[:24]
    suffix = 1
    while True:
        cursor.execute("SELECT id FROM users WHERE username = %s", (candidate,))
        row = cursor.fetchone()
        if not row or (user_id is not None and int(row["id"]) == int(user_id)):
            return candidate
        suffix_text = str(suffix)
        max_base_length = max(2, 24 - len(suffix_text))
        candidate = f"{base[:max_base_length]}{suffix_text}"
        suffix += 1
