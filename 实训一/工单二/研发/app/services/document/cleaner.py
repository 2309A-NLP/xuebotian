from __future__ import annotations

import re

from app.utils.text import dedupe_lines, normalize_whitespace


class TextCleaner:
    def __init__(self, watermark_patterns: list[str]) -> None:
        self.watermark_patterns = watermark_patterns

    def clean_pages(self, pages_text: list[str]) -> str:
        cleaned_pages = [self.clean_text(text) for text in pages_text]
        merged = "\n\n".join(text for text in cleaned_pages if text)
        merged = dedupe_lines(merged)
        return normalize_whitespace(merged)

    def clean_text(self, text: str) -> str:
        for pattern in self.watermark_patterns:
            text = text.replace(pattern, " ")
        text = re.sub(r"第\s*\d+\s*页", " ", text)
        text = re.sub(r"Page\s*\d+", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
        return normalize_whitespace(text)
