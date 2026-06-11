from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ImageDescription:
    page_number: int
    image_index: int
    width: int
    height: int
    description: str
    caption: str = ""
    kind: str = "image"
    debug_path: str = ""
    lead_text: str = ""


@dataclass(slots=True)
class _PdfImage:
    page_number: int
    image_index: int
    width: int
    height: int
    ext: str
    data: bytes
    caption: str = ""
    kind: str = "image"
    debug_path: str = ""
    lead_text: str = ""

