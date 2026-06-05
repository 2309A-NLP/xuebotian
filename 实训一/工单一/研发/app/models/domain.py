from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    text: str
    tables: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedDocument:
    doc_id: str
    file_name: str
    file_path: str
    pages: list[ParsedPage]
    cleaned_text: str
    created_at: datetime


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    text: str
    page: int
    chunk_index: int
    source_file: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchHit:
    chunk_id: str
    doc_id: str
    text: str
    page: int
    score: float
    source_file: str
    metadata: dict[str, Any] = field(default_factory=dict)
