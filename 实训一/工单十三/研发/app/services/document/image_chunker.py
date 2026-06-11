from __future__ import annotations

from typing import Any

from app.models.domain import ChunkRecord
from app.services.document.chunk_models import _Counter
from app.services.document.image_models import ImageDescription
from app.utils.text import normalize_whitespace


class ImageChunkMixin:
    """负责把图片描述结果转成可检索的图片切片。

    图片本身不会直接进入向量库，真正入库的是视觉模型生成的描述文本，
    再配合标题、类型和页码等元数据作为后续召回依据。
    """
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
        """把单张图片描述包装成一个图片类切片并追加到结果列表。

        只有当描述文本足够长、具备检索价值时才会入库，
        这样可以过滤掉空描述或信息量过低的图片。
        """
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
        """整理图片切片需要携带的元数据。

        这些字段既会进入解析产物，也会参与后续检索排序和前端引用展示。
        """
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
        """为图片描述补上一段结构化前缀文本。

        前缀会显式写出图片类型、标题以及“视觉描述”标签，
        让向量检索和关键词检索都更容易利用这些上下文。
        """
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
        """把内部图片类型编码转换为更适合展示和检索的中文标签。"""
        normalized = normalize_whitespace(kind).lower()
        if normalized == "chart":
            return "图表"
        if normalized == "image":
            return "图片"
        return normalized
