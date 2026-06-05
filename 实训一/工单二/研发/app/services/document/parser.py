from __future__ import annotations

import logging
from pathlib import Path

import pdfplumber

from app.models.domain import ParsedPage

logger = logging.getLogger(__name__)


class PdfParser:
    def parse(self, file_path: Path) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        logger.info("Start parsing PDF: %s", file_path)
        with pdfplumber.open(file_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                tables = self._extract_tables(page)
                pages.append(
                    ParsedPage(
                        page_number=index,
                        text=text,
                        tables=tables,
                    )
                )
        logger.info("Parsed PDF pages=%s file=%s", len(pages), file_path.name)
        return pages

    def _extract_tables(self, page: pdfplumber.page.Page) -> list[str]:
        result: list[str] = []
        try:
            tables = page.extract_tables() or []
            for table in tables:
                rows = []
                for row in table:
                    values = [(cell or "").strip() for cell in row]
                    rows.append(" | ".join(values))
                if rows:
                    result.append("\n".join(rows))
        except Exception:
            logger.exception("Failed to extract tables from page")
        return result
