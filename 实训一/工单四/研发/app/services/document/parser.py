from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber

try:
    import camelot
except ImportError:  # pragma: no cover - optional parser
    camelot = None

from app.models.domain import ParsedPage, TableBlock
from app.services.document.table_processor import normalize_grid

logger = logging.getLogger(__name__)

_CAPTION_MAX_GAP = 28.0
_REFERENCE_MAX_GAP = 72.0
_REFERENCE_MAX_LINES = 2
_CAPTION_KEYWORDS = (
    "\u8868",
    "Table",
    "TABLE",
    "\u9644\u8868",
    "\u6e05\u5355",
    "\u660e\u7ec6",
)
_UNIT_NOTE_PREFIXES = (
    "\u5355\u4f4d\uff1a",
    "\u5355\u4f4d:",
    "(\u5355\u4f4d\uff1a",
    "\uff08\u5355\u4f4d\uff1a",
)
_HEADER_FOOTER_HINTS = (
    "\u62db\u80a1\u610f\u5411\u4e66",
    "\u62db\u80a1\u8bf4\u660e\u4e66",
    "\u62db\u80a1\u4e66",
    "\u52df\u96c6\u8bf4\u660e\u4e66",
    "\u5e74\u62a5",
    "\u534a\u5e74\u62a5",
    "\u5b63\u62a5",
    "\u516c\u544a",
    "\u4fdd\u8350\u4e66",
)
_HEADER_REGION_MAX_TOP = 90.0
_FOOTER_REGION_MIN_BOTTOM_OFFSET = 50.0

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

_CAMELOT_FLAVORS = ("lattice",)


class PdfParser:
    def parse(self, file_path: Path) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        logger.info("Start parsing PDF: %s", file_path)
        with pdfplumber.open(file_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                tables, table_bboxes = self._extract_tables(file_path, page, index)
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
        self, file_path: Path, page: pdfplumber.page.Page, page_number: int
    ) -> tuple[list[TableBlock], list[tuple[float, float, float, float]]]:
        blocks: list[TableBlock] = []
        bboxes: list[tuple[float, float, float, float]] = []
        pdfplumber_raw_count = 0
        camelot_raw_count = 0
        try:
            found = page.find_tables(table_settings=_TABLE_SETTINGS) or []
            if not found:
                found = page.find_tables() or []
            pdfplumber_raw_count = len(found)
        except Exception:
            logger.exception("Failed to find tables on page %s", page_number)
            found = []

        page_lines = self._extract_page_lines(page)
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
            block.caption = self._detect_caption(page_lines, table.bbox, page.height)
            block.reference_text = self._detect_reference_text(
                page_lines,
                table.bbox,
                block.caption,
                page.height,
            )
            block.bbox = table.bbox
            blocks.append(block)
            bboxes.append(table.bbox)

        camelot_blocks, camelot_bboxes, camelot_raw_count = self._extract_camelot_tables(
            file_path=file_path,
            page=page,
            page_lines=page_lines,
            page_number=page_number,
            existing_bboxes=bboxes,
        )
        blocks.extend(camelot_blocks)
        bboxes.extend(camelot_bboxes)
        blocks.sort(key=lambda block: block.bbox[1] if block.bbox is not None else 0)
        logger.info(
            "Parsed tables page=%s pdfplumber_raw=%s camelot_raw=%s usable=%s excluded_regions=%s file=%s",
            page_number,
            pdfplumber_raw_count,
            camelot_raw_count,
            len(blocks),
            len(bboxes),
            file_path.name,
        )
        return blocks, bboxes

    def _extract_camelot_tables(
        self,
        file_path: Path,
        page: pdfplumber.page.Page,
        page_lines: list[dict[str, Any]],
        page_number: int,
        existing_bboxes: list[tuple[float, float, float, float]],
    ) -> tuple[list[TableBlock], list[tuple[float, float, float, float]], int]:
        if camelot is None:
            return [], [], 0

        blocks: list[TableBlock] = []
        bboxes: list[tuple[float, float, float, float]] = []
        known_bboxes = list(existing_bboxes)
        raw_count = 0
        for flavor in _CAMELOT_FLAVORS:
            try:
                tables = camelot.read_pdf(
                    str(file_path),
                    pages=str(page_number),
                    flavor=flavor,
                    strip_text="\n",
                    suppress_stdout=True,
                )
                raw_count += len(tables)
            except Exception:
                logger.exception(
                    "Camelot failed to parse page=%s flavor=%s file=%s",
                    page_number,
                    flavor,
                    file_path.name,
                )
                continue

            for table in tables:
                bbox = self._camelot_bbox(table, page.height)
                if bbox is None or self._overlaps_existing_table(bbox, known_bboxes):
                    continue
                if not self._camelot_report_is_usable(table):
                    continue
                grid = self._camelot_grid(table)
                block = normalize_grid(grid)
                if block is None:
                    continue
                block.page_start = page_number
                block.page_end = page_number
                block.caption = self._detect_caption(page_lines, bbox, page.height)
                block.reference_text = self._detect_reference_text(
                    page_lines,
                    bbox,
                    block.caption,
                    page.height,
                )
                block.bbox = bbox
                blocks.append(block)
                bboxes.append(bbox)
                known_bboxes.append(bbox)

        return blocks, bboxes, raw_count

    def _camelot_grid(self, table: Any) -> list[list[str | None]]:
        frame = getattr(table, "df", None)
        if frame is None:
            return []
        try:
            values = frame.fillna("").values.tolist()
        except Exception:
            logger.exception("Failed to read Camelot table dataframe")
            return []
        return [
            [str(cell) if cell is not None else "" for cell in row]
            for row in values
        ]

    def _camelot_bbox(
        self, table: Any, page_height: float
    ) -> tuple[float, float, float, float] | None:
        raw_bbox = getattr(table, "_bbox", None) or getattr(table, "bbox", None)
        if raw_bbox is None or len(raw_bbox) != 4:
            return None
        try:
            x0, y0, x1, y1 = [float(value) for value in raw_bbox]
        except (TypeError, ValueError):
            return None

        left = max(min(x0, x1), 0.0)
        right = max(x0, x1)
        top = max(page_height - max(y0, y1), 0.0)
        bottom = min(page_height - min(y0, y1), page_height)
        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)

    def _camelot_report_is_usable(self, table: Any) -> bool:
        report = getattr(table, "parsing_report", {}) or {}
        try:
            accuracy = float(report.get("accuracy", 100) or 0)
        except (TypeError, ValueError):
            accuracy = 100.0
        if accuracy < 50:
            return False

        grid = self._camelot_grid(table)
        populated_rows = [
            row for row in grid
            if sum(1 for cell in row if str(cell).strip()) >= 2
        ]
        return len(populated_rows) >= 2

    def _overlaps_existing_table(
        self,
        bbox: tuple[float, float, float, float],
        existing_bboxes: list[tuple[float, float, float, float]],
    ) -> bool:
        return any(
            self._bbox_overlap_ratio(bbox, existing) >= 0.50
            for existing in existing_bboxes
        )

    def _bbox_overlap_ratio(
        self,
        left_bbox: tuple[float, float, float, float],
        right_bbox: tuple[float, float, float, float],
    ) -> float:
        left_x0, left_top, left_x1, left_bottom = left_bbox
        right_x0, right_top, right_x1, right_bottom = right_bbox
        overlap_width = max(0.0, min(left_x1, right_x1) - max(left_x0, right_x0))
        overlap_height = max(0.0, min(left_bottom, right_bottom) - max(left_top, right_top))
        overlap_area = overlap_width * overlap_height
        if overlap_area <= 0:
            return 0.0
        left_area = max((left_x1 - left_x0) * (left_bottom - left_top), 1.0)
        right_area = max((right_x1 - right_x0) * (right_bottom - right_top), 1.0)
        return overlap_area / min(left_area, right_area)

    def _extract_page_lines(self, page: pdfplumber.page.Page) -> list[dict[str, Any]]:
        try:
            words = page.extract_words(use_text_flow=False) or []
        except Exception:
            return []

        lines: dict[int, list[dict[str, Any]]] = {}
        for word in words:
            lines.setdefault(round(float(word["top"])), []).append(word)

        extracted: list[dict[str, Any]] = []
        for items in lines.values():
            ordered = sorted(items, key=lambda item: item["x0"])
            text = " ".join(str(word["text"]) for word in ordered).strip()
            if not text:
                continue
            extracted.append(
                {
                    "text": text,
                    "x0": min(float(word["x0"]) for word in ordered),
                    "x1": max(float(word["x1"]) for word in ordered),
                    "top": min(float(word["top"]) for word in ordered),
                    "bottom": max(float(word["bottom"]) for word in ordered),
                }
            )
        return sorted(extracted, key=lambda item: (item["top"], item["x0"]))

    def _detect_caption(
        self,
        page_lines: list[dict[str, Any]],
        bbox: tuple[float, float, float, float],
        page_height: float,
    ) -> str:
        """Find the nearest text line above a table as its caption."""
        candidates = [
            line
            for line in self._lines_above_bbox(page_lines, bbox, horizontal_padding=8.0)
            if not self._looks_like_page_header_footer(line, page_height)
        ]
        if not candidates:
            return ""

        nearest = candidates[0]
        gap = bbox[1] - float(nearest["bottom"])
        caption = str(nearest["text"]).strip()
        if not caption:
            return ""

        has_keyword = any(keyword in caption for keyword in _CAPTION_KEYWORDS)
        if gap <= _CAPTION_MAX_GAP or has_keyword:
            return caption
        return ""

    def _detect_reference_text(
        self,
        page_lines: list[dict[str, Any]],
        bbox: tuple[float, float, float, float],
        caption: str,
        page_height: float,
    ) -> str:
        candidates = [
            line
            for line in self._lines_above_bbox(page_lines, bbox, horizontal_padding=24.0)
            if not self._looks_like_page_header_footer(line, page_height)
        ]
        if not candidates:
            return ""

        references: list[str] = []
        seen: set[str] = set()
        anchor_top = float(bbox[1])
        normalized_caption = " ".join(caption.split())
        for line in candidates:
            text = str(line["text"]).strip()
            if not text:
                continue

            normalized = " ".join(text.split())
            if normalized_caption and normalized == normalized_caption:
                anchor_top = min(anchor_top, float(line["top"]))
                continue
            if self._looks_like_caption(text) or self._looks_like_unit_note(text):
                anchor_top = min(anchor_top, float(line["top"]))
                continue

            gap = anchor_top - float(line["bottom"])
            if gap > _REFERENCE_MAX_GAP:
                break
            if normalized in seen:
                continue

            references.append(normalized)
            seen.add(normalized)
            anchor_top = float(line["top"])
            if len(references) >= _REFERENCE_MAX_LINES:
                break

        references.reverse()
        return " ".join(references).strip()

    def _lines_above_bbox(
        self,
        page_lines: list[dict[str, Any]],
        bbox: tuple[float, float, float, float],
        horizontal_padding: float,
    ) -> list[dict[str, Any]]:
        x0, top, x1, _ = bbox
        candidates = [
            line
            for line in page_lines
            if float(line["bottom"]) <= top + 1
            and float(line["x1"]) >= x0 - horizontal_padding
            and float(line["x0"]) <= x1 + horizontal_padding
        ]
        return sorted(candidates, key=lambda item: item["bottom"], reverse=True)

    def _looks_like_caption(self, text: str) -> bool:
        return any(keyword in text for keyword in _CAPTION_KEYWORDS)

    def _looks_like_unit_note(self, text: str) -> bool:
        compact = text.replace(" ", "")
        return compact.startswith(_UNIT_NOTE_PREFIXES)

    def _looks_like_page_header_footer(
        self,
        line: dict[str, Any],
        page_height: float,
    ) -> bool:
        text = str(line.get("text", "")).strip()
        if not text:
            return True

        compact = text.replace(" ", "")
        top = float(line.get("top", 0.0))
        bottom = float(line.get("bottom", 0.0))
        in_header_region = top <= _HEADER_REGION_MAX_TOP
        in_footer_region = bottom >= max(page_height - _FOOTER_REGION_MIN_BOTTOM_OFFSET, 0.0)

        if re.fullmatch(r"(?:\u7b2c)?\d+(?:/\d+)?(?:\u9875)?", compact, flags=re.IGNORECASE):
            return True
        if re.fullmatch(r"Page\d+(?:of\d+)?", compact, flags=re.IGNORECASE):
            return True

        if any(hint in compact for hint in _HEADER_FOOTER_HINTS) and (in_header_region or in_footer_region):
            return True

        if (in_header_region or in_footer_region) and len(compact) <= 40:
            if compact.endswith(("\u4e66", "\u62a5", "\u516c\u544a", "\u8d44\u6599", "\u6587\u4ef6")):
                return True

        return False

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
