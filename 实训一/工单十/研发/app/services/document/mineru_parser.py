from __future__ import annotations

import io
import json
import logging
import re
import shutil
import time
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import fitz
import requests

from app.core.config import Settings
from app.models.domain import ParsedPage, TableBlock
from app.services.document.table_processor import normalize_grid
from app.utils.text import normalize_whitespace

logger = logging.getLogger(__name__)

_TERMINAL_SUCCESS_STATES = {"done", "completed", "success", "succeeded"}
_TERMINAL_FAILURE_STATES = {"failed", "error", "expired", "cancelled"}
_SELF_HOSTED_TASK_PENDING_STATES = {"pending", "queued", "running", "processing", "in_progress"}
_IGNORED_BLOCK_TYPES = {
    "page_header",
    "page_footer",
    "page_number",
    "header",
    "footer",
    "footnote",
    "aside_text",
    "page_footnote",
}


@dataclass(slots=True)
class _PdfPart:
    path: Path
    start_page: int
    end_page: int
    total_pages: int
    temporary: bool


@dataclass(slots=True)
class _PartParseResult:
    content_list: list[dict[str, Any]]
    fallback_text: str = ""
    raw_result: dict[str, Any] = field(default_factory=dict)
    archive_bytes: bytes = b""
    archive_member_name: str = ""
    archive_member_format: str = "json"
    archive_payload: Any = None


class _HtmlTableGridParser(HTMLParser):
    """Parse a MinerU ``<table>`` HTML string into a rectangular grid.

    Handles ``colspan``/``rowspan`` by replicating cell text across the spanned
    cells, so the resulting grid is consistent and can be fed to
    :func:`normalize_grid` for header detection and cleaning.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._rows: list[list[str]] = []
        self._current: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_colspan = 1
        self._cell_rowspan = 1
        # Pending rowspans carried into following rows: column -> (text, remaining rows).
        self._pending_spans: dict[int, tuple[str, int]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._current = []
        elif tag in {"td", "th"} and self._current is not None:
            self._cell_parts = []
            attr_map = {key.lower(): (value or "") for key, value in attrs}
            self._cell_colspan = self._safe_span(attr_map.get("colspan"))
            self._cell_rowspan = self._safe_span(attr_map.get("rowspan"))
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None and data:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current is not None and self._cell_parts is not None:
            text = normalize_whitespace(" ".join(self._cell_parts)).strip()
            for _ in range(max(self._cell_colspan, 1)):
                self._current.append(text)
            self._cell_parts = None
            self._cell_colspan = 1
            self._cell_rowspan = 1
        elif tag == "tr" and self._current is not None:
            self._rows.append(self._current)
            self._current = None

    def _safe_span(self, value: str | None) -> int:
        try:
            return max(int(str(value).strip()), 1)
        except (TypeError, ValueError):
            return 1

    def grid(self) -> list[list[str]]:
        return self._rows


def parse_table_html(html: str) -> tuple[list[str], list[list[str]]] | None:
    """Convert a MinerU table HTML string into ``(header, rows)``.

    Returns ``None`` when the markup yields no usable table. The grid is run
    through :func:`normalize_grid` so header detection, multi-row header merge
    and cell cleaning stay consistent with the local pdfplumber parser.
    """
    if not html or "<" not in html:
        return None
    parser = _HtmlTableGridParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # pragma: no cover - defensive against malformed markup
        logger.exception("Failed to parse MinerU table HTML")
        return None

    grid = parser.grid()
    if not grid:
        return None

    block = normalize_grid(grid)
    if block is None:
        return None
    return block.header, block.rows


class MinerUPdfParser:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.mineru_api_base_url.rstrip("/")
        self.api_mode = settings.mineru_api_mode.strip().lower()
        self.api_token = settings.mineru_api_token.strip()
        self.user_token = settings.mineru_api_user_token.strip()
        self.model_version = settings.mineru_model_version.strip() or "vlm"
        self.language = settings.mineru_language.strip() or "auto"
        self.enable_ocr = bool(settings.mineru_enable_ocr)
        self.enable_table = bool(settings.mineru_enable_table)
        self.enable_formula = bool(settings.mineru_enable_formula)
        self.max_pages_per_file = max(int(settings.mineru_max_pages_per_file), 1)
        self.request_timeout_seconds = max(int(settings.mineru_request_timeout_seconds), 30)
        self.poll_interval_seconds = max(float(settings.mineru_poll_interval_seconds), 1.0)
        self.poll_timeout_seconds = max(int(settings.mineru_poll_timeout_seconds), 30)
        self.debug_save_results = bool(settings.mineru_debug_save_results)
        self.debug_dir = settings.mineru_debug_dir
        self._last_debug_artifacts: dict[str, Any] = {}

    def parse(self, file_path: Path) -> list[ParsedPage]:
        if self.api_mode == "cloud" and not self.api_token:
            raise RuntimeError("MINERU_API_TOKEN is not configured")

        self._last_debug_artifacts = {}
        parts, split_dir = self._prepare_parts(file_path)
        debug_doc_dir = self._prepare_debug_doc_dir(file_path) if self.debug_save_results else None
        if debug_doc_dir is not None:
            self._last_debug_artifacts = {
                "mineru_debug_dir": str(debug_doc_dir),
                "mineru_debug_part_count": 0,
            }
        debug_parts: list[dict[str, Any]] = []
        page_fragments: dict[int, list[str]] = {
            page_number: []
            for part in parts
            for page_number in range(part.start_page, part.end_page + 1)
        }
        page_metadata: dict[int, dict[str, Any]] = {
            page_number: {}
            for part in parts
            for page_number in range(part.start_page, part.end_page + 1)
        }
        page_tables: dict[int, list[TableBlock]] = {
            page_number: []
            for part in parts
            for page_number in range(part.start_page, part.end_page + 1)
        }

        logger.info(
            "Start MinerU parsing file=%s parts=%s max_pages_per_file=%s",
            file_path.name,
            len(parts),
            self.max_pages_per_file,
        )
        try:
            with requests.Session() as client:
                for index, part in enumerate(parts, start=1):
                    logger.info(
                        "Submitting MinerU part=%s/%s pages=%s-%s file=%s",
                        index,
                        len(parts),
                        part.start_page,
                        part.end_page,
                        part.path.name,
                    )
                    parsed_part = self._parse_part(client, part)
                    if debug_doc_dir is not None:
                        self._save_part_debug_artifacts(
                            debug_doc_dir,
                            file_path,
                            index,
                            part,
                            parsed_part,
                            debug_parts,
                        )
                    merged_count = self._merge_content_list(
                        page_fragments,
                        page_metadata,
                        page_tables,
                        part,
                        parsed_part.content_list,
                    )
                    if merged_count <= 0 and parsed_part.fallback_text:
                        logger.warning(
                            "MinerU page-level extraction was empty; using fallback text distribution file=%s pages=%s-%s",
                            part.path.name,
                            part.start_page,
                            part.end_page,
                        )
                        self._distribute_fallback_text(
                            page_fragments,
                            part,
                            parsed_part.fallback_text,
                        )
                    if part.temporary:
                        self._delete_part_file(part.path)
        finally:
            for part in parts:
                if part.temporary:
                    self._delete_part_file(part.path)
            if split_dir is not None and split_dir.exists():
                shutil.rmtree(split_dir, ignore_errors=True)

        pages = [
            ParsedPage(
                page_number=page_number,
                text=self._join_page_fragments(page_fragments.get(page_number, [])),
                tables=page_tables.get(page_number, []),
                metadata=page_metadata.get(page_number, {}),
            )
            for page_number in sorted(page_fragments)
        ]
        logger.info(
            "MinerU parsed PDF pages=%s tables=%s file=%s",
            len(pages),
            sum(len(items) for items in page_tables.values()),
            file_path.name,
        )
        if debug_doc_dir is not None:
            self._last_debug_artifacts = self._save_debug_manifest(
                debug_doc_dir,
                file_path,
                debug_parts,
            )
        return pages

    def consume_debug_artifacts(self) -> dict[str, Any]:
        artifacts = dict(self._last_debug_artifacts)
        self._last_debug_artifacts = {}
        return artifacts

    def _prepare_parts(self, file_path: Path) -> tuple[list[_PdfPart], Path | None]:
        with fitz.open(file_path) as document:
            total_pages = document.page_count
            if total_pages <= self.max_pages_per_file:
                return [
                    _PdfPart(
                        path=file_path,
                        start_page=1,
                        end_page=total_pages,
                        total_pages=total_pages,
                        temporary=False,
                    )
                ], None

            split_dir = file_path.parent / f"{file_path.stem}_mineru_parts"
            split_dir.mkdir(parents=True, exist_ok=True)
            parts: list[_PdfPart] = []
            for start_index in range(0, total_pages, self.max_pages_per_file):
                end_index = min(start_index + self.max_pages_per_file, total_pages) - 1
                part_path = (
                    split_dir
                    / f"{file_path.stem}_part_{start_index + 1:04d}_{end_index + 1:04d}.pdf"
                )
                chunk = fitz.open()
                try:
                    chunk.insert_pdf(document, from_page=start_index, to_page=end_index)
                    chunk.save(part_path)
                finally:
                    chunk.close()
                parts.append(
                    _PdfPart(
                        path=part_path,
                        start_page=start_index + 1,
                        end_page=end_index + 1,
                        total_pages=end_index - start_index + 1,
                        temporary=True,
                    )
                )
            return parts, split_dir

    def _parse_part(self, client: requests.Session, part: _PdfPart) -> _PartParseResult:
        if self.api_mode == "self_hosted":
            return self._parse_part_self_hosted(client, part)
        upload_meta = self._create_upload_slot(client, part)
        self._upload_part_file(client, upload_meta["upload_url"], part.path)
        result = self._poll_extract_result(client, upload_meta["batch_id"], upload_meta["data_id"])
        return self._download_content_list(client, result)

    def _parse_part_self_hosted(
        self,
        client: requests.Session,
        part: _PdfPart,
    ) -> _PartParseResult:
        try:
            return self._parse_part_self_hosted_task_api(client, part)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in {404, 405, 501}:
                raise
            logger.info(
                "Self-hosted MinerU /tasks API unavailable, falling back to /file_parse for file=%s",
                part.path.name,
            )
            return self._parse_part_self_hosted_sync(client, part)

    def _parse_part_self_hosted_task_api(
        self,
        client: requests.Session,
        part: _PdfPart,
    ) -> _PartParseResult:
        task_id = self._submit_self_hosted_task(client, part)
        task = self._poll_self_hosted_task(client, task_id)
        if isinstance(task.get("result"), dict):
            return self._parse_self_hosted_payload_data(client, task["result"], part)
        response = client.get(
            f"{self.base_url}/tasks/{task_id}/result",
            headers=self._api_headers(),
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
        return self._parse_self_hosted_response(client, response, part)

    def _parse_part_self_hosted_sync(
        self,
        client: requests.Session,
        part: _PdfPart,
    ) -> _PartParseResult:
        with part.path.open("rb") as file_obj:
            response = client.post(
                f"{self.base_url}/file_parse",
                headers=self._api_headers(),
                data=self._self_hosted_form_data(),
                files={
                    "files": (part.path.name, file_obj, "application/pdf"),
                },
                timeout=self.request_timeout_seconds,
            )
        response.raise_for_status()
        return self._parse_self_hosted_response(client, response, part)

    def _submit_self_hosted_task(
        self,
        client: requests.Session,
        part: _PdfPart,
    ) -> str:
        with part.path.open("rb") as file_obj:
            response = client.post(
                f"{self.base_url}/tasks",
                headers=self._api_headers(),
                data=self._self_hosted_form_data(),
                files={
                    "files": (part.path.name, file_obj, "application/pdf"),
                },
                timeout=self.request_timeout_seconds,
            )
        response.raise_for_status()
        payload = response.json()
        data = self._self_hosted_task_payload(payload)
        task_id = str(data.get("task_id") or data.get("id") or "").strip()
        if not task_id:
            raise RuntimeError(f"Self-hosted MinerU task submission response is incomplete: {payload}")
        return task_id

    def _poll_self_hosted_task(
        self,
        client: requests.Session,
        task_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.poll_timeout_seconds
        last_state = "pending"
        while time.monotonic() < deadline:
            response = client.get(
                f"{self.base_url}/tasks/{task_id}",
                headers=self._api_headers(),
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            data = self._self_hosted_task_payload(payload)
            state = str(
                data.get("status")
                or data.get("state")
                or data.get("task_status")
                or ""
            ).strip().lower()
            if state and state != last_state:
                logger.info("Self-hosted MinerU task updated task_id=%s state=%s", task_id, state)
            last_state = state or last_state
            if state in _TERMINAL_SUCCESS_STATES:
                return data
            if state in _TERMINAL_FAILURE_STATES:
                raise RuntimeError(
                    f"Self-hosted MinerU task failed for {task_id}: {data.get('error') or data.get('message') or payload}"
                )
            if state and state not in _SELF_HOSTED_TASK_PENDING_STATES:
                logger.debug("Unexpected self-hosted MinerU task state task_id=%s state=%s", task_id, state)
            time.sleep(self.poll_interval_seconds)

        raise TimeoutError(f"Timed out waiting for self-hosted MinerU task {task_id} state={last_state}")

    def _official_endpoint(self, path: str) -> str:
        suffix = path if path.startswith("/") else f"/{path}"
        if self.base_url.endswith("/api/v4"):
            return f"{self.base_url}{suffix}"
        return f"{self.base_url}/api/v4{suffix}"

    def _create_upload_slot(self, client: requests.Session, part: _PdfPart) -> dict[str, str]:
        data_id = f"{part.path.stem[:64]}-{uuid.uuid4().hex[:12]}"
        data = self._request_json(
            client,
            "POST",
            self._official_endpoint("/file-urls/batch"),
            json={
                "enable_formula": self.enable_formula,
                "enable_table": self.enable_table,
                "language": self.language,
                "model_version": self.model_version,
                "files": [
                    {
                        "name": part.path.name,
                        "data_id": data_id,
                        "is_ocr": self.enable_ocr,
                    }
                ],
            },
        )
        batch_id = str(data.get("batch_id") or "").strip()
        upload_entries = self._ensure_list(data.get("file_urls") or data.get("files"))
        upload_url = self._extract_upload_url(upload_entries)
        if not batch_id or not upload_url:
            raise RuntimeError(f"MinerU upload slot response is incomplete: {data}")
        return {
            "batch_id": batch_id,
            "upload_url": upload_url,
            "data_id": data_id,
        }

    def _upload_part_file(self, client: requests.Session, upload_url: str, file_path: Path) -> None:
        with file_path.open("rb") as file_obj:
            response = client.put(
                upload_url,
                data=file_obj,
                timeout=self.request_timeout_seconds,
            )
        response.raise_for_status()

    def _poll_extract_result(
        self,
        client: requests.Session,
        batch_id: str,
        data_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.poll_timeout_seconds
        last_state = "pending"
        while time.monotonic() < deadline:
            data = self._request_json(
                client,
                "GET",
                self._official_endpoint(f"/extract-results/batch/{batch_id}"),
            )
            result = self._find_result_entry(data, data_id)
            if result:
                state = str(result.get("state") or result.get("status") or "").strip().lower()
                if state and state != last_state:
                    logger.info(
                        "MinerU parsing state updated data_id=%s state=%s",
                        data_id,
                        state,
                    )
                last_state = state or last_state
                if state in _TERMINAL_SUCCESS_STATES:
                    return result
                if state in _TERMINAL_FAILURE_STATES:
                    raise RuntimeError(
                        f"MinerU parsing failed for {data_id}: {result.get('err_msg') or result}"
                    )
            time.sleep(self.poll_interval_seconds)

        raise TimeoutError(
            f"Timed out waiting for MinerU result batch_id={batch_id} data_id={data_id} state={last_state}"
        )

    def _download_content_list(
        self,
        client: requests.Session,
        result: dict[str, Any],
    ) -> _PartParseResult:
        zip_url = str(
            result.get("full_zip_url")
            or result.get("result_url")
            or result.get("zip_url")
            or ""
        ).strip()
        if not zip_url:
            raise RuntimeError(f"MinerU result does not contain a zip URL: {result}")

        response = client.get(zip_url, timeout=self.request_timeout_seconds)
        response.raise_for_status()
        return self._part_parse_result_from_archive_bytes(result, response.content)

    def _part_parse_result_from_archive_bytes(
        self,
        result: dict[str, Any],
        archive_bytes: bytes,
    ) -> _PartParseResult:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            content_name = self._find_archive_member(
                archive,
                [
                    "_content_list_v2.json",
                    "_content_list.json",
                    "content_list.json",
                    "content_list_v2.json",
                    "middle.json",
                    "full.md",
                ],
            )
            if content_name is None:
                raise RuntimeError(
                    f"MinerU result zip does not contain a supported content list file: {archive.namelist()}"
                )
            payload = archive.read(content_name)
            if content_name.endswith(".md"):
                markdown = payload.decode("utf-8", errors="ignore")
                return _PartParseResult(
                    content_list=self._markdown_to_content_list(markdown),
                    fallback_text=self._parse_markdown(markdown),
                    raw_result=result,
                    archive_bytes=archive_bytes,
                    archive_member_name=content_name,
                    archive_member_format="markdown",
                    archive_payload=markdown,
                )
            parsed = json.loads(payload.decode("utf-8"))
        return _PartParseResult(
            content_list=self._unwrap_content_list(parsed),
            fallback_text=self._archive_payload_to_text(parsed),
            raw_result=result,
            archive_bytes=archive_bytes,
            archive_member_name=content_name,
            archive_member_format="json",
            archive_payload=parsed,
        )

    def _parse_self_hosted_response(
        self,
        client: requests.Session,
        response: requests.Response,
        part: _PdfPart,
    ) -> _PartParseResult:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "zip" in content_type or response.content.startswith(b"PK\x03\x04"):
            return self._part_parse_result_from_archive_bytes(
                {"mode": "self_hosted", "file_name": part.path.name},
                response.content,
            )

        payload = response.json()
        data = self._self_hosted_result_payload(payload)
        return self._parse_self_hosted_payload_data(client, data, part)

    def _parse_self_hosted_payload_data(
        self,
        client: requests.Session,
        data: dict[str, Any],
        part: _PdfPart,
    ) -> _PartParseResult:
        zip_url = str(
            data.get("full_zip_url")
            or data.get("result_url")
            or data.get("zip_url")
            or ""
        ).strip()
        if zip_url:
            return self._download_content_list(client, data)

        content_list = data.get("content_list") or data.get("middle_json")
        if content_list:
            parsed_content = self._unwrap_content_list(content_list)
            return _PartParseResult(
                content_list=parsed_content,
                fallback_text=self._archive_payload_to_text(content_list),
                raw_result=data,
                archive_member_name="content_list.json",
                archive_member_format="json",
                archive_payload=content_list,
            )

        markdown = str(data.get("md_content") or data.get("full_md") or "").strip()
        if markdown:
            return _PartParseResult(
                content_list=self._markdown_to_content_list(markdown),
                fallback_text=self._parse_markdown(markdown),
                raw_result=data,
                archive_member_name=f"{part.path.stem}.md",
                archive_member_format="markdown",
                archive_payload=markdown,
            )

        raise RuntimeError(f"Self-hosted MinerU response is unsupported: {data}")

    def _merge_content_list(
        self,
        page_fragments: dict[int, list[str]],
        page_metadata: dict[int, dict[str, Any]],
        page_tables: dict[int, list[TableBlock]],
        part: _PdfPart,
        content_list: list[dict[str, Any]],
    ) -> int:
        current_local_page = 0
        merged_count = 0
        recent_text_lines: dict[int, list[str]] = {
            page_number: []
            for page_number in range(part.start_page, part.end_page + 1)
        }
        for index, item in enumerate(content_list):
            local_page = self._extract_page_index(item)
            if local_page is None:
                local_page = current_local_page
            else:
                current_local_page = local_page
            if local_page < 0 or local_page >= part.total_pages:
                continue
            global_page = part.start_page + local_page

            if self._looks_like_visual_block(item):
                page_metadata.setdefault(global_page, {})["mineru_visual_text"] = True

            block_type = str(item.get("type") or item.get("block_type") or "").strip().lower()
            if block_type == "table" or self._has_table_body(item):
                title_hint = self._context_title_hint(recent_text_lines.get(global_page, []))
                table_block = self._extract_table_block(
                    item,
                    global_page,
                    title_hint,
                    pre_text=self._context_title_hint(recent_text_lines.get(global_page, [])),
                    post_text=self._neighbor_text(content_list, index, local_page),
                )
                if table_block is not None:
                    page_tables.setdefault(global_page, []).append(table_block)
                    merged_count += 1
                    continue
                # Structured parse failed: keep the table's text but never leak raw HTML.
                fallback_text = self._table_fallback_text(item, title_hint)
                if fallback_text:
                    page_fragments.setdefault(global_page, []).append(fallback_text)
                    self._remember_context_lines(recent_text_lines.setdefault(global_page, []), fallback_text)
                    merged_count += 1
                continue

            text = self._extract_item_text(item)
            if not text:
                continue
            page_fragments.setdefault(global_page, []).append(text)
            self._remember_context_lines(recent_text_lines.setdefault(global_page, []), text)
            merged_count += 1
        return merged_count

    def _has_table_body(self, item: dict[str, Any]) -> bool:
        for source in (item, item.get("content")):
            if isinstance(source, dict) and source.get("table_body"):
                return True
        return False

    def _extract_table_block(
        self,
        item: dict[str, Any],
        global_page: int,
        title_hint: str = "",
        pre_text: str = "",
        post_text: str = "",
    ) -> TableBlock | None:
        body_html = self._table_body_html(item)
        if not body_html:
            return None
        parsed = parse_table_html(body_html)
        if parsed is None:
            return None
        header, rows = parsed
        caption = self._table_text_field(item, ("table_caption", "caption")) or title_hint
        footnote = self._table_text_field(item, ("table_footnote", "footnote"))
        return TableBlock(
            page_start=global_page,
            page_end=global_page,
            header=header,
            rows=rows,
            caption=caption,
            reference_text=pre_text or footnote,
            pre_text=pre_text or footnote,
            post_text=post_text,
        )

    def _table_body_html(self, item: dict[str, Any]) -> str:
        for source in (item, item.get("content")):
            if not isinstance(source, dict):
                continue
            value = source.get("table_body") or source.get("html")
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, list):
                parts = [part for part in value if isinstance(part, str) and part.strip()]
                if parts:
                    return "\n".join(parts)
        return ""

    def _table_text_field(self, item: dict[str, Any], keys: tuple[str, ...]) -> str:
        for source in (item, item.get("content")):
            if not isinstance(source, dict):
                continue
            for key in keys:
                text = self._coerce_table_text(source.get(key))
                if text:
                    return text
        return ""

    def _coerce_table_text(self, value: Any) -> str:
        if isinstance(value, str):
            return normalize_whitespace(value).strip()
        if isinstance(value, list):
            parts = [self._coerce_table_text(part) for part in value]
            return normalize_whitespace(" ".join(part for part in parts if part)).strip()
        return ""

    def _table_fallback_text(self, item: dict[str, Any], title_hint: str = "") -> str:
        """Build plain text for a table that could not be parsed structurally.

        Strips any HTML so raw ``<table>`` markup never reaches the index.
        """
        caption = self._table_text_field(item, ("table_caption", "caption")) or title_hint
        footnote = self._table_text_field(item, ("table_footnote", "footnote"))
        body_html = self._table_body_html(item)
        body_text = ""
        if body_html:
            stripped = re.sub(r"<[^>]+>", " ", body_html)
            body_text = self._sanitize_mineru_text(stripped)
        parts = [part for part in (caption, body_text, footnote) if part]
        return self._join_page_fragments(parts)

    def _remember_context_lines(self, recent_lines: list[str], text: str) -> None:
        for raw_line in text.splitlines():
            line = normalize_whitespace(raw_line)
            if not self._is_context_line(line):
                continue
            recent_lines.append(line)
        if len(recent_lines) > 8:
            del recent_lines[:-8]

    def _context_title_hint(self, recent_lines: list[str]) -> str:
        if not recent_lines:
            return ""
        return normalize_whitespace(" ".join(recent_lines[-2:])).strip()

    def _neighbor_text(
        self,
        content_list: list[dict[str, Any]],
        current_index: int,
        current_page: int,
    ) -> str:
        for item in content_list[current_index + 1 :]:
            page_index = self._extract_page_index(item)
            if page_index is not None and page_index != current_page:
                break
            block_type = str(item.get("type") or item.get("block_type") or "").strip().lower()
            if block_type in _IGNORED_BLOCK_TYPES:
                continue
            if block_type == "table" or self._has_table_body(item):
                continue
            text = self._extract_item_text(item)
            if text:
                return normalize_whitespace(text).strip()
        return ""

    def _is_title_hint_line(self, line: str) -> bool:
        compact = normalize_whitespace(line)
        if not compact or len(compact) < 2:
            return False
        if not self._is_context_line(compact):
            return False
        if len(compact) >= 48 and compact[-1] in "。！？；":
            return False
        return True

    def _is_context_line(self, line: str) -> bool:
        compact = normalize_whitespace(line)
        if not compact or len(compact) < 2:
            return False
        lowered = compact.lower()
        if lowered == "text":
            return False
        if re.fullmatch(r"page\s*\d+(?:\s*/\s*\d+)?", lowered):
            return False
        if re.fullmatch(r"\d+\s*/\s*\d+", compact):
            return False
        if compact.startswith(("表格：", "参考：", "表头：", "图片", "标题：", "前导描述：", "描述：")):
            return False
        normalized = compact.replace(" ", "")
        if normalized.startswith(("单位：", "单位:", "(单位：", "（单位：")):
            return False
        return True

    def _distribute_fallback_text(
        self,
        page_fragments: dict[int, list[str]],
        part: _PdfPart,
        text: str,
    ) -> None:
        compact = normalize_whitespace(text).strip()
        if not compact:
            return

        paragraphs = [
            normalize_whitespace(item).strip()
            for item in re.split(r"\n{2,}", text.replace("\r\n", "\n").replace("\r", "\n"))
            if normalize_whitespace(item).strip()
        ]
        if not paragraphs:
            page_fragments.setdefault(part.start_page, []).append(compact)
            return

        total_pages = max(part.total_pages, 1)
        target_chars = max(len(compact) // total_pages, 200)
        buckets = [""] * total_pages
        page_index = 0
        current_chars = 0
        for paragraph in paragraphs:
            if (
                buckets[page_index]
                and current_chars >= target_chars
                and page_index < total_pages - 1
            ):
                page_index += 1
                current_chars = 0
            buckets[page_index] = (
                f"{buckets[page_index]}\n\n{paragraph}".strip()
                if buckets[page_index]
                else paragraph
            )
            current_chars += len(paragraph)

        for offset, bucket in enumerate(buckets):
            if bucket.strip():
                page_fragments.setdefault(part.start_page + offset, []).append(bucket.strip())

    def _extract_page_index(self, item: dict[str, Any]) -> int | None:
        raw_value = item.get("page_idx")
        if raw_value is None:
            raw_value = item.get("page_no")
            if raw_value is not None:
                try:
                    return max(int(raw_value) - 1, 0)
                except (TypeError, ValueError):
                    return None
        if raw_value is None:
            raw_value = item.get("page_number") or item.get("page_num")
            if raw_value is not None:
                try:
                    return max(int(raw_value) - 1, 0)
                except (TypeError, ValueError):
                    return None
        if raw_value is None:
            page_info = item.get("page_info")
            if isinstance(page_info, dict):
                return self._extract_page_index(page_info)
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return None

    def _extract_item_text(self, item: dict[str, Any]) -> str:
        block_type = str(item.get("type") or item.get("block_type") or "").strip().lower()
        if block_type in _IGNORED_BLOCK_TYPES:
            return ""

        fragments: list[str] = []
        preferred_keys = (
            "text",
            "title",
            "section_title",
            "text_level",
            "table_caption",
            "table_body",
            "table_footnote",
            "image_caption",
            "image_footnote",
            "image_body",
            "equation_text",
            "latex",
            "html",
            "markdown",
            "content",
            "lines",
            "spans",
            "blocks",
            "items",
        )
        for key in preferred_keys:
            self._collect_text_fragments(item.get(key), fragments)

        if not fragments:
            for key, value in item.items():
                normalized_key = str(key).lower()
                if normalized_key in {"page_idx", "page_no", "type", "block_type", "bbox", "poly"}:
                    continue
                if any(
                    token in normalized_key
                    for token in ("text", "title", "caption", "body", "content", "markdown", "html")
                ):
                    self._collect_text_fragments(value, fragments)

        return self._join_page_fragments(fragments)

    def _looks_like_visual_block(self, item: dict[str, Any]) -> bool:
        block_type = str(item.get("type") or item.get("block_type") or "").strip().lower()
        if block_type in {"image", "chart", "figure", "table"}:
            return True
        if any(
            key in item
            for key in (
                "img_caption",
                "img_footnote",
                "chart_caption",
                "chart_footnote",
                "table_caption",
                "table_body",
                "table_footnote",
                "image_caption",
                "image_footnote",
                "image_body",
            )
        ):
            return True
        content = item.get("content")
        if isinstance(content, dict) and any(
            key in content
            for key in (
                "img_caption",
                "img_footnote",
                "chart_caption",
                "chart_footnote",
                "table_caption",
                "table_body",
                "table_footnote",
            )
        ):
            return True
        return False

    def _collect_text_fragments(self, value: Any, fragments: list[str]) -> None:
        if value is None:
            return
        if isinstance(value, str):
            cleaned = normalize_whitespace(value).strip()
            if cleaned:
                fragments.append(cleaned)
            return
        if isinstance(value, list):
            for item in value:
                self._collect_text_fragments(item, fragments)
            return
        if isinstance(value, dict):
            if any(
                key in value
                for key in (
                    "items",
                    "blocks",
                    "content_list",
                    "content_list_v2",
                    "children",
                    "para_blocks",
                    "preproc_blocks",
                    "images",
                    "tables",
                    "interline_equations",
                    "discarded_blocks",
                )
            ):
                for nested in self._iter_page_blocks(value):
                    self._collect_text_fragments(nested, fragments)
                return
            for item in self._dict_text_values(value):
                self._collect_text_fragments(item, fragments)

    def _join_page_fragments(self, fragments: list[str]) -> str:
        merged: list[str] = []
        seen: set[str] = set()
        for fragment in fragments:
            cleaned = normalize_whitespace(fragment).strip()
            if not cleaned or cleaned in seen:
                continue
            merged.append(cleaned)
            seen.add(cleaned)
        return "\n\n".join(merged)

    def _find_result_entry(self, data: dict[str, Any], data_id: str) -> dict[str, Any] | None:
        candidate_lists = [
            data.get("extract_result"),
            data.get("extract_results"),
            data.get("results"),
            data.get("files"),
        ]
        for candidate in candidate_lists:
            for item in self._ensure_list(candidate):
                if not isinstance(item, dict):
                    continue
                if str(item.get("data_id") or "").strip() == data_id:
                    return item

        for candidate in candidate_lists:
            for item in self._ensure_list(candidate):
                if isinstance(item, dict) and item.get("file_name") is not None:
                    return item
            for item in self._ensure_list(candidate):
                if isinstance(item, dict):
                    return item
        return None

    def _find_archive_member(
        self,
        archive: zipfile.ZipFile,
        suffixes: list[str],
    ) -> str | None:
        names = archive.namelist()
        for suffix in suffixes:
            for name in names:
                normalized = name.replace("\\", "/")
                if normalized.endswith(f"/{suffix}") or normalized == suffix or normalized.endswith(suffix):
                    return name
        markdown_members = [
            name
            for name in names
            if name.replace("\\", "/").lower().endswith(".md")
        ]
        if len(markdown_members) == 1:
            return markdown_members[0]
        return None

    def _unwrap_content_list(self, parsed: Any) -> list[dict[str, Any]]:
        if isinstance(parsed, list):
            return self._flatten_content_items(parsed)
        if isinstance(parsed, dict):
            for key in ("content_list", "content_list_v2", "items", "blocks"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return self._flatten_content_items(value)
            pages = parsed.get("pages")
            if isinstance(pages, list):
                return self._flatten_content_items(pages)
            pdf_info = parsed.get("pdf_info")
            if isinstance(pdf_info, list):
                return self._flatten_middle_pdf_info(pdf_info)
        raise RuntimeError("Unsupported MinerU content list structure")

    def _flatten_content_items(self, items: list[Any]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for default_page_index, item in enumerate(items):
            if isinstance(item, list):
                flattened.extend(
                    self._iter_page_blocks(
                        item,
                        default_page_index=default_page_index,
                    )
                )
                continue
            if not isinstance(item, dict):
                continue
            item_page_index = self._extract_page_index(item)
            page_blocks = list(
                self._iter_page_blocks(
                    item,
                    default_page_index=(
                        item_page_index if item_page_index is not None else default_page_index
                    ),
                )
            )
            if page_blocks:
                flattened.extend(page_blocks)
                continue
            if self._looks_like_content_block(item):
                flattened.append(item)
        return flattened

    def _flatten_middle_pdf_info(self, pages: list[Any]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for default_page_index, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            page_index = self._extract_page_index(page)
            if page_index is None:
                page_index = default_page_index
            for key in (
                "para_blocks",
                "preproc_blocks",
                "images",
                "tables",
                "interline_equations",
                "discarded_blocks",
            ):
                blocks = page.get(key)
                if blocks:
                    flattened.extend(
                        self._iter_page_blocks(
                            blocks,
                            default_page_index=page_index,
                        )
                    )
        return flattened

    def _iter_page_blocks(
        self,
        container: Any,
        *,
        default_page_index: int | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(container, list):
            flattened: list[dict[str, Any]] = []
            for block in container:
                if isinstance(block, (dict, list)):
                    flattened.extend(
                        self._iter_page_blocks(
                            block,
                            default_page_index=default_page_index,
                        )
                    )
            return flattened
        if not isinstance(container, dict):
            return []
        page_index = self._extract_page_index(container)
        if page_index is None:
            page_index = default_page_index

        blocks = (
            container.get("blocks")
            or container.get("items")
            or container.get("content_list")
            or container.get("content_list_v2")
            or container.get("children")
            or container.get("para_blocks")
            or container.get("preproc_blocks")
            or container.get("images")
            or container.get("tables")
            or container.get("interline_equations")
            or container.get("discarded_blocks")
        )
        flattened: list[dict[str, Any]] = []
        if blocks:
            for block in self._ensure_list(blocks):
                if not isinstance(block, (dict, list)):
                    continue
                nested = list(self._iter_page_blocks(block, default_page_index=page_index))
                if nested:
                    flattened.extend(nested)
            return flattened
        if self._looks_like_content_block(container):
            if page_index is not None and all(
                key not in container for key in ("page_idx", "page_no", "page_number", "page_num")
            ):
                container = {**container, "page_idx": page_index}
            flattened.append(container)
        return flattened

    def _looks_like_content_block(self, item: dict[str, Any]) -> bool:
        if any(key in item for key in ("page_idx", "page_no", "page_number", "page_num")):
            return True
        if any(
            key in item
            for key in (
                "text",
                "title",
                "content",
                "markdown",
                "html",
                "table_body",
                "table_caption",
                "image_caption",
                "latex",
                "lines",
                "spans",
                "title_content",
                "paragraph_content",
                "math_content",
                "code_content",
                "algorithm_content",
                "list_items",
            )
        ):
            return True
        block_type = str(item.get("type") or item.get("block_type") or "").strip()
        return bool(block_type)

    def _api_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "*/*",
        }
        if self.api_mode != "cloud":
            headers.pop("Authorization", None)
            return headers
        if self.user_token:
            headers["token"] = self.user_token
        return headers

    def _extract_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("code") not in (None, 0):
            raise RuntimeError(f"MinerU API call failed: {payload.get('msg') or payload}")
        if isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload

    def _request_json(
        self,
        client: requests.Session,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = self._api_headers()
        headers["Content-Type"] = "application/json"
        response = client.request(
            method=method,
            url=url,
            headers=headers,
            json=json,
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return self._extract_data(payload)

    def _self_hosted_result_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("code") not in (None, 0):
            raise RuntimeError(f"MinerU API call failed: {payload.get('msg') or payload}")

        data = payload.get("data")
        if isinstance(data, dict):
            payload = data

        if isinstance(payload.get("result"), dict):
            return payload["result"]
        if isinstance(payload.get("results"), list):
            for item in payload["results"]:
                if isinstance(item, dict):
                    return item
        return payload

    def _self_hosted_task_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("code") not in (None, 0):
            raise RuntimeError(f"MinerU API call failed: {payload.get('msg') or payload}")
        data = payload.get("data")
        if isinstance(data, dict):
            payload = data
        return payload

    def _self_hosted_form_data(self) -> dict[str, str]:
        return {
            "return_md": "true",
            "return_middle_json": "true",
            "return_content_list": "true",
            "return_images": "true",
            "response_format_zip": "true",
            "return_original_file": "false",
            "is_ocr": "true" if self.enable_ocr else "false",
            "lang": self.language,
        }

    def _ensure_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    def _extract_upload_url(self, entries: list[Any]) -> str:
        for entry in entries:
            if isinstance(entry, str):
                return entry.strip()
            if isinstance(entry, dict):
                upload_url = str(entry.get("upload_url") or entry.get("url") or "").strip()
                if upload_url:
                    return upload_url
        return ""

    def _delete_part_file(self, file_path: Path) -> None:
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            logger.exception("Failed to delete temporary MinerU split file: %s", file_path)

    def _prepare_debug_doc_dir(self, file_path: Path) -> Path:
        debug_doc_dir = self.debug_dir / file_path.stem
        if debug_doc_dir.exists():
            shutil.rmtree(debug_doc_dir, ignore_errors=True)
        debug_doc_dir.mkdir(parents=True, exist_ok=True)
        return debug_doc_dir

    def _save_part_debug_artifacts(
        self,
        debug_doc_dir: Path,
        file_path: Path,
        part_index: int,
        part: _PdfPart,
        parsed_part: _PartParseResult,
        debug_parts: list[dict[str, Any]],
    ) -> None:
        try:
            prefix = f"part_{part_index:02d}_{part.start_page:04d}_{part.end_page:04d}"
            zip_path = debug_doc_dir / f"{prefix}.zip"
            result_path = debug_doc_dir / f"{prefix}_result.json"
            flattened_path = debug_doc_dir / f"{prefix}_flattened_content_list.json"
            archive_ext = ".md" if parsed_part.archive_member_format == "markdown" else ".json"
            archive_path = debug_doc_dir / f"{prefix}_raw{archive_ext}"

            zip_path.write_bytes(parsed_part.archive_bytes)
            result_path.write_text(
                json.dumps(parsed_part.raw_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            flattened_path.write_text(
                json.dumps(parsed_part.content_list, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if parsed_part.archive_member_format == "markdown":
                archive_path.write_text(str(parsed_part.archive_payload or ""), encoding="utf-8")
            else:
                archive_path.write_text(
                    json.dumps(parsed_part.archive_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            debug_parts.append(
                {
                    "part_index": part_index,
                    "page_range": [part.start_page, part.end_page],
                    "source_file": part.path.name,
                    "doc_id": file_path.stem,
                    "zip_path": str(zip_path),
                    "result_path": str(result_path),
                    "raw_content_path": str(archive_path),
                    "flattened_content_list_path": str(flattened_path),
                    "archive_member_name": parsed_part.archive_member_name,
                    "archive_member_format": parsed_part.archive_member_format,
                    "flattened_block_count": len(parsed_part.content_list),
                }
            )
        except Exception:
            logger.exception("Failed to save MinerU debug artifacts for part=%s", part.path.name)

    def _save_debug_manifest(
        self,
        debug_doc_dir: Path,
        file_path: Path,
        debug_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        manifest = {
            "doc_id": file_path.stem,
            "source_path": str(file_path),
            "saved_at": datetime.now().isoformat(),
            "parts": debug_parts,
        }
        manifest_path = debug_doc_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "mineru_debug_dir": str(debug_doc_dir),
            "mineru_debug_manifest_path": str(manifest_path),
            "mineru_debug_part_count": len(debug_parts),
        }

    def _markdown_to_content_list(self, markdown: str) -> list[dict[str, Any]]:
        text = self._parse_markdown(markdown)
        if not text:
            return []
        return [{"page_idx": 0, "type": "text", "text": text}]

    def _archive_payload_to_text(self, parsed: Any) -> str:
        if isinstance(parsed, list):
            flattened = self._flatten_content_items(parsed)
            return self._parse_content_list(flattened)
        if isinstance(parsed, dict):
            pages = parsed.get("pages")
            if isinstance(pages, list):
                flattened = self._flatten_content_items(pages)
                return self._parse_content_list(flattened)
            content_v2 = parsed.get("content_list_v2")
            if isinstance(content_v2, list):
                flattened = self._flatten_content_items(content_v2)
                return self._parse_content_list(flattened)
            content = parsed.get("content_list")
            if isinstance(content, list):
                flattened = self._flatten_content_items(content)
                return self._parse_content_list(flattened)
        return ""

    def _parse_content_list(self, items: list[Any]) -> str:
        parts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            block_type = str(item.get("type") or "").strip().lower()
            if block_type in _IGNORED_BLOCK_TYPES:
                continue
            text = self._extract_text_from_legacy_item(item, block_type)
            if text:
                parts.append(text)
        return self._sanitize_mineru_text("\n\n".join(parts))

    def _parse_content_list_v2(self, pages: list[Any]) -> str:
        parts: list[str] = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            items = page.get("items") or page.get("content_list") or page.get("content_list_v2") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                block_type = str(item.get("type") or "").strip().lower()
                if block_type in _IGNORED_BLOCK_TYPES:
                    continue
                text = self._extract_text_from_v2_item(block_type, item.get("content"), item)
                if text:
                    parts.append(text)
        return self._sanitize_mineru_text("\n\n".join(parts))

    def _extract_text_from_legacy_item(self, item: dict[str, Any], block_type: str) -> str:
        if block_type == "text":
            return normalize_whitespace(str(item.get("text") or item.get("content") or "")).strip()
        if block_type == "equation":
            return normalize_whitespace(str(item.get("latex") or item.get("text") or "")).strip()
        if block_type == "list":
            return self._join_text_parts(item.get("list_items") or item.get("items") or [])
        if block_type in {"image", "chart"}:
            return self._join_text_parts(
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
            return self._join_text_parts(
                [
                    item.get("table_caption"),
                    item.get("table_body"),
                    item.get("table_footnote"),
                    item.get("content"),
                    item.get("text"),
                ]
            )
        if block_type == "code":
            return self._join_text_parts([item.get("code_caption"), item.get("code_body")])
        return self._join_text_parts(
            [
                item.get("text"),
                item.get("content"),
                item.get("title"),
                item.get("caption"),
                item.get("value"),
            ]
        )

    def _extract_text_from_v2_item(
        self,
        block_type: str,
        content: Any,
        item: dict[str, Any],
    ) -> str:
        if isinstance(content, dict):
            return self._join_text_parts(
                [
                    content.get("text"),
                    content.get("content"),
                    content.get("title"),
                    content.get("title_content"),
                    content.get("paragraph_content"),
                    content.get("caption"),
                    content.get("footnote"),
                    content.get("body"),
                    content.get("latex"),
                    content.get("math_content"),
                    content.get("value"),
                    content.get("page_header_content"),
                    content.get("page_footer_content"),
                    content.get("page_number_content"),
                    content.get("page_aside_text_content"),
                    content.get("page_footnote_content"),
                    content.get("code_content"),
                    content.get("code_body"),
                    content.get("code_caption"),
                    content.get("code_footnote"),
                    content.get("algorithm_content"),
                    content.get("algorithm_caption"),
                    content.get("algorithm_footnote"),
                    content.get("table_body"),
                    content.get("table_caption"),
                    content.get("table_footnote"),
                    content.get("image_body"),
                    content.get("chart_caption"),
                    content.get("chart_footnote"),
                    content.get("chart_body"),
                    content.get("img_caption"),
                    content.get("img_footnote"),
                    content.get("image_caption"),
                    content.get("image_footnote"),
                    content.get("list_items"),
                ]
            )
        if isinstance(content, list):
            return self._join_text_parts(content)
        if isinstance(content, str):
            return normalize_whitespace(content).strip()
        return self._extract_text_from_legacy_item(item, block_type)

    def _parse_markdown(self, markdown: str) -> str:
        text = markdown.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("<details>", "\n").replace("</details>", "\n")
        text = text.replace("<summary>", "").replace("</summary>", "\n")
        return self._sanitize_mineru_text(text)

    def _join_text_parts(self, values: Any) -> str:
        parts: list[str] = []
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, list):
                nested = self._join_text_parts(value)
                if nested:
                    parts.append(nested)
                continue
            if isinstance(value, dict):
                nested = self._join_text_parts(self._dict_text_values(value))
                if nested:
                    parts.append(nested)
                continue
            text = normalize_whitespace(str(value or "")).strip()
            if text:
                parts.append(text)
        return self._sanitize_mineru_text("\n".join(parts))

    def _dict_text_values(self, value: dict[str, Any]) -> list[Any]:
        ordered_keys = (
            "content",
            "text",
            "title",
            "caption",
            "footnote",
            "body",
            "value",
            "latex",
            "title_content",
            "paragraph_content",
            "math_content",
            "page_header_content",
            "page_footer_content",
            "page_number_content",
            "page_aside_text_content",
            "page_footnote_content",
            "code_content",
            "code_body",
            "code_caption",
            "code_footnote",
            "algorithm_content",
            "algorithm_caption",
            "algorithm_footnote",
            "table_body",
            "table_caption",
            "table_footnote",
            "image_body",
            "image_caption",
            "image_footnote",
            "chart_body",
            "chart_caption",
            "chart_footnote",
            "img_caption",
            "img_footnote",
            "list_items",
            "children",
            "lines",
            "spans",
            "items",
            "blocks",
        )
        extracted = [value[key] for key in ordered_keys if key in value]
        if extracted:
            return extracted
        return [
            item
            for key, item in value.items()
            if str(key).lower() not in {"type", "bbox", "poly", "path", "url", "score"}
        ]

    def _sanitize_mineru_text(self, text: str) -> str:
        normalized = (text or "").replace("\ufeff", "").replace("\u0000", "")
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"<!--.*?-->", " ", normalized, flags=re.S)
        normalized = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+", " ", normalized)
        normalized = re.sub(r"<img[^>]*>", " ", normalized, flags=re.I)
        normalized = re.sub(
            r"</?(?:figure|figcaption|table|tbody|thead|tr|td|th|span|div|p)[^>]*>",
            " ",
            normalized,
            flags=re.I,
        )
        normalized = re.sub(r"[^\S\n]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        lines = [line.strip() for line in normalized.split("\n") if line.strip()]
        if not lines:
            return ""
        line_counts = Counter(lines)
        cleaned_lines: list[str] = []
        previous = ""
        for line in lines:
            lowered = line.lower()
            if re.fullmatch(r"page\s*\d+(\s*/\s*\d+)?", lowered):
                continue
            if re.fullmatch(r"page\s*\d+\s*of\s*\d+", lowered):
                continue
            if re.fullmatch(r"第\s*\d+\s*页(\s*/\s*共?\s*\d+\s*页)?", line):
                continue
            if re.fullmatch(r"\d+\s*/\s*\d+", line):
                continue
            if len(line) <= 80 and line_counts.get(line, 0) >= 3:
                if re.search(r"(copyright|版权所有|保密|机密|confidential|内部资料)", line, re.I):
                    continue
                digit_ratio = sum(char.isdigit() for char in line) / max(1, len(line))
                if digit_ratio >= 0.35 or len(line) <= 24:
                    continue
            if line == previous:
                continue
            cleaned_lines.append(line)
            previous = line
        return normalize_whitespace("\n".join(cleaned_lines))
