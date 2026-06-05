from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings


class FileStore:
    def __init__(self, settings: Settings) -> None:
        self.upload_dir = settings.upload_dir
        self.parsed_dir = settings.parsed_dir

    def save_upload(self, doc_id: str, upload: UploadFile) -> Path:
        suffix = Path(upload.filename or "upload.pdf").suffix or ".pdf"
        target = self.upload_dir / f"{doc_id}{suffix}"
        with target.open("wb") as file_obj:
            shutil.copyfileobj(upload.file, file_obj)
        return target

    def save_parsed_document(self, doc_id: str, payload: dict) -> Path:
        target = self.parsed_dir / f"{doc_id}.json"
        payload["saved_at"] = datetime.now().isoformat()
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def delete_file(self, path: str | Path) -> None:
        target = Path(path)
        if target.exists():
            target.unlink()
