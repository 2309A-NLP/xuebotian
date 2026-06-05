from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from app.services.document.image_models import _PdfImage


class ImageExtractionMixin:
    def _extract_images(
        self,
        file_path: Path,
        table_bboxes_by_page: dict[int, list[tuple[float, float, float, float]]],
    ) -> list[_PdfImage]:
        images: list[_PdfImage] = []
        seen_xrefs: set[int] = set()
        max_images = max(self.settings.vision_max_images_per_pdf, 0)
        if max_images == 0:
            return images

        with fitz.open(file_path) as document:
            for page_index in range(document.page_count):
                if len(images) >= max_images:
                    return images
                page = document.load_page(page_index)
                page_number = page_index + 1
                page_words = page.get_text("words") or []
                excluded_rects = [
                    fitz.Rect(bbox)
                    for bbox in table_bboxes_by_page.get(page_number, [])
                ]

                for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                    if len(images) >= max_images:
                        return images
                    xref = int(image_info[0])
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    bbox = self._image_bbox(page, xref)
                    if bbox is not None and not self._passes_size_filter(
                        int(bbox.width),
                        int(bbox.height),
                    ):
                        continue
                    base_image = document.extract_image(xref)
                    width = int(base_image.get("width") or 0)
                    height = int(base_image.get("height") or 0)
                    if not self._passes_size_filter(width, height):
                        continue
                    data = base_image.get("image") or b""
                    if not data:
                        continue
                    ext = str(base_image.get("ext") or "png").lower()
                    if bbox is not None and self._overlaps_excluded_region(
                        bbox,
                        excluded_rects,
                        strict=True,
                    ):
                        continue
                    if bbox is not None and self._embedded_image_looks_like_table(
                        page_words,
                        bbox,
                    ):
                        excluded_rects.append(bbox)
                        continue
                    if bbox is not None and self._clip_looks_like_table_grid(page, bbox):
                        excluded_rects.append(bbox)
                        continue
                    if bbox is not None:
                        excluded_rects.append(bbox)
                    caption = self._nearby_caption(page_words, bbox)
                    debug_path = self._save_debug_image(
                        data=data,
                        file_path=file_path,
                        page_number=page_number,
                        image_index=image_index,
                        ext=ext,
                        suffix="image",
                    )
                    images.append(
                        _PdfImage(
                            page_number=page_number,
                            image_index=image_index,
                            width=width,
                            height=height,
                            ext=ext,
                            data=data,
                            caption=caption,
                            kind="image",
                            debug_path=debug_path,
                        )
                    )

                if (
                    self.settings.vision_extract_vector_diagrams
                    and len(images) < max_images
                ):
                    images.extend(
                        self._extract_vector_diagrams(
                            page=page,
                            page_words=page_words,
                            file_path=file_path,
                            page_number=page_number,
                            start_index=len(images) + 1,
                            remaining=max_images - len(images),
                            excluded_rects=excluded_rects,
                        )
                    )
        return images

    def _extract_vector_diagrams(
        self,
        page: fitz.Page,
        page_words: list[Any],
        file_path: Path,
        page_number: int,
        start_index: int,
        remaining: int,
        excluded_rects: list[fitz.Rect],
    ) -> list[_PdfImage]:
        drawings = page.get_drawings() or []
        if len(drawings) < self.settings.vision_min_vector_drawings:
            return []

        page_rect = page.rect
        candidates = self._vector_visual_candidates(
            drawings,
            page_words,
            page_rect,
            excluded_rects,
        )
        if not candidates:
            return []

        matrix = fitz.Matrix(
            self.settings.vision_render_zoom,
            self.settings.vision_render_zoom,
        )
        extracted: list[_PdfImage] = []
        for offset, (clip, kind) in enumerate(candidates[:remaining]):
            pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
            data = pixmap.tobytes("png")
            image_index = start_index + offset
            caption = self._nearby_caption(page_words, clip)
            debug_path = self._save_debug_image(
                data=data,
                file_path=file_path,
                page_number=page_number,
                image_index=image_index,
                ext="png",
                suffix=kind,
            )
            extracted.append(
                _PdfImage(
                    page_number=page_number,
                    image_index=image_index,
                    width=pixmap.width,
                    height=pixmap.height,
                    ext="png",
                    data=data,
                    caption=caption,
                    kind=kind,
                    debug_path=debug_path,
                )
            )
        return extracted

    def _vector_visual_candidates(
        self,
        drawings: list[dict[str, Any]],
        page_words: list[Any],
        page_rect: fitz.Rect,
        excluded_rects: list[fitz.Rect],
    ) -> list[tuple[fitz.Rect, str]]:
        clusters = self._cluster_drawing_rects(drawings, page_rect, excluded_rects)
        candidates: list[tuple[float, fitz.Rect, str]] = []
        for rects in clusters:
            if len(rects) < self.settings.vision_min_vector_drawings:
                continue
            union = self._rects_union(rects) & page_rect
            if not self._passes_size_filter(int(union.width), int(union.height)):
                continue
            if self._overlaps_excluded_region(union, excluded_rects, strict=True):
                continue
            if union.width > page_rect.width * 0.90 and union.height > page_rect.height * 0.65:
                continue
            if self._looks_like_table_region(rects, page_words, union):
                kind = "vector_table"
                score = 1.0
            else:
                kind = "vector_diagram"
                score = self._diagram_score(rects, page_words, union)
                dense_visual_block = (
                    len(rects) >= max(self.settings.vision_min_vector_drawings, 6)
                    and union.get_area() >= 3000
                    and self._word_count_in_rect(page_words, union) <= 100
                )
                if score < 1.0 and not dense_visual_block:
                    continue
            clip = fitz.Rect(
                max(union.x0 - 24, page_rect.x0),
                max(union.y0 - 48, page_rect.y0),
                min(union.x1 + 24, page_rect.x1),
                min(union.y1 + 24, page_rect.y1),
            )
            if self._overlaps_excluded_region(clip, excluded_rects, strict=True):
                continue
            candidates.append((score, clip, kind))
        candidates.sort(key=lambda item: (item[0], item[1].get_area()), reverse=True)
        visual_candidates = [(clip, kind) for _, clip, kind in candidates]
        if visual_candidates:
            return visual_candidates
        fallback = self._page_level_vector_candidate(
            drawings,
            page_words,
            page_rect,
            excluded_rects,
        )
        return [fallback] if fallback is not None else []

    def _page_level_vector_candidate(
        self,
        drawings: list[dict[str, Any]],
        page_words: list[Any],
        page_rect: fitz.Rect,
        excluded_rects: list[fitz.Rect],
    ) -> tuple[fitz.Rect, str] | None:
        rects: list[fitz.Rect] = []
        for drawing in drawings:
            raw_rect = drawing.get("rect")
            if raw_rect is None:
                continue
            rect = fitz.Rect(raw_rect) & page_rect
            if rect.is_empty or rect.get_area() < 4:
                continue
            if self._overlaps_excluded_region(rect, excluded_rects, strict=False):
                continue
            rects.append(rect)
        if len(rects) < max(self.settings.vision_min_vector_drawings, 6):
            return None
        union = self._rects_union(rects) & page_rect
        if not self._passes_size_filter(int(union.width), int(union.height)):
            return None
        if union.width > page_rect.width * 0.92 and union.height > page_rect.height * 0.72:
            return None
        is_table = self._looks_like_table_region(rects, page_words, union)
        word_count = self._word_count_in_rect(page_words, union)
        if word_count > 180:
            return None
        if not is_table and self._diagram_score(rects, page_words, union) < 1.0:
            return None
        clip = fitz.Rect(
            max(union.x0 - 24, page_rect.x0),
            max(union.y0 - 48, page_rect.y0),
            min(union.x1 + 24, page_rect.x1),
            min(union.y1 + 24, page_rect.y1),
        )
        if self._overlaps_excluded_region(clip, excluded_rects, strict=True):
            return None
        return (clip, "vector_table" if is_table else "vector_diagram")

    def _overlaps_excluded_region(
        self,
        rect: fitz.Rect,
        excluded_rects: list[fitz.Rect],
        strict: bool = False,
    ) -> bool:
        rect_area = max(rect.get_area(), 1.0)
        for excluded in excluded_rects:
            overlap = rect & excluded
            if overlap.is_empty:
                continue
            overlap_area = overlap.get_area()
            excluded_area = max(excluded.get_area(), 1.0)
            if strict:
                if overlap_area / rect_area >= 0.03 or overlap_area / excluded_area >= 0.10:
                    return True
                continue
            if overlap_area / rect_area >= 0.12 or overlap_area / excluded_area >= 0.50:
                return True
        return False

    def _cluster_drawing_rects(
        self,
        drawings: list[dict[str, Any]],
        page_rect: fitz.Rect,
        excluded_rects: list[fitz.Rect],
    ) -> list[list[fitz.Rect]]:
        rects: list[fitz.Rect] = []
        for drawing in drawings:
            rect = drawing.get("rect")
            if rect is None:
                continue
            current = fitz.Rect(rect) & page_rect
            if current.is_empty or current.get_area() < 4:
                continue
            if self._overlaps_excluded_region(current, excluded_rects, strict=False):
                continue
            rects.append(current)

        clusters: list[list[fitz.Rect]] = []
        for rect in rects:
            placed = False
            padding = max(36.0, min(rect.width, rect.height) * 0.8)
            expanded = fitz.Rect(
                rect.x0 - padding,
                rect.y0 - padding,
                rect.x1 + padding,
                rect.y1 + padding,
            )
            for cluster in clusters:
                union = self._rects_union(cluster)
                cluster_padding = 36.0
                expanded_union = fitz.Rect(
                    union.x0 - cluster_padding,
                    union.y0 - cluster_padding,
                    union.x1 + cluster_padding,
                    union.y1 + cluster_padding,
                )
                if expanded.intersects(expanded_union):
                    cluster.append(rect)
                    placed = True
                    break
            if not placed:
                clusters.append([rect])
        return clusters
