from __future__ import annotations

from app.core.config import Settings
from app.services.llm.client import OpenAICompatibleLLMClient


class AudioTranscriber:
    def __init__(self, settings: Settings, llm_client: OpenAICompatibleLLMClient) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        if not self.settings.speech_enabled:
            return ""
        return self.llm_client.transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            model=self.settings.speech_model,
        )
