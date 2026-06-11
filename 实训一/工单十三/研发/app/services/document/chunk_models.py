from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class _TextBlock:
    """表示一段带页码与标题信息的文本块。"""
    text: str
    heading: str = ""
    page_start: int = 0
    page_end: int = 0

    def __post_init__(self) -> None:
        """在数据类初始化后补齐派生字段或归一化状态。"""
        if self.page_end < self.page_start:
            self.page_end = self.page_start


class _Counter:
    """为切片生成过程提供递增编号的简单计数器。"""
    def __init__(self) -> None:
        """初始化计数器所需的依赖和运行参数。"""
        self._value = 0

    def next(self) -> int:
        """返回下一个递增编号。"""
        value = self._value
        self._value += 1
        return value
