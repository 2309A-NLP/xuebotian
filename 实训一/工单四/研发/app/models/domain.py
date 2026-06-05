from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class TableBlock:
    """A structured table, possibly spanning multiple pages.

    ``header`` is the first row (column names); ``rows`` are the data rows.
    ``caption`` is the title line detected above the table, if any.
    ``reference_text`` is the nearby non-caption text that explains the table context.
    """

    page_start: int
    page_end: int
    header: list[str]
    rows: list[list[str]]
    caption: str = ""
    reference_text: str = ""
    bbox: tuple[float, float, float, float] | None = None

    @property
    def column_count(self) -> int:
        return len(self.header)


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    text: str
    tables: list[TableBlock] = field(default_factory=list)


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
    bm25_text: str
    page: int
    chunk_index: int
    source_file: str
    page_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.page_end < self.page:
            self.page_end = self.page


@dataclass(slots=True)
class SearchHit:
    chunk_id: str
    doc_id: str
    text: str
    page: int
    score: float
    source_file: str
    page_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.page_end < self.page:
            self.page_end = self.page
