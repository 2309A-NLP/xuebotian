from __future__ import annotations

import hashlib
import uuid


def generate_doc_id(file_name: str) -> str:
    digest = hashlib.md5(f"{file_name}-{uuid.uuid4()}".encode("utf-8")).hexdigest()
    return f"doc_{digest[:16]}"


def generate_chunk_id(doc_id: str, chunk_index: int, content: str) -> str:
    digest = hashlib.md5(f"{doc_id}-{chunk_index}-{content}".encode("utf-8")).hexdigest()
    return f"chunk_{digest[:20]}"
