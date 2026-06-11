from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class MetadataStore:
    """负责文档元数据的 SQLite 持久化读写。"""
    def __init__(self, db_path: Path) -> None:
        """初始化元数据存储所需的依赖和运行参数。"""
        self.db_path = db_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """处理connect。"""
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        """初始化文档元数据表结构。"""
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    parsed_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    parse_error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def upsert_document(self, record: dict[str, Any]) -> None:
        """新增或更新文档。"""
        now = datetime.now().isoformat()
        payload = {
            "doc_id": record["doc_id"],
            "file_name": record["file_name"],
            "source_path": record["source_path"],
            "parsed_path": record["parsed_path"],
            "status": record["status"],
            "page_count": record.get("page_count", 0),
            "chunk_count": record.get("chunk_count", 0),
            "parse_error": record.get("parse_error"),
            "metadata_json": json.dumps(record.get("metadata", {}), ensure_ascii=False),
            "created_at": record.get("created_at", now),
            "updated_at": now,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    doc_id, file_name, source_path, parsed_path, status,
                    page_count, chunk_count, parse_error, metadata_json,
                    created_at, updated_at
                )
                VALUES (
                    :doc_id, :file_name, :source_path, :parsed_path, :status,
                    :page_count, :chunk_count, :parse_error, :metadata_json,
                    :created_at, :updated_at
                )
                ON CONFLICT(doc_id) DO UPDATE SET
                    file_name = excluded.file_name,
                    source_path = excluded.source_path,
                    parsed_path = excluded.parsed_path,
                    status = excluded.status,
                    page_count = excluded.page_count,
                    chunk_count = excluded.chunk_count,
                    parse_error = excluded.parse_error,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            connection.commit()

    def list_documents(self) -> list[dict[str, Any]]:
        """列出documents。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents ORDER BY datetime(created_at) DESC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """获取文档。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def delete_document(self, doc_id: str) -> None:
        """删除文档。"""
        with self._connect() as connection:
            connection.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            connection.commit()

    def update_document_status(
        self,
        doc_id: str,
        status: str,
        *,
        page_count: int | None = None,
        chunk_count: int | None = None,
        parse_error: str | None = None,
        parsed_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """更新文档状态。"""
        document = self.get_document(doc_id)
        if not document:
            return None

        document["status"] = status
        if page_count is not None:
            document["page_count"] = page_count
        if chunk_count is not None:
            document["chunk_count"] = chunk_count
        if parse_error is not None:
            document["parse_error"] = parse_error
        elif status != "failed":
            document["parse_error"] = None
        if parsed_path is not None:
            document["parsed_path"] = parsed_path
        if metadata is not None:
            merged_metadata = dict(document.get("metadata") or {})
            merged_metadata.update(metadata)
            document["metadata"] = merged_metadata
        self.upsert_document(document)
        return self.get_document(doc_id)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """处理行内容todict。"""
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json", "{}"))
        return data
