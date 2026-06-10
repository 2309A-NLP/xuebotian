from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class _TextBlock:
    text: str
    heading: str = ""
    page_start: int = 0
    page_end: int = 0

    def __post_init__(self) -> None:
        if self.page_end < self.page_start:
            self.page_end = self.page_start


class _Counter:
    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        value = self._value
        self._value += 1
        return value
