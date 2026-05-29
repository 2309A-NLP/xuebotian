from typing import Dict, List

from app.repositories.mysql.connection import get_db


def _normalize_chat_mode(chat_mode: str) -> str:
    return "online" if (chat_mode or "").strip().lower() == "online" else "offline"


def _normalize_chat_title(
    title: str, user_message: str = "", character_name: str = ""
) -> str:
    normalized = (title or "").strip()
    if normalized:
        return normalized[:255]

    normalized_user_message = (user_message or "").strip()
    if normalized_user_message:
        if len(normalized_user_message) <= 80:
            return normalized_user_message
        return normalized_user_message[:77].rstrip() + "..."

    normalized_character_name = (character_name or "").strip()
    if normalized_character_name:
        return f"{normalized_character_name} 的对话"
    return "新的对话"


def save_chat_message(
    user_id: int,
    session_id: str,
    title: str,
    character_name: str,
    chat_mode: str,
    user_message: str,
    assistant_message: str,
) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_sessions (session_id, user_id, title, character_name, chat_mode)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                title = VALUES(title),
                character_name = VALUES(character_name),
                chat_mode = VALUES(chat_mode),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                session_id,
                user_id,
                _normalize_chat_title(title, user_message, character_name),
                (character_name or "").strip(),
                _normalize_chat_mode(chat_mode),
            ),
        )
        cursor.execute(
            """
            INSERT INTO chat_turns (session_id, user_message, assistant_message, character_name)
            VALUES (%s, %s, %s, %s)
            """,
            (
                session_id,
                user_message,
                assistant_message,
                (character_name or "").strip(),
            ),
        )


def list_chat_sessions(user_id: int) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                cs.session_id,
                cs.title,
                cs.character_name,
                cs.chat_mode,
                cs.created_at,
                cs.updated_at,
                (
                    SELECT COUNT(*)
                    FROM chat_turns ct
                    WHERE ct.session_id = cs.session_id
                ) AS message_count
            FROM chat_sessions cs
            WHERE cs.user_id = %s
            ORDER BY cs.updated_at DESC, cs.created_at DESC
            """,
            (user_id,),
        )
        return cursor.fetchall()


def get_chat_session_messages(session_id: str, limit: int = 50) -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_message, assistant_message, character_name, created_at
            FROM chat_turns
            WHERE session_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (session_id, max(1, int(limit))),
        )
        rows = list(cursor.fetchall())
        rows.reverse()
        return rows


def clear_chat_session(
    session_id: str,
    title: str = "",
    character_name: str = "",
    chat_mode: str = "offline",
) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_turns WHERE session_id = %s", (session_id,))
        cursor.execute(
            """
            UPDATE chat_sessions
            SET title = %s, character_name = %s, chat_mode = %s, updated_at = CURRENT_TIMESTAMP
            WHERE session_id = %s
            """,
            (
                _normalize_chat_title(title, "", character_name),
                (character_name or "").strip(),
                _normalize_chat_mode(chat_mode),
                session_id,
            ),
        )


def delete_chat_session(session_id: str) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_turns WHERE session_id = %s", (session_id,))
        cursor.execute("DELETE FROM chat_sessions WHERE session_id = %s", (session_id,))
