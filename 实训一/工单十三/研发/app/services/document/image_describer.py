from __future__ import annotations

from pathlib import Path

from app.services.document.image_models import ImageDescription, _PdfImage


class ImageDescriptionMixin:
    """封装图片描述阶段的公共能力。

    这里主要负责两件事：一是把单张图片组织成视觉模型可理解的输入，
    二是在调试模式下把中间图片文件保存到本地，便于排查识别质量问题。
    """
    def _describe_one(self, image: _PdfImage) -> ImageDescription:
        """调用视觉模型描述单张 PDF 图片，并返回统一的数据对象。

        输出对象除了描述文本，还会保留页码、尺寸、标题和调试路径，
        方便后续切片、展示和问题定位。
        """
        prompt = self._image_prompt(image)
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
            lead_text=image.lead_text,
        )

    def _image_prompt(self, image: _PdfImage) -> str:
        """为单张图片生成视觉描述提示词。

        提示词会结合页码、图题和上文线索约束模型输出，
        同时区分图表类和普通图片类内容，尽量让描述更聚焦于可检索信息。
        """
        title_hint = f"标题或注释：{image.caption}\n" if image.caption else ""
        lead_hint = f"上文线索：{image.lead_text}\n" if image.lead_text else ""
        kind_label = "图表" if image.kind == "chart" else "图片"
        kind_rule = (
            "若是图表，重点提取标题、坐标轴、图例、关键数字、变化趋势和对比关系。"
            if image.kind == "chart"
            else "若不是图表，重点提取主体、标签、可见文字、数字和空间关系。"
        )
        return (
            f"这是 PDF 第 {image.page_number} 页中的{kind_label}。\n"
            f"{title_hint}"
            f"{lead_hint}"
            "任务：只描述图中肉眼可见的信息，不要编造，不要解释作者意图，不要输出表格内容；默认图片中不包含表格。\n"
            "先判断该图是否属于架构图、流程图、关系图或示意图。\n"
            "如果属于上述类型，请用 Markdown 输出，格式如下：\n"
            "## 标题\n"
            "- 没有明确标题时写“未标注”\n"
            "## 主要元素\n"
            "- 逐条列出主要节点、模块、对象或区域\n"
            "## 关系与方向\n"
            "- 逐条列出连接关系、上下游、箭头方向或包含关系\n"
            "## 图中文字\n"
            "- 只摘录图中能直接看见的关键文字、数字或标签\n"
            "如果不属于上述类型，请直接输出一段简洁中文描述，不要使用 Markdown 列表。"
            f"{kind_rule}"
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
        """按约定目录保存调试图片，并返回生成后的路径。

        这一步只在调试开关开启时生效，用于保留送给视觉模型的原始图片，
        方便回看“模型到底看到了什么”。
        """
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
        """根据图片扩展名推断发送给视觉接口的 MIME 类型。"""
        normalized = ext.lower().lstrip(".")
        if normalized in {"jpg", "jpeg"}:
            return "image/jpeg"
        if normalized == "webp":
            return "image/webp"
        return "image/png"
