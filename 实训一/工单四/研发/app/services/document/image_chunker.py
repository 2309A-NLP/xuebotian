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

        metadata = self._image_metadata(image, image_index, document_title)
        prefix = self._image_text_prefix(image, image_index)
        text = f"{prefix}{description}"
        if len(text) <= self.chunk_size:
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
            return

        for piece_index, piece in enumerate(self._hard_split(prefix, description), start=1):
            chunks.append(
                self._make_chunk(
                    doc_id=doc_id,
                    file_name=file_name,
                    text=piece,
                    page_start=image.page_number,
                    page_end=image.page_number,
                    kind="image",
                    counter=counter,
                    extra_metadata={**metadata, "image_piece": piece_index},
                )
            )

    def _image_metadata(
        self,
        image: ImageDescription,
        image_index: int,
        document_title: str = "",
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "image_index": image_index,
            "page_image_index": image.image_index,
            "image_kind": image.kind,
            "image_caption": image.caption,
            "image_width": image.width,
            "image_height": image.height,
        }
        if image.debug_path:
            metadata["image_debug_path"] = image.debug_path
        if document_title:
            metadata["document_title"] = document_title
        return metadata

    def _image_text_prefix(self, image: ImageDescription, image_index: int) -> str:
        lines = [
            f"图片 {image_index}",
            f"页码：{image.page_number}",
            f"类型：{image.kind}",
            f"尺寸：{image.width}x{image.height}",
        ]
        caption = normalize_whitespace(image.caption)
        if caption:
            lines.append(f"标题：{caption}")
        lines.append("描述：")
        return "\n".join(lines) + " "
