from __future__ import annotations

import re
from collections import Counter

from app.utils.text import dedupe_lines, normalize_whitespace


class TextCleaner:
    def __init__(self, watermark_patterns: list[str]) -> None:
        self.watermark_patterns = watermark_patterns

    def clean_pages(self, pages_text: list[str]) -> str:
        cleaned_pages = self.clean_page_texts(pages_text)
        merged = "\n\n".join(text for text in cleaned_pages if text)
        merged = dedupe_lines(merged)
        return normalize_whitespace(merged)

    def clean_page_texts(self, pages_text: list[str]) -> list[str]:
        boilerplate = self._detect_boilerplate_lines(pages_text)
        cleaned_pages: list[str] = []
        for text in pages_text:
            cleaned = self.clean_text(text)
            if boilerplate:
                lines = [
                    line
                    for line in cleaned.splitlines()
                    if self._line_key(line) not in boilerplate
                ]
                cleaned = "\n".join(lines)
            cleaned_pages.append(normalize_whitespace(cleaned))
        return cleaned_pages

    def clean_text(self, text: str) -> str:
        text = self._remove_noise(text)
        text = self._collapse_broken_lines(text)
        return normalize_whitespace(text)

    def clean_cell(self, value: str) -> str:
        """Clean a single table cell: strip noise and collapse internal whitespace."""
        cleaned = self._remove_noise(value)
        return normalize_whitespace(cleaned.replace("\n", " "))

    def _remove_noise(self, text: str) -> str:
        for pattern in self.watermark_patterns:
            if pattern:
                text = text.replace(pattern, " ")
        text = re.sub(r"第\s*\d+\s*页(\s*/?\s*共?\s*\d*\s*页?)?", " ", text)
        text = re.sub(r"Page\s*\d+\s*(of\s*\d+)?", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b\d+\s*/\s*\d+\b", " ", text)
        return text

    def _detect_boilerplate_lines(self, pages_text: list[str]) -> set[str]:
        counter: Counter[str] = Counter()
        for text in pages_text:
            seen_on_page: set[str] = set()
            for raw_line in text.splitlines():
                key = self._line_key(raw_line)
                if key:
                    seen_on_page.add(key)
            counter.update(seen_on_page)

        page_count = max(len(pages_text), 1)
        threshold = max(5, int(page_count * 0.08))
        return {
            line
            for line, count in counter.items()
            if count >= threshold and self._looks_like_boilerplate(line)
        }

    def _line_key(self, line: str) -> str:
        line = self._remove_noise(line)
        line = normalize_whitespace(line)
        line = re.sub(r"\s+", "", line)
        return line.strip()

    def _looks_like_boilerplate(self, line: str) -> bool:
        if len(line) < 6 or len(line) > 60:
            return False
        if re.fullmatch(r"\d+", line):
            return True
        if any(keyword in line for keyword in ["招股意向书", "招股说明书", "保荐书"]):
            return True
        return False

    def _collapse_broken_lines(self, text: str) -> str:
        lines = [normalize_whitespace(line) for line in text.splitlines()]
        merged: list[str] = []
        for line in lines:
            if not line:
                if merged and merged[-1] != "":
                    merged.append("")
                continue
            if not merged or merged[-1] == "":
                merged.append(line)
                continue
            if self._should_join(merged[-1], line):
                merged[-1] = self._join_lines(merged[-1], line)
            else:
                merged.append(line)
        return "\n".join(part for part in merged if part != "")

    def _should_join(self, previous: str, current: str) -> bool:
        if len(previous) <= 2 or len(current) <= 2:
            return False
        if self._looks_like_heading(previous) or self._looks_like_heading(current):
            return False
        if previous.endswith(("：", ":", "；", ";")):
            return False
        if current.startswith(("注：", "说明：", "其中：", "单位：")):
            return False
        if re.match(r"^\d+(\.\d+)*[、.．)]", current):
            return False
        if re.match(r"^[（(]?[一二三四五六七八九十0-9]+[）)]", current):
            return False
        if re.match(r"^(第[一二三四五六七八九十0-9]+[章节部分])", current):
            return False
        if re.search(r"[。！？.!?]$", previous):
            return False
        return True

    def _join_lines(self, previous: str, current: str) -> str:
        if not previous:
            return current
        if not current:
            return previous

        previous_last = previous[-1]
        current_first = current[0]

        if self._is_cjk(previous_last) and self._is_cjk(current_first):
            separator = ""
        elif previous_last in "（([" or current_first in "）)]，。；：！？、,.!?;:":
            separator = ""
        else:
            separator = " "
        return f"{previous}{separator}{current}"

    def _is_cjk(self, char: str) -> bool:
        return "一" <= char <= "鿿"

    def _looks_like_heading(self, text: str) -> bool:
        compact = text.strip()
        if not compact or len(compact) > 30:
            return False
        if re.match(r"^[一二三四五六七八九十]+[、.]?", compact):
            return True
        if re.match(r"^[（(][一二三四五六七八九十0-9]+[）)]", compact):
            return True
        if re.match(r"^第[一二三四五六七八九十0-9]+[章节部分]$", compact):
            return True
        if re.match(r"^[一-鿿A-Za-z0-9《》“”()（）-]+$", compact):
            return True
        return False
