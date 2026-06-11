from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ImageDescription:
    """表示图片经过视觉模型处理后的结果。

    这个对象是图片解析阶段和切片阶段之间的桥梁，
    同时保存描述文本、页面位置、图题和调试信息。
    """
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
    """表示从 PDF 中提取出的单张原始图片。

    其中既包含送入视觉模型所需的二进制数据，也包含页码、尺寸、
    图题和上文线索等上下文信息，供提示词构造时使用。
    """
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

