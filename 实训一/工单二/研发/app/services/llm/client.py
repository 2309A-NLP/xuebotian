from __future__ import annotations

import io
import logging
from collections.abc import Iterator

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings

logger = logging.getLogger(__name__)


class OpenAICompatibleLLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.llm_api_key or "EMPTY",
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        logger.info("Calling LLM model=%s", self.settings.llm_model)
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def stream_chat(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        logger.info("Streaming LLM model=%s", self.settings.llm_model)
        stream = self.client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta

    def transcribe(self, audio_bytes: bytes, filename: str, model: str) -> str:
        file_obj = io.BytesIO(audio_bytes)
        file_obj.name = filename
        response = self.client.audio.transcriptions.create(
            model=model,
            file=file_obj,
        )
        return getattr(response, "text", "") or ""

    def close(self) -> None:
        self.client.close()
