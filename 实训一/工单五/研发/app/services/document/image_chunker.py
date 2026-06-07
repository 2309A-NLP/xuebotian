from __future__ import annotations

from typing import Any

from app.models.domain import ChunkRecord
from app.services.document.chunk_models import _Counter
from app.services.document.image_models import ImageDescription
from app.utils.text import normalize_whitespace


class ImageChunkMixin:
    def _chunk_image(
        self,
        doc_id: str,
        file_name: str,
        image: ImageDescription,
        image_index: int,
        chunks: list[ChunkRecord],
        counter: _Counter,
        document_title: str = "",
    ) -> None:
        description = normalize_whitespace(image.description)
        if not description or len(self._content_signature(description)) < 24:
            return

        metadata = self._image_metadata(image, document_title)
        prefix = self._image_text_prefix(image)
        text = f"{prefix}{description}"
        chunks.append(
            self._make_chunk(
                doc_id=doc_id,
                file_name=file_name,
                text=text,
                page_start=image.page_number,
                page_end=image.page_number,
                kind="image",
                counter=counter,
                extra_metadata=metadata,
            )
        )

    def _image_metadata(
        self,
        image: ImageDescription,
        document_title: str = "",
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "image_caption": image.caption,
            "image_lead_text": image.lead_text,
            "image_kind": self._image_kind_label(image.kind),
            "image_width": image.width,
            "image_height": image.height,
        }
        if document_title:
            metadata["document_title"] = document_title
        return metadata

    def _image_text_prefix(self, image: ImageDescription) -> str:
        lines: list[str] = []
        kind_label = self._image_kind_label(image.kind)
        if kind_label:
            lines.append(f"类型：{kind_label}")
        caption = normalize_whitespace(image.caption)
        if caption:
            lines.append(f"标题：{caption}")
        lines.append("视觉描述：")
        return "\n".join(lines) + " "

    def _image_kind_label(self, kind: str) -> str:
        normalized = normalize_whitespace(kind).lower()
        if normalized == "chart":
            return "图表"
        if normalized == "image":
            return "图片"
        return normalized
