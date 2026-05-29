import json
import traceback
from typing import Dict, Iterator, List

import requests

from app.core.config import (
    ONLINE_LLM_API_KEY,
    ONLINE_LLM_BASE_URL,
    ONLINE_LLM_MODEL,
    ONLINE_LLM_TIMEOUT,
    SGLANG_API_KEY,
    SGLANG_BASE_URL,
    SGLANG_MODEL,
)
from app.core.logging_utils import get_logger


logger = get_logger(__name__)


def _extract_error_message(response: requests.Response, fallback: str) -> str:

    try:
        payload = response.json()
    except ValueError:
        return fallback

    if not isinstance(payload, dict):
        return fallback

    for key in ("detail", "message", "error"):
        value = payload.get(key)
        if isinstance(value, dict):
            value = value.get("message") or value.get("type")
        if value:
            return str(value)

    return fallback


def _force_utf8_response(response: requests.Response) -> requests.Response:
    response.encoding = "utf-8"
    return response


def _normalize_openai_compatible_base_url(base_url: str) -> str:

    normalized = (base_url or "").rstrip("/")
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized }/v1"


def _extract_stream_delta(payload: Dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""

    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    content = delta.get("content")
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("text")
        )
    if content:
        return str(content)

    message = choice.get("message") or {}
    message_content = message.get("content")
    if isinstance(message_content, list):
        return "".join(
            str(part.get("text", ""))
            for part in message_content
            if isinstance(part, dict) and part.get("text")
        )
    return str(message_content or "")


def _iter_openai_compatible_stream(response: requests.Response) -> Iterator[str]:
    _force_utf8_response(response)
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue

        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            if data == "[DONE]":
                break
            continue

        try:
            payload = json.loads(data)
        except ValueError:
            continue

        delta = _extract_stream_delta(payload)
        if delta:
            yield delta


class SGLangLLM:

    def __init__(
        self,
        base_url: str = None,
        model: str = None,
        api_key: str = None,
    ):
        self.base_url = _normalize_openai_compatible_base_url(
            base_url or SGLANG_BASE_URL
        )
        self.model = model or SGLANG_MODEL
        self.api_key = api_key or SGLANG_API_KEY

    def _validate(self) -> None:
        if not self.base_url:
            raise RuntimeError("SGLang base URL is not configured")
        if not self.model:
            raise RuntimeError("SGLang model name is not configured")

    def chat(self, messages: List[Dict]) -> str:
        self._validate()
        try:
            response = requests.post(
                f"{self .base_url }/chat/completions",
                headers={
                    "Authorization": f"Bearer {self .api_key }",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                },
                timeout=ONLINE_LLM_TIMEOUT,
            )
            _force_utf8_response(response)
        except requests.RequestException as exc:
            logger.error("离线模型请求失败。\n%s", traceback.format_exc())

            raise RuntimeError(
                "Offline model service is unavailable. Check the SGLang server."
            ) from exc

        if not response.ok:
            raise RuntimeError(
                _extract_error_message(
                    response,
                    "Offline model request failed",
                )
            )

        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("离线模型返回非法 JSON。\n%s", traceback.format_exc())
            raise RuntimeError("Offline model returned invalid JSON") from exc

        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("Offline model returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError("Offline model returned empty content")
        return content

    def stream_chat(self, messages: List[Dict]) -> Iterator[str]:
        self._validate()
        try:
            response = requests.post(
                f"{self .base_url }/chat/completions",
                headers={
                    "Authorization": f"Bearer {self .api_key }",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                },
                timeout=ONLINE_LLM_TIMEOUT,
                stream=True,
            )
            _force_utf8_response(response)
        except requests.RequestException as exc:
            logger.error("离线模型流式请求失败。\n%s", traceback.format_exc())
            raise RuntimeError(
                "Offline model service is unavailable. Check the SGLang server."
            ) from exc

        if not response.ok:
            raise RuntimeError(
                _extract_error_message(
                    response,
                    "Offline model request failed",
                )
            )

        try:
            yield from _iter_openai_compatible_stream(response)
        finally:
            response.close()


class OnlineLLM:
    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
    ):
        self.base_url = _normalize_openai_compatible_base_url(
            base_url or ONLINE_LLM_BASE_URL
        )
        self.api_key = api_key or ONLINE_LLM_API_KEY
        self.model = model or ONLINE_LLM_MODEL

    def _validate(self) -> None:
        if not self.base_url:
            raise RuntimeError("Online model base URL is not configured")
        if not self.api_key:
            raise RuntimeError("Online model API key is not configured")
        if not self.model:
            raise RuntimeError("Online model name is not configured")

    def chat(self, messages: List[Dict]) -> str:
        self._validate()
        try:
            response = requests.post(
                f"{self .base_url }/chat/completions",
                headers={
                    "Authorization": f"Bearer {self .api_key }",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                },
                timeout=ONLINE_LLM_TIMEOUT,
            )
            _force_utf8_response(response)
        except requests.RequestException as exc:
            logger.error("在线模型请求失败。\n%s", traceback.format_exc())
            raise RuntimeError(
                "Online model service is unavailable. Check network and configuration."
            ) from exc

        if not response.ok:
            raise RuntimeError(
                _extract_error_message(
                    response,
                    "Online model request failed",
                )
            )

        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("在线模型返回非法 JSON。\n%s", traceback.format_exc())
            raise RuntimeError("Online model returned invalid JSON") from exc

        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("Online model returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError("Online model returned empty content")
        return content

    def stream_chat(self, messages: List[Dict]) -> Iterator[str]:
        self._validate()
        try:
            response = requests.post(
                f"{self .base_url }/chat/completions",
                headers={
                    "Authorization": f"Bearer {self .api_key }",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                },
                timeout=ONLINE_LLM_TIMEOUT,
                stream=True,
            )
            _force_utf8_response(response)
        except requests.RequestException as exc:
            logger.error("在线模型流式请求失败。\n%s", traceback.format_exc())
            raise RuntimeError(
                "Online model service is unavailable. Check network and configuration."
            ) from exc

        if not response.ok:
            raise RuntimeError(
                _extract_error_message(
                    response,
                    "Online model request failed",
                )
            )

        try:
            yield from _iter_openai_compatible_stream(response)
        finally:
            response.close()


class ChatRouterLLM:
    def __init__(self):
        self.offline_llm = SGLangLLM()
        self.online_llm = OnlineLLM()

    def chat(self, messages: List[Dict], mode: str = "offline") -> str:
        if mode == "online":
            return self.online_llm.chat(messages)
        return self.offline_llm.chat(messages)

    def stream_chat(self, messages: List[Dict], mode: str = "offline") -> Iterator[str]:
        if mode == "online":
            yield from self.online_llm.stream_chat(messages)
            return
        yield from self.offline_llm.stream_chat(messages)
