from __future__ import annotations

import io
import logging
from base64 import b64encode
from collections.abc import Iterator

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings

logger = logging.getLogger(__name__)


class OpenAICompatibleLLMClient:
    """封装兼容 OpenAI 协议的聊天、视觉和语音接口调用。"""
    def __init__(self, settings: Settings) -> None:
        """初始化LLM 客户端所需的依赖和运行参数。"""
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.llm_api_key or "EMPTY",
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """调用聊天模型生成一次性回答。"""
        logger.info("Calling LLM model=%s", self.settings.llm_model)
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=self.settings.llm_temperature if temperature is None else temperature,
            max_tokens=self.settings.llm_max_tokens if max_tokens is None else max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def stream_chat(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """调用聊天模型并按流式片段持续返回内容。"""
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

    @retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
    ) -> str:
        """调用视觉模型描述图片内容。"""
        model = self.settings.vision_model or self.settings.llm_model
        logger.info("Calling vision model=%s image_bytes=%s", model, len(image_bytes))
        image_base64 = b64encode(image_bytes).decode("ascii")
        response = self.client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=self.settings.vision_max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}",
                            },
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content or ""

    def transcribe(self, audio_bytes: bytes, filename: str, model: str) -> str:
        """将输入音频转写为文本。"""
        file_obj = io.BytesIO(audio_bytes)
        file_obj.name = filename
        response = self.client.audio.transcriptions.create(
            model=model,
            file=file_obj,
        )
        return getattr(response, "text", "") or ""

    def close(self) -> None:
        """关闭当前对象持有的连接、模型或其他外部资源。"""
        self.client.close()
