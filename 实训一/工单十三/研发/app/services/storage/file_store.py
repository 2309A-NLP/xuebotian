from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings


class FileStore:
    """负责上传文件、解析产物的落盘与清理。"""
    def __init__(self, settings: Settings) -> None:
        """初始化文件存储服务所需的依赖和运行参数。"""
        self.upload_dir = settings.upload_dir
        self.parsed_dir = settings.parsed_dir

    def save_upload(self, doc_id: str, upload: UploadFile) -> Path:
        """保存上传文件。"""
        suffix = Path(upload.filename or "upload.pdf").suffix or ".pdf"
        target = self.upload_dir / f"{doc_id}{suffix}"
        with target.open("wb") as file_obj:
            shutil.copyfileobj(upload.file, file_obj)
        return target

    def save_parsed_document(self, doc_id: str, payload: dict) -> Path:
        """保存parsed文档。"""
        target = self.parsed_dir / f"{doc_id}.json"
        payload["saved_at"] = datetime.now().isoformat()
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def delete_file(self, path: str | Path) -> None:
        """删除文件。"""
        target = Path(path)
        if target.exists():
            target.unlink()

    def delete_tree(self, path: str | Path) -> None:
        """删除tree。"""
        target = Path(path)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
