"""Verify the MinerU table path: HTML parse -> cross-page merge -> whole chunk.

Run from the project root:

    python scripts/verify_table_pipeline.py

The script uses no network and no external services. It feeds sample MinerU
table HTML through the real pipeline helpers and asserts that:

1. ``parse_table_html`` parses headers (including colspan) and data rows.
2. A caption-less table on the next page merges into the previous one.
3. ``DocumentChunker._chunk_table`` emits exactly one chunk per table,
   regardless of size (tables are never split).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.domain import TableBlock
from app.services.document.chunk_models import _Counter
from app.services.document.chunker import DocumentChunker
from app.services.document.mineru_parser import parse_table_html
from app.services.document.table_processor import merge_cross_page_tables

# A table whose first body row is a sub-header ("金额"/"占比") that should merge
# into the column names, exercising the multi-row header path in normalize_grid.
TABLE_PAGE_1 = """
<table>
  <tr><td>关联方名称</td><td>持股比例</td><td>与本公司关系</td></tr>
  <tr><td>甲投资公司</td><td>35%</td><td>控股股东</td></tr>
  <tr><td>乙合伙企业</td><td>12%</td><td>重要股东</td></tr>
</table>
"""

# Same columns, no caption -> should be treated as a continuation of page 1.
TABLE_PAGE_2 = """
<table>
  <tr><td>丙基金</td><td>8%</td><td>财务投资者</td></tr>
  <tr><td>丁个人</td><td>5%</td><td>董事</td></tr>
</table>
"""

# A colspan header to confirm spanned cells are replicated across columns.
TABLE_COLSPAN = """
<table>
  <tr><td colspan="2">营业收入</td><td>毛利率</td></tr>
  <tr><td>境内</td><td>境外</td><td>合计</td></tr>
  <tr><td>1,000</td><td>200</td><td>45%</td></tr>
</table>
"""


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" :: {detail}" if detail else ""))
    if not condition:
        raise AssertionError(label)


def verify_parse() -> None:
    parsed = parse_table_html(TABLE_PAGE_1)
    _check("parse_table_html returns a table", parsed is not None)
    header, rows = parsed
    _check("header has 3 columns", len(header) == 3, str(header))
    _check("parsed 2 data rows", len(rows) == 2, str(rows))
    _check(
        "first row content preserved",
        rows[0][:3] == ["甲投资公司", "35%", "控股股东"],
        str(rows[0]),
    )


def verify_colspan() -> None:
    parsed = parse_table_html(TABLE_COLSPAN)
    _check("colspan table parses", parsed is not None)
    header, rows = parsed
    _check("colspan expands header to 3 columns", len(header) == 3, str(header))
    _check("colspan data row intact", rows[-1][:3] == ["1,000", "200", "45%"], str(rows))


def verify_merge() -> None:
    p1 = parse_table_html(TABLE_PAGE_1)
    p2 = parse_table_html(TABLE_PAGE_2)
    block1 = TableBlock(
        page_start=10, page_end=10, header=p1[0], rows=p1[1], caption="主要关联方持股情况"
    )
    block2 = TableBlock(page_start=11, page_end=11, header=p2[0], rows=p2[1], caption="")
    merged = merge_cross_page_tables([block1, block2])
    _check("two page tables merge into one", len(merged) == 1, f"got {len(merged)} blocks")
    combined = merged[0]
    _check("merged page range spans 10-11", (combined.page_start, combined.page_end) == (10, 11))
    _check("merged rows total 4", len(combined.rows) == 4, str(combined.rows))


def verify_whole_chunk() -> None:
    # Build a very large table (well over CHUNK_SIZE) to prove it is never split.
    big_rows = [[f"行{i}名称示例文本内容", f"{i}%", "财务投资者说明文字"] for i in range(300)]
    table = TableBlock(
        page_start=5,
        page_end=6,
        header=["关联方名称", "持股比例", "与本公司关系"],
        rows=big_rows,
        caption="超大关联方表格",
    )
    chunker = DocumentChunker(chunk_size=700, chunk_overlap=120)
    chunks = chunker.split(
        doc_id="doc_test",
        file_name="sample.pdf",
        body_pages=[(5, "")],
        tables=[table],
        images=None,
    )
    table_chunks = [c for c in chunks if c.metadata.get("type") == "table"]
    _check(
        "large table produces exactly one chunk",
        len(table_chunks) == 1,
        f"got {len(table_chunks)} table chunks (chunk text len={len(table_chunks[0].text) if table_chunks else 0})",
    )
    text = table_chunks[0].text
    _check("chunk text far exceeds chunk_size (not split)", len(text) > 700, f"len={len(text)}")
    _check("first row present in chunk", "行0名称示例文本内容" in text)
    _check("last row present in chunk", "行299名称示例文本内容" in text)


def main() -> int:
    print("== Verifying MinerU table pipeline ==")
    verify_parse()
    verify_colspan()
    verify_merge()
    verify_whole_chunk()
    print("\nAll table-pipeline checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
