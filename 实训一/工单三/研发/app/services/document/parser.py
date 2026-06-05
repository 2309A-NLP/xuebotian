from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pdfplumber

from app.models.domain import ParsedPage, TableBlock
from app.services.document.table_processor import normalize_grid

logger = logging.getLogger(__name__)

_CAPTION_MAX_GAP = 28.0
_CAPTION_KEYWORDS = ("表", "Table", "TABLE", "附表", "清单", "明细")

_TABLE_SETTINGS: dict[str, Any] = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "intersection_tolerance": 5,
    "edge_min_length": 8,
    "min_words_vertical": 2,
    "min_words_horizontal": 1,
}


class PdfParser:
    def parse(self, file_path: Path) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        logger.info("Start parsing PDF: %s", file_path)
        with pdfplumber.open(file_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                tables, table_bboxes = self._extract_tables(page, index)
                text = self._extract_body_text(page, table_bboxes)
                pages.append(
                    ParsedPage(
                        page_number=index,
                        text=text,
                        tables=tables,
                    )
                )
        logger.info("Parsed PDF pages=%s file=%s", len(pages), file_path.name)
        return pages

    def _extract_tables(
        self, page: pdfplumber.page.Page, page_number: int
    ) -> tuple[list[TableBlock], list[tuple[float, float, float, float]]]:
        blocks: list[TableBlock] = []
        bboxes: list[tuple[float, float, float, float]] = []
        try:
            found = page.find_tables(table_settings=_TABLE_SETTINGS) or []
            if not found:
                found = page.find_tables() or []
        except Exception:
            logger.exception("Failed to find tables on page %s", page_number)
            return blocks, bboxes

        found = sorted(found, key=lambda item: item.bbox[1])
        for table in found:
            try:
                grid = table.extract()
            except Exception:
                logger.exception("Failed to extract a table on page %s", page_number)
                continue
            block = normalize_grid(grid)
            if block is None:
                continue
            block.page_start = page_number
            block.page_end = page_number
            block.caption = self._detect_caption(page, table.bbox)
            blocks.append(block)
            bboxes.append(table.bbox)
        return blocks, bboxes

    def _detect_caption(
        self, page: pdfplumber.page.Page, bbox: tuple[float, float, float, float]
    ) -> str:
        """Find the nearest text line above a table as its caption."""
        x0, top, x1, _ = bbox
        try:
            words = page.extract_words(use_text_flow=False) or []
        except Exception:
            return ""

        lines: dict[int, list[dict]] = {}
        for word in words:
            is_above = word["bottom"] <= top + 1
            overlaps_table = word["x1"] >= x0 - 8 and word["x0"] <= x1 + 8
            if is_above and overlaps_table:
                lines.setdefault(round(word["top"]), []).append(word)
        if not lines:
            return ""

        nearest_key = max(lines)
        gap = top - nearest_key
        line_words = sorted(lines[nearest_key], key=lambda item: item["x0"])
        caption = " ".join(word["text"] for word in line_words).strip()
        if not caption:
            return ""

        has_keyword = any(keyword in caption for keyword in _CAPTION_KEYWORDS)
        if gap <= _CAPTION_MAX_GAP or has_keyword:
            return caption
        return ""

    def _extract_body_text(
        self,
        page: pdfplumber.page.Page,
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> str:
        """Extract page text with table regions removed to avoid duplication."""
        if not table_bboxes:
            return page.extract_text() or ""

        def outside_tables(obj: dict) -> bool:
            cx = (obj["x0"] + obj["x1"]) / 2
            cy = (obj["top"] + obj["bottom"]) / 2
            for x0, top, x1, bottom in table_bboxes:
                if x0 <= cx <= x1 and top <= cy <= bottom:
                    return False
            return True

        try:
            filtered = page.filter(outside_tables)
            return filtered.extract_text() or ""
        except Exception:
            logger.exception("Failed to filter table regions on page %s", page.page_number)
            return page.extract_text() or ""
