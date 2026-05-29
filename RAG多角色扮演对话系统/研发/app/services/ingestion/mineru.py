import json
import re
import time
import uuid
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from app.core.config import (
    MINERU_API_BASE_URL,
    MINERU_API_TOKEN,
    MINERU_API_USER_TOKEN,
    MINERU_PDF_ENABLE_FORMULA,
    MINERU_PDF_ENABLE_OCR,
    MINERU_PDF_ENABLE_TABLE,
    MINERU_PDF_LANGUAGE,
    MINERU_PDF_MODEL_VERSION,
    MINERU_PDF_POLL_INTERVAL_SECONDS,
    MINERU_PDF_POLL_TIMEOUT_SECONDS,
    MINERU_PDF_REQUEST_TIMEOUT,
)
from app.core.logging_utils import get_logger
from app.services.ingestion.text_utils import clean_inline_text, clean_text


logger = get_logger(__name__)

_IGNORED_BLOCK_TYPES = {
    "header",
    "footer",
    "page_number",
    "aside_text",
    "page_footnote",
}


def mineru_available() -> bool:
    return bool((MINERU_API_TOKEN or "").strip())


def extract_pdf_text_with_mineru(file_path: Path) -> str:
    client = MinerUClient()
    archive = client.extract_file(file_path)
    return sanitize_mineru_text(_build_text_from_archive(archive, file_path.name))


class MinerUClient:
    def __init__(self) -> None:
        self.base_url = (MINERU_API_BASE_URL or "https://mineru.net").rstrip("/")
        self.token = (MINERU_API_TOKEN or "").strip()
        self.user_token = (MINERU_API_USER_TOKEN or "").strip()
        self.request_timeout = max(30, int(MINERU_PDF_REQUEST_TIMEOUT))
        self.poll_timeout = max(30, int(MINERU_PDF_POLL_TIMEOUT_SECONDS))
        self.poll_interval = max(1, int(MINERU_PDF_POLL_INTERVAL_SECONDS))

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise RuntimeError("未配置 MinerU API Token")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "*/*",
        }
        if self.user_token:
            headers["token"] = self.user_token
        return headers

    def _json_headers(self) -> Dict[str, str]:
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        return headers

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = requests.request(
            method=method,
            url=url,
            headers=self._json_headers(),
            json=json_body,
            timeout=self.request_timeout,
        )
        response.encoding = "utf-8"
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"MinerU API 调用失败: {payload.get('msg') or '未知错误'}"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("MinerU API 返回数据格式不正确")
        return data

    def _apply_upload_url(self, file_path: Path, data_id: str) -> Dict[str, Any]:
        payload = {
            "files": [
                {
                    "name": file_path.name,
                    "data_id": data_id,
                    "is_ocr": MINERU_PDF_ENABLE_OCR,
                }
            ],
            "model_version": MINERU_PDF_MODEL_VERSION,
            "language": MINERU_PDF_LANGUAGE,
            "enable_formula": MINERU_PDF_ENABLE_FORMULA,
            "enable_table": MINERU_PDF_ENABLE_TABLE,
        }
        return self._request_json(
            "POST",
            f"{self.base_url}/api/v4/file-urls/batch",
            json_body=payload,
        )

    def _upload_file(self, upload_url: str, file_path: Path) -> None:
        with open(file_path, "rb") as file:
            response = requests.put(
                upload_url,
                data=file,
                timeout=self.request_timeout,
            )
        response.raise_for_status()

    def _poll_batch_result(self, batch_id: str, data_id: str) -> Dict[str, Any]:
        deadline = time.time() + self.poll_timeout
        last_state = ""
        while time.time() < deadline:
            data = self._request_json(
                "GET",
                f"{self.base_url}/api/v4/extract-results/batch/{batch_id}",
            )
            extract_results = data.get("extract_result") or []
            matched = None
            for item in extract_results:
                if not isinstance(item, dict):
                    continue
                if item.get("data_id") == data_id or item.get("file_name") is not None:
                    matched = item
                    if item.get("data_id") == data_id:
                        break
            if not isinstance(matched, dict):
                time.sleep(self.poll_interval)
                continue

            state = str(matched.get("state") or "")
            if state != last_state:
                logger.info("MinerU PDF 解析状态更新: 文件=%s 状态=%s", data_id, state)
                last_state = state

            if state == "done":
                return matched
            if state == "failed":
                raise RuntimeError(
                    f"MinerU PDF 解析失败: {matched.get('err_msg') or '未知错误'}"
                )
            time.sleep(self.poll_interval)

        raise TimeoutError("MinerU PDF 解析超时")

    def _download_archive(self, archive_url: str) -> bytes:
        response = requests.get(archive_url, timeout=self.request_timeout)
        response.raise_for_status()
        return response.content

    def extract_file(self, file_path: Path) -> bytes:
        if not file_path.exists():
            raise FileNotFoundError(file_path)
        data_id = f"{file_path.stem[:64]}-{uuid.uuid4().hex[:12]}"
        logger.info("开始调用 MinerU 解析 PDF: 文件=%s", file_path.name)
        upload_data = self._apply_upload_url(file_path, data_id)
        batch_id = upload_data.get("batch_id")
        upload_urls = upload_data.get("file_urls") or []
        if not batch_id or not upload_urls:
            raise RuntimeError("MinerU 未返回有效的上传地址")

        self._upload_file(str(upload_urls[0]), file_path)
        logger.info("MinerU PDF 上传完成: 文件=%s 批次=%s", file_path.name, batch_id)
        result = self._poll_batch_result(str(batch_id), data_id)
        archive_url = result.get("full_zip_url")
        if not archive_url:
            raise RuntimeError("MinerU 未返回解析结果压缩包地址")

        logger.info("MinerU PDF 解析完成，开始下载结果: 文件=%s", file_path.name)
        return self._download_archive(str(archive_url))


def _build_text_from_archive(archive_bytes: bytes, file_name: str) -> str:
    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        content_v2_name = _find_archive_member(names, "_content_list_v2.json")
        if content_v2_name:
            text = _parse_content_list_v2(archive.read(content_v2_name))
            if text:
                return text

        content_name = _find_archive_member(names, "_content_list.json")
        if content_name:
            text = _parse_content_list(archive.read(content_name))
            if text:
                return text

        markdown_name = _find_archive_member(names, "full.md", exact_name=True)
        if markdown_name:
            text = _parse_markdown(archive.read(markdown_name))
            if text:
                return text

    raise RuntimeError(f"MinerU 返回结果中未找到可用文本内容: {file_name}")


def sanitize_mineru_text(text: str) -> str:
    normalized = _normalize_mineru_text(text)
    if not normalized:
        return ""

    lines = [line for line in normalized.split("\n") if line.strip()]
    if not lines:
        return ""

    line_counts = Counter(lines)
    cleaned_lines = _filter_noise_lines(lines, line_counts)
    if not cleaned_lines:
        return ""

    compacted_lines = _deduplicate_adjacent_lines(cleaned_lines)
    return clean_text("\n".join(compacted_lines))


def _normalize_mineru_text(text: str) -> str:
    normalized = (text or "").replace("\ufeff", "").replace("\u0000", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"<!--.*?-->", " ", normalized, flags=re.S)
    normalized = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", normalized)
    normalized = re.sub(r"\[(?:图片|图像|image)[^\]]*]\([^)]*\)", " ", normalized, flags=re.I)
    normalized = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+", " ", normalized)
    normalized = re.sub(r"<img[^>]*>", " ", normalized, flags=re.I)
    normalized = re.sub(r"</?(?:figure|figcaption|table|tbody|thead|tr|td|th|span|div|p)[^>]*>", " ", normalized, flags=re.I)
    normalized = re.sub(r"[^\S\n]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return clean_text(normalized)


def _filter_noise_lines(lines: List[str], line_counts: Counter) -> List[str]:
    cleaned_lines: List[str] = []
    for line in lines:
        normalized = clean_inline_text(line)
        if not normalized:
            continue
        if _is_page_noise_line(normalized):
            continue
        if _looks_like_asset_reference(normalized):
            continue
        if _is_repeated_layout_noise(normalized, line_counts):
            continue
        cleaned_lines.append(normalized)
    return cleaned_lines


def _deduplicate_adjacent_lines(lines: List[str]) -> List[str]:
    result: List[str] = []
    previous = ""
    for line in lines:
        if line == previous:
            continue
        result.append(line)
        previous = line
    return result


def _is_page_noise_line(line: str) -> bool:
    lowered = line.lower()
    patterns = (
        r"^page\s*\d+(\s*/\s*\d+)?$",
        r"^page\s*\d+\s*of\s*\d+$",
        r"^第\s*\d+\s*页(\s*/\s*共?\s*\d+\s*页)?$",
        r"^\d+\s*/\s*\d+$",
    )
    return any(re.fullmatch(pattern, lowered) for pattern in patterns)


def _looks_like_asset_reference(line: str) -> bool:
    lowered = line.lower()
    if len(line) > 240 and "base64" in lowered:
        return True
    if re.fullmatch(r".*\.(png|jpg|jpeg|gif|bmp|svg|webp)$", lowered):
        return True
    if lowered.startswith(("http://", "https://", "file://")) and len(line) > 48:
        return True
    return False


def _is_repeated_layout_noise(line: str, line_counts: Counter) -> bool:
    if len(line) > 80:
        return False
    if line_counts.get(line, 0) < 3:
        return False
    if re.search(r"[。！？；!?]", line):
        return False
    digit_ratio = sum(char.isdigit() for char in line) / max(1, len(line))
    if digit_ratio >= 0.35:
        return True
    if re.search(r"(copyright|版权所有|保密|机密|confidential|内部资料)", line, re.I):
        return True
    if len(line) <= 24:
        return True
    return False


def _find_archive_member(
    names: Iterable[str], pattern: str, *, exact_name: bool = False
) -> Optional[str]:
    for name in names:
        normalized = name.replace("\\", "/")
        if exact_name:
            if normalized.endswith(f"/{pattern}") or normalized == pattern:
                return name
        elif normalized.endswith(pattern):
            return name
    return None


def _parse_content_list(payload: bytes) -> str:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, list):
        return ""
    parts: List[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "").strip().lower()
        if block_type in _IGNORED_BLOCK_TYPES:
            continue
        text = _extract_text_from_legacy_item(item, block_type)
        if text:
            parts.append(text)
    return clean_text("\n\n".join(parts))


def _parse_content_list_v2(payload: bytes) -> str:
    data = json.loads(payload.decode("utf-8"))
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list):
        return ""
    parts: List[str] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        items = page.get("items") or page.get("content_list") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            block_type = str(item.get("type") or "").strip().lower()
            if block_type in _IGNORED_BLOCK_TYPES:
                continue
            content = item.get("content")
            text = _extract_text_from_v2_item(block_type, content, item)
            if text:
                parts.append(text)
    return clean_text("\n\n".join(parts))


def _extract_text_from_legacy_item(item: Dict[str, Any], block_type: str) -> str:
    if block_type == "text":
        return clean_text(item.get("text") or item.get("content") or "")
    if block_type == "equation":
        return clean_inline_text(item.get("latex") or item.get("text") or "")
    if block_type == "list":
        return _join_text_parts(item.get("list_items") or item.get("items") or [])
    if block_type in {"image", "chart"}:
        return _join_text_parts(
            [
                item.get("img_caption"),
                item.get("img_footnote"),
                item.get("chart_caption"),
                item.get("chart_footnote"),
                item.get("content"),
                item.get("text"),
            ]
        )
    if block_type == "table":
        return _join_text_parts(
            [
                item.get("table_caption"),
                item.get("table_body"),
                item.get("table_footnote"),
                item.get("content"),
                item.get("text"),
            ]
        )
    if block_type == "code":
        return _join_text_parts([item.get("code_caption"), item.get("code_body")])
    return _join_text_parts(
        [
            item.get("text"),
            item.get("content"),
            item.get("title"),
            item.get("caption"),
            item.get("value"),
        ]
    )


def _extract_text_from_v2_item(
    block_type: str, content: Any, item: Dict[str, Any]
) -> str:
    if isinstance(content, dict):
        return _join_text_parts(
            [
                content.get("text"),
                content.get("content"),
                content.get("title"),
                content.get("caption"),
                content.get("footnote"),
                content.get("body"),
                content.get("latex"),
                content.get("value"),
                content.get("code_body"),
                content.get("code_caption"),
                content.get("table_body"),
                content.get("table_caption"),
                content.get("table_footnote"),
                content.get("chart_caption"),
                content.get("chart_footnote"),
                content.get("img_caption"),
                content.get("img_footnote"),
                content.get("list_items"),
            ]
        )
    if isinstance(content, list):
        return _join_text_parts(content)
    if isinstance(content, str):
        return clean_text(content)
    return _extract_text_from_legacy_item(item, block_type)


def _parse_markdown(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="ignore")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("<details>", "\n").replace("</details>", "\n")
    text = text.replace("<summary>", "").replace("</summary>", "\n")
    return clean_text(text)


def _join_text_parts(values: Iterable[Any]) -> str:
    parts: List[str] = []
    for value in values:
        if isinstance(value, list):
            nested = _join_text_parts(value)
            if nested:
                parts.append(nested)
            continue
        if isinstance(value, dict):
            nested = _join_text_parts(value.values())
            if nested:
                parts.append(nested)
            continue
        text = clean_inline_text(str(value or ""))
        if text:
            parts.append(text)
    return clean_text("\n".join(parts))
