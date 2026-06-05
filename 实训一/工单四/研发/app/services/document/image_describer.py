from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from app.services.document.image_models import ImageDescription, _PdfImage


class ImageDescriptionMixin:
    def _describe_one(self, image: _PdfImage) -> ImageDescription:
        caption_text = f"附近标题：{image.caption}\n" if image.caption else ""
        if image.kind == "vector_table":
            prompt = (
                f"这是 PDF 第 {image.page_number} 页中未被结构化解析器识别的矢量表格截图。\n"
                f"{caption_text}"
                "请只提取表格中的可见文字和结构，不要补充截图中没有的信息。"
                "请优先以文字的形式描述清楚，方便知识块的存储；如果表头或单元格无法可靠识别，请用简洁中文说明无法识别的部分。不要加入对水印的描述。"
                "保留数字、单位、百分号、日期和专有名词。"
            )
        else:
            kind_text = "矢量图、流程图或结构图" if image.kind == "vector_diagram" else "PDF 内嵌图片"
            prompt = (
                f"这是 PDF 第 {image.page_number} 页中的{kind_text}。\n"
                f"{caption_text}"
                "请用中文客观描述图片中的关键信息。"
                "如果是流程图、架构图、关系图或示意图，请说明主要节点、连接关系和方向。"
                "如果是普通图片，请描述主体、关键文字、数字、标签和结论、主题信息等。"
                "不要编造图片中不存在的内容。不要加入对水印的描述。"
            )
        description = self.llm_client.describe_image(
            image_bytes=image.data,
            mime_type=self._mime_type(image.ext),
            prompt=prompt,
        ).strip()
        return ImageDescription(
            page_number=image.page_number,
            image_index=image.image_index,
            width=image.width,
            height=image.height,
            description=description,
            caption=image.caption,
            kind=image.kind,
            debug_path=image.debug_path,
        )

    def _image_bbox(self, page: fitz.Page, xref: int) -> fitz.Rect | None:
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            return None
        return rects[0] if rects else None

    def _rects_union(self, rects: list[fitz.Rect]) -> fitz.Rect:
        union = fitz.Rect(rects[0])
        for rect in rects[1:]:
            union |= rect
        return union

    def _looks_like_table_region(
        self,
        rects: list[fitz.Rect],
        words: list[Any],
        union: fitz.Rect,
    ) -> bool:
        thin_lines = [
            rect for rect in rects
            if rect.width <= 2 or rect.height <= 2
        ]
        thin_ratio = len(thin_lines) / max(len(rects), 1)
        word_count = self._word_count_in_rect(words, union)
        horizontal_lines = [rect for rect in thin_lines if rect.width > rect.height * 8]
        vertical_lines = [rect for rect in thin_lines if rect.height > rect.width * 8]
        grid_like = len(horizontal_lines) >= 4 and len(vertical_lines) >= 4
        text_dense = word_count >= max(len(rects) * 1.2, 24)
        tabular_text = self._looks_like_tabular_text(words, union)
        large_text_block = (
            union.width >= 420
            and union.height >= 360
            and word_count >= 80
            and not self._has_diagram_keywords(words, union)
        )
        return (
            grid_like
            and (thin_ratio > 0.50 or text_dense or tabular_text)
        ) or (tabular_text and text_dense) or large_text_block

    def _diagram_score(
        self,
        rects: list[fitz.Rect],
        words: list[Any],
        union: fitz.Rect,
    ) -> float:
        text = self._text_in_rect(words, union)
        score = 0.0
        if self._looks_like_caption(text):
            score += 2.0
        diagram_terms = (
            "流程", "架构", "关系", "结构", "模块", "系统", "平台", "节点",
            "输入", "输出", "处理", "控制", "管理", "Figure", "FIGURE",
        )
        if any(term in text for term in diagram_terms):
            score += 2.0
        square_like = [
            rect for rect in rects
            if rect.width >= 18 and rect.height >= 12 and 0.2 <= rect.width / max(rect.height, 1) <= 5
        ]
        long_connectors = [
            rect for rect in rects
            if (rect.width > rect.height * 6 and rect.width >= 24)
            or (rect.height > rect.width * 6 and rect.height >= 24)
        ]
        if len(square_like) >= 2 and len(long_connectors) >= 1:
            score += 2.0
        elif len(square_like) >= 3:
            score += 1.0
        elif len(long_connectors) >= 3:
            score += 1.0
        if len(rects) >= self.settings.vision_min_vector_drawings * 2:
            score += 1.0
        word_count = self._word_count_in_rect(words, union)
        if word_count > 120:
            score -= 2.0
        return score

    def _looks_like_tabular_text(self, words: list[Any], rect: fitz.Rect) -> bool:
        inside = self._words_in_rect(words, rect)
        if len(inside) < 24:
            return False
        row_bins: dict[int, int] = {}
        col_bins: dict[int, int] = {}
        for word in inside:
            center_x = (float(word[0]) + float(word[2])) / 2
            center_y = (float(word[1]) + float(word[3])) / 2
            row_bins[round(center_y / 8)] = row_bins.get(round(center_y / 8), 0) + 1
            col_bins[round(center_x / 18)] = col_bins.get(round(center_x / 18), 0) + 1
        dense_rows = sum(1 for count in row_bins.values() if count >= 3)
        dense_cols = sum(1 for count in col_bins.values() if count >= 3)
        return dense_rows >= 5 and dense_cols >= 3

    def _embedded_image_looks_like_table(self, words: list[Any], rect: fitz.Rect) -> bool:
        word_count = self._word_count_in_rect(words, rect)
        if word_count >= 24 and self._looks_like_tabular_text(words, rect):
            return True
        if rect.width >= 360 and rect.height >= 180 and word_count >= 60:
            return not self._has_diagram_keywords(words, rect)
        return False

    def _clip_looks_like_table_grid(self, page: fitz.Page, rect: fitz.Rect) -> bool:
        if rect.width < 120 or rect.height < 80:
            return False
        area = max(rect.width * rect.height, 1.0)
        zoom = min(1.0, (1_200_000 / area) ** 0.5)
        try:
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(zoom, zoom),
                clip=rect,
                alpha=False,
            )
        except Exception:
            logger.exception("Failed to render image clip for table-grid detection")
            return False

        width = pixmap.width
        height = pixmap.height
        channels = pixmap.n
        if width < 80 or height < 60 or channels < 3:
            return False

        samples = pixmap.samples
        row_dark_counts = [0] * height
        col_dark_counts = [0] * width
        for y in range(height):
            row_offset = y * width * channels
            for x in range(width):
                offset = row_offset + x * channels
                red = samples[offset]
                green = samples[offset + 1]
                blue = samples[offset + 2]
                if red + green + blue <= 270:
                    row_dark_counts[y] += 1
                    col_dark_counts[x] += 1

        horizontal_lines = self._count_dense_runs(row_dark_counts, width * 0.45)
        vertical_lines = self._count_dense_runs(col_dark_counts, height * 0.35)
        return horizontal_lines >= 3 and vertical_lines >= 3

    def _count_dense_runs(self, counts: list[int], threshold: float) -> int:
        runs = 0
        in_run = False
        for count in counts:
            if count >= threshold:
                if not in_run:
                    runs += 1
                    in_run = True
            else:
                in_run = False
        return runs

    def _has_diagram_keywords(self, words: list[Any], rect: fitz.Rect) -> bool:
        text = self._text_in_rect(words, rect)
        terms = (
            "流程", "架构", "关系", "结构", "模块", "系统", "平台", "节点",
            "输入", "输出", "处理", "控制", "Figure", "FIGURE",
        )
        return any(term in text for term in terms)

    def _word_count_in_rect(self, words: list[Any], rect: fitz.Rect) -> int:
        return len(self._words_in_rect(words, rect))

    def _text_in_rect(self, words: list[Any], rect: fitz.Rect) -> str:
        return " ".join(str(word[4]) for word in self._words_in_rect(words, rect))

    def _words_in_rect(self, words: list[Any], rect: fitz.Rect) -> list[Any]:
        inside: list[Any] = []
        for word in words:
            if len(word) < 5:
                continue
            center_x = (float(word[0]) + float(word[2])) / 2
            center_y = (float(word[1]) + float(word[3])) / 2
            if rect.x0 <= center_x <= rect.x1 and rect.y0 <= center_y <= rect.y1:
                inside.append(word)
        return inside

    def _nearby_caption(self, words: list[Any], bbox: fitz.Rect | None) -> str:
        if bbox is None:
            return ""
        candidates: list[tuple[float, str]] = []
        for line in self._word_lines(words):
            line_rect = line["rect"]
            horizontal_overlap = min(line_rect.x1, bbox.x1) - max(line_rect.x0, bbox.x0)
            if horizontal_overlap <= 0:
                continue
            overlap_ratio = horizontal_overlap / max(min(line_rect.width, bbox.width), 1)
            above_gap = bbox.y0 - line_rect.y1
            below_gap = line_rect.y0 - bbox.y1
            text = line["text"].strip()
            if not text:
                continue
            if 0 <= above_gap <= 90 and overlap_ratio >= 0.25:
                candidates.append((above_gap, text))
            elif 0 <= below_gap <= 48 and overlap_ratio >= 0.4 and self._looks_like_caption(text):
                candidates.append((below_gap + 100, text))
        if not candidates:
            return ""
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1][:300]

    def _word_lines(self, words: list[Any]) -> list[dict[str, Any]]:
        lines: dict[tuple[int, int], list[Any]] = {}
        for word in words:
            if len(word) < 7:
                continue
            lines.setdefault((int(word[5]), int(word[6])), []).append(word)

        result: list[dict[str, Any]] = []
        for items in lines.values():
            items = sorted(items, key=lambda item: item[0])
            rect = fitz.Rect(
                min(float(item[0]) for item in items),
                min(float(item[1]) for item in items),
                max(float(item[2]) for item in items),
                max(float(item[3]) for item in items),
            )
            result.append(
                {
                    "text": " ".join(str(item[4]) for item in items),
                    "rect": rect,
                }
            )
        return sorted(result, key=lambda item: (item["rect"].y0, item["rect"].x0))

    def _looks_like_caption(self, text: str) -> bool:
        return any(
            token in text
            for token in ("图", "流程", "关系", "架构", "结构", "Figure", "FIGURE")
        )

    def _passes_size_filter(self, width: int, height: int) -> bool:
        return (
            width >= self.settings.vision_min_image_width
            and height >= self.settings.vision_min_image_height
        )

    def _save_debug_image(
        self,
        data: bytes,
        file_path: Path,
        page_number: int,
        image_index: int,
        ext: str,
        suffix: str,
    ) -> str:
        if not self.settings.vision_debug_save_images:
            return ""
        safe_stem = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_"
            for char in file_path.stem
        )
        normalized_ext = ext.lower().lstrip(".") or "png"
        output_dir = self.settings.vision_debug_dir / safe_stem
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"page_{page_number:04d}_{suffix}_{image_index:03d}.{normalized_ext}"
        output_path.write_bytes(data)
        return str(output_path)

    def _mime_type(self, ext: str) -> str:
        normalized = ext.lower().lstrip(".")
        if normalized in {"jpg", "jpeg"}:
            return "image/jpeg"
        if normalized == "webp":
            return "image/webp"
        return "image/png"
