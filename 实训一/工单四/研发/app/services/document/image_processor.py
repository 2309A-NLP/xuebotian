from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.core.config import Settings
from app.services.document.image_describer import ImageDescription, ImageDescriptionMixin
from app.services.document.image_extraction import ImageExtractionMixin
from app.services.llm.client import OpenAICompatibleLLMClient

logger = logging.getLogger(__name__)


class PdfImageDescriber(ImageExtractionMixin, ImageDescriptionMixin):
    def __init__(
        self,
        settings: Settings,
        llm_client: OpenAICompatibleLLMClient,
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def describe_pdf(
        self,
        file_path: Path,
        table_bboxes_by_page: dict[int, list[tuple[float, float, float, float]]] | None = None,
    ) -> dict[int, list[ImageDescription]]:
        if not self.settings.vision_enabled:
            return {}
        images = self._extract_images(file_path, table_bboxes_by_page or {})
        if not images:
            return {}

        max_workers = max(self.settings.vision_max_workers, 1)
        descriptions: list[ImageDescription] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._describe_one, image): image for image in images}
            for future in as_completed(futures):
                image = futures[future]
                try:
                    description = future.result()
                except Exception:
                    logger.exception(
                        "Failed to describe PDF image page=%s index=%s kind=%s file=%s",
                        image.page_number,
                        image.image_index,
                        image.kind,
                        file_path.name,
                    )
                    continue
                if description.description:
                    descriptions.append(description)

        by_page: dict[int, list[ImageDescription]] = {}
        for description in sorted(
            descriptions,
            key=lambda item: (item.page_number, item.image_index),
        ):
            by_page.setdefault(description.page_number, []).append(description)
        logger.info(
            "Described PDF visual blocks file=%s images=%s described=%s",
            file_path.name,
            len(images),
            len(descriptions),
        )
        return by_page
