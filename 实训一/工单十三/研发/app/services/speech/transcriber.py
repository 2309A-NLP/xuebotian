from __future__ import annotations

from app.core.config import Settings
from app.services.llm.client import OpenAICompatibleLLMClient


class AudioTranscriber:
    """基于 LLM 客户端完成音频转写的轻量服务。"""
    def __init__(self, settings: Settings, llm_client: OpenAICompatibleLLMClient) -> None:
        """初始化音频转写服务所需的依赖和运行参数。"""
        self.settings = settings
        self.llm_client = llm_client

    def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        """将输入音频转写为文本。"""
        if not self.settings.speech_enabled:
            return ""
        return self.llm_client.transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            model=self.settings.speech_model,
        )
