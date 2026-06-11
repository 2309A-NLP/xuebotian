from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import posixpath
import re
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from app.core.config import Settings
from app.services.document.image_describer import ImageDescription, ImageDescriptionMixin
from app.services.document.image_models import _PdfImage
from app.services.llm.client import OpenAICompatibleLLMClient
from app.utils.text import normalize_whitespace

logger = logging.getLogger(__name__)

_MD_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)")


class PdfImageDescriber(ImageDescriptionMixin):
    """负责读取 MinerU 图片产物并批量生成图片描述。"""
    def __init__(
        self,
        settings: Settings,
        llm_client: OpenAICompatibleLLMClient,
    ) -> None:
        """初始化图片描述器所需的依赖和运行参数。"""
        self.settings = settings
        self.llm_client = llm_client

    def describe_mineru_md_images(
        self,
        file_path: Path,
        manifest_path: Path,
    ) -> dict[int, list[ImageDescription]]:
        """生成minerumd图片集合的描述信息。"""
        if not self.settings.vision_enabled or not manifest_path.exists():
            return {}

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read MinerU manifest for md-linked images: %s", manifest_path)
            return {}

        images: list[_PdfImage] = []
        for part in manifest.get("parts") or []:
            try:
                images.extend(self._load_mineru_md_part_images(file_path, part))
            except Exception:
                logger.exception(
                    "Failed to prepare MinerU md-linked images for part=%s manifest=%s",
                    part.get("part_index"),
                    manifest_path,
                )

        descriptions = self._describe_images(file_path, images)
        by_page: dict[int, list[ImageDescription]] = {}
        for description in sorted(descriptions, key=lambda item: (item.page_number, item.image_index)):
            by_page.setdefault(description.page_number, []).append(description)
        max_workers = self._vision_worker_count(len(images))
        logger.info(
            "Described MinerU md-linked images file=%s prepared=%s described=%s max_workers=%s",
            file_path.name,
            len(images),
            len(descriptions),
            max_workers,
        )
        return by_page

    def _load_mineru_md_part_images(
        self,
        file_path: Path,
        part: dict[str, Any],
    ) -> list[_PdfImage]:
        """加载minerumd分片文件图片集合。"""
        zip_path = Path(str(part.get("zip_path") or ""))
        flattened_path = Path(str(part.get("flattened_content_list_path") or ""))
        if not zip_path.exists() or not flattened_path.exists():
            return []

        page_range = part.get("page_range") or [1, 1]
        page_start = int(page_range[0]) if page_range else 1
        block_map = self._mineru_image_block_map(flattened_path, page_start)
        if not block_map:
            return []

        images: list[_PdfImage] = []
        with ZipFile(zip_path) as archive:
            markdown_name = self._find_markdown_member(archive)
            if markdown_name is None:
                return []
            markdown = archive.read(markdown_name).decode("utf-8", errors="ignore")
            entries = self._extract_md_image_entries(markdown, markdown_name, block_map)
            archive_members = set(archive.namelist())
            for image_index, entry in enumerate(entries, start=1):
                archive_name = entry["archive_name"]
                if archive_name not in archive_members:
                    continue
                image_bytes = archive.read(archive_name)
                ext = Path(archive_name).suffix.lower().lstrip(".") or "jpg"
                width = int(entry.get("width") or 0)
                height = int(entry.get("height") or 0)
                debug_path = self._save_debug_image(
                    data=image_bytes,
                    file_path=file_path,
                    page_number=int(entry["page_number"]),
                    image_index=image_index,
                    ext=ext,
                    suffix="mineru_md_image",
                )
                pdf_image = _PdfImage(
                    page_number=int(entry["page_number"]),
                    image_index=image_index,
                    width=width,
                    height=height,
                    ext=ext,
                    data=image_bytes,
                    caption=str(entry.get("title") or ""),
                    kind=str(entry.get("kind") or "image"),
                    debug_path=debug_path,
                    lead_text=str(entry.get("lead_text") or ""),
                )
                images.append(pdf_image)
        return images

    def _describe_images(
        self,
        file_path: Path,
        images: list[_PdfImage],
    ) -> list[ImageDescription]:
        """处理describe图片集合。"""
        if not images:
            return []

        if len(images) == 1:
            return self._describe_images_serial(file_path, images)

        worker_count = self._vision_worker_count(len(images))
        if worker_count == 1:
            return self._describe_images_serial(file_path, images)

        descriptions: list[ImageDescription] = []
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="vision") as executor:
            futures = [executor.submit(self._describe_one, image) for image in images]
            for image, future in zip(images, futures):
                try:
                    descriptions.append(future.result())
                except Exception:
                    logger.exception(
                        "Failed to describe MinerU image file=%s page=%s image_index=%s",
                        file_path.name,
                        image.page_number,
                        image.image_index,
                    )
        return descriptions

    def _describe_images_serial(
        self,
        file_path: Path,
        images: list[_PdfImage],
    ) -> list[ImageDescription]:
        """处理describe图片集合serial。"""
        descriptions: list[ImageDescription] = []
        for image in images:
            try:
                descriptions.append(self._describe_one(image))
            except Exception:
                logger.exception(
                    "Failed to describe MinerU image file=%s page=%s image_index=%s",
                    file_path.name,
                    image.page_number,
                    image.image_index,
                )
        return descriptions

    def _vision_worker_count(self, image_count: int) -> int:
        """处理vision工作线程数count。"""
        if image_count <= 0:
            return 1
        configured = max(int(self.settings.vision_max_workers or 1), 1)
        return min(configured, image_count)

    def _find_markdown_member(self, archive: ZipFile) -> str | None:
        """查找Markdown 内容压缩包成员。"""
        markdown_members = [
            name for name in archive.namelist() if name.replace("\\", "/").lower().endswith(".md")
        ]
        return markdown_members[0] if markdown_members else None

    def _mineru_image_block_map(
        self,
        flattened_path: Path,
        page_start: int,
    ) -> dict[str, dict[str, Any]]:
        """处理mineru图片块map。"""
        try:
            items = json.loads(flattened_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load MinerU flattened content list: %s", flattened_path)
            return {}

        mapping: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or item.get("block_type") or "").strip().lower()
            if kind not in {"image", "chart"}:
                continue
            content = item.get("content")
            if not isinstance(content, dict):
                continue
            source = content.get("image_source")
            if not isinstance(source, dict):
                continue
            raw_path = str(source.get("path") or "").strip()
            if not raw_path or raw_path.endswith("/"):
                continue
            normalized_path = raw_path.replace("\\", "/").lstrip("./")
            page_idx = int(item.get("page_idx") or item.get("page_no") or 0)
            bbox = item.get("bbox") or [0, 0, 0, 0]
            width = 0
            height = 0
            if isinstance(bbox, list) and len(bbox) >= 4:
                width = max(int(float(bbox[2]) - float(bbox[0])), 0)
                height = max(int(float(bbox[3]) - float(bbox[1])), 0)
            mapping.setdefault(
                normalized_path,
                {
                    "page_number": page_start + page_idx,
                    "kind": kind,
                    "title": self._mineru_image_title(content, kind),
                    "lead_text": self._mineru_image_lead_text(content),
                    "width": width,
                    "height": height,
                },
            )
        return mapping

    def _extract_md_image_entries(
        self,
        markdown: str,
        markdown_name: str,
        block_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """提取md图片entries。"""
        entries: list[dict[str, Any]] = []
        base_dir = posixpath.dirname(markdown_name.replace("\\", "/"))
        lines = markdown.splitlines()
        for index, raw_line in enumerate(lines):
            matches = list(_MD_IMAGE_RE.finditer(raw_line))
            if not matches:
                continue
            context_lines = self._previous_non_empty_lines(lines, index, limit=2)
            context_title = self._compose_context_title(context_lines)
            for match in matches:
                relative_path = match.group("path").strip().strip("<>").strip()
                normalized_path = relative_path.replace("\\", "/").lstrip("./")
                block = block_map.get(normalized_path)
                if block is None:
                    continue
                archive_name = posixpath.normpath(posixpath.join(base_dir, normalized_path))
                alt_text = normalize_whitespace(match.group("alt"))
                title = alt_text or str(block.get("title") or "") or context_title
                lead_text = self._compose_lead_text(context_lines)
                if not lead_text:
                    lead_text = str(block.get("lead_text") or "")
                entries.append(
                    {
                        **block,
                        "archive_name": archive_name,
                        "title": title or str(block.get("title") or ""),
                        "lead_text": lead_text,
                    }
                )
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in entries:
            key = str(entry.get("archive_name") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        return deduped

    def _previous_non_empty_lines(
        self,
        lines: list[str],
        current_index: int,
        *,
        limit: int,
    ) -> list[str]:
        """处理previousnonempty文本行。"""
        collected: list[str] = []
        for index in range(current_index - 1, -1, -1):
            line = normalize_whitespace(lines[index])
            if not line:
                if collected:
                    break
                continue
            if _MD_IMAGE_RE.search(line):
                continue
            collected.append(line)
            if len(collected) >= limit:
                break
        collected.reverse()
        return collected

    def _compose_lead_text(self, lines: list[str]) -> str:
        """组合前置上下文文本。"""
        cleaned = [normalize_whitespace(line) for line in lines if normalize_whitespace(line)]
        return "\n".join(cleaned[:2])

    def _compose_context_title(self, lines: list[str]) -> str:
        """组合上下文标题。"""
        cleaned = [normalize_whitespace(line) for line in lines if normalize_whitespace(line)]
        if not cleaned:
            return ""
        return normalize_whitespace(" ".join(cleaned[:2]))

    def _mineru_image_title(self, content: dict[str, Any], kind: str) -> str:
        """处理mineru图片标题。"""
        if kind == "chart":
            title = self._flatten_caption_items(content.get("chart_caption"))
            if title:
                return title
        title = self._flatten_caption_items(content.get("image_caption"))
        if title:
            return title
        return ""

    def _mineru_image_lead_text(self, content: dict[str, Any]) -> str:
        """处理mineru图片前置上下文文本。"""
        parts = [
            self._flatten_caption_items(content.get("image_caption")),
            self._flatten_caption_items(content.get("chart_caption")),
            normalize_whitespace(str(content.get("content") or "")),
        ]
        cleaned = [part for part in parts if part]
        return "\n".join(cleaned[:2])

    def _flatten_caption_items(self, value: Any) -> str:
        """展平图注条目列表。"""
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    text = normalize_whitespace(str(item.get("content") or item.get("text") or ""))
                else:
                    text = normalize_whitespace(str(item or ""))
                if text:
                    parts.append(text)
            return "\n".join(parts)
        if isinstance(value, dict):
            return normalize_whitespace(str(value.get("content") or value.get("text") or ""))
        return normalize_whitespace(str(value or ""))
