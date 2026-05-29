from typing import Dict, List

from app.repositories.mysql.connection import get_db


def _build_character_name_rows(characters: List[Dict[str, str]]) -> List[tuple]:
    rows = []
    seen = set()
    for item in characters:
        name = (item.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            rows.append((name,))
    return rows


def sync_character_profiles(
    characters: List[Dict[str, str]],
    replace_existing: bool = False,
) -> None:
    rows = _build_character_name_rows(characters)
    with get_db() as conn:
        cursor = conn.cursor()
        if replace_existing:
            cursor.execute("DELETE FROM character_profiles")
        if rows:
            cursor.executemany(
                """
                INSERT INTO character_profiles (name)
                VALUES (%s)
                ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )


def list_character_profiles() -> List[Dict]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name
            FROM character_profiles
            ORDER BY name ASC
            """
        )
        return cursor.fetchall()
