from app.repositories.mysql.connection import get_db
from app.repositories.mysql.validation import (
    _generate_unique_username,
    normalize_email,
)


def _ensure_user_schema(cursor) -> None:
    cursor.execute("SHOW COLUMNS FROM users LIKE 'username'")
    username_column = cursor.fetchone()
    if not username_column:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN username VARCHAR(64) NULL AFTER id"
        )

    cursor.execute("SHOW COLUMNS FROM users LIKE 'is_admin'")
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0"
        )

    cursor.execute(
        """
        SELECT id, email, username
        FROM users
        WHERE username IS NULL OR TRIM(username) = ''
        ORDER BY id ASC
        """
    )
    for row in cursor.fetchall():
        email = normalize_email(row.get("email") or "")
        seed = email.split("@", 1)[0] if "@" in email else f"user{row['id']}"
        username = _generate_unique_username(cursor, seed, user_id=row["id"])
        cursor.execute(
            "UPDATE users SET username = %s WHERE id = %s",
            (username, row["id"]),
        )

    cursor.execute(
        "SHOW INDEX FROM users WHERE Column_name = 'username' AND Non_unique = 0"
    )
    if not cursor.fetchone():
        cursor.execute(
            "ALTER TABLE users ADD UNIQUE KEY uniq_users_username (username)"
        )

    if not username_column or (username_column.get("Null") or "").upper() == "YES":
        cursor.execute("ALTER TABLE users MODIFY COLUMN username VARCHAR(64) NOT NULL")


def _ensure_chat_schema(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id VARCHAR(255) PRIMARY KEY,
            user_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            character_name VARCHAR(255) NOT NULL DEFAULT '',
            chat_mode VARCHAR(32) NOT NULL DEFAULT 'offline',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_chat_sessions_user_id (user_id),
            INDEX idx_chat_sessions_updated_at (updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_turns (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            session_id VARCHAR(255) NOT NULL,
            user_message TEXT NOT NULL,
            assistant_message TEXT NOT NULL,
            character_name VARCHAR(255) NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_chat_turns_session_id (session_id),
            INDEX idx_chat_turns_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS character_profiles (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(255) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uniq_character_profiles_name (name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _ensure_at_least_one_admin(cursor) -> None:
    cursor.execute("SELECT COUNT(*) AS admin_count FROM users WHERE is_admin = 1")
    admin_count = int((cursor.fetchone() or {}).get("admin_count", 0) or 0)
    if admin_count > 0:
        return

    cursor.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    first_user = cursor.fetchone()
    if first_user:
        cursor.execute(
            "UPDATE users SET is_admin = 1 WHERE id = %s",
            (first_user["id"],),
        )


def init_database():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT PRIMARY KEY AUTO_INCREMENT,
                email VARCHAR(255) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        _ensure_user_schema(cursor)
        _ensure_chat_schema(cursor)
        _ensure_at_least_one_admin(cursor)
