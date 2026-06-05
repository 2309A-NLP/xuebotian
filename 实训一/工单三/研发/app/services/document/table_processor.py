from __future__ import annotations

from app.models.domain import TableBlock
from app.utils.text import normalize_whitespace


def _clean_cell(value: str | None) -> str:
    if not value:
        return ""
    flattened = " ".join(part.strip() for part in value.splitlines() if part.strip())
    return normalize_whitespace(flattened)


def normalize_grid(grid: list[list[str | None]]) -> TableBlock | None:
    """Turn a raw pdfplumber grid into a normalized table block."""
    cleaned: list[list[str]] = []
    for raw_row in grid:
        row = [_clean_cell(cell) for cell in raw_row]
        if any(cell for cell in row):
            cleaned.append(row)
    if not cleaned:
        return None

    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]

    header_index = _find_header_index(cleaned)
    header = cleaned[header_index]
    rows = cleaned[header_index + 1 :]
    if rows and _looks_like_subheader(rows[0]):
        header = _merge_multirow_header(header, rows[0])
        rows = rows[1:]
    else:
        header = _fill_header_spans(header)
    rows = [row for row in rows if not _headers_match(header, row)]
    if not _is_usable_table(header, rows):
        return None
    return TableBlock(page_start=0, page_end=0, header=header, rows=rows)


def _is_usable_table(header: list[str], rows: list[list[str]]) -> bool:
    """Reject layout fragments that pdfplumber often reports as tables."""
    non_empty_header = [cell for cell in header if cell.strip()]
    if len(header) < 2 or len(non_empty_header) < 2:
        return False
    if not rows:
        return False

    populated_rows = [row for row in rows if sum(1 for cell in row if cell.strip()) >= 2]
    if not populated_rows:
        return False

    compact_header = "".join(non_empty_header).replace(" ", "")
    if compact_header in {"指", "序号"} or set(non_empty_header) <= {"指"}:
        return False

    repeated_marker_cells = 0
    total_cells = 0
    for row in rows:
        for cell in row:
            value = cell.strip()
            if not value:
                continue
            total_cells += 1
            if value in {"指", "-"}:
                repeated_marker_cells += 1
    if total_cells and repeated_marker_cells / total_cells > 0.5:
        return False

    return True


def _find_header_index(rows: list[list[str]]) -> int:
    """Prefer the first row that looks like column names."""
    for index, row in enumerate(rows[:3]):
        non_empty = sum(1 for cell in row if cell.strip())
        if non_empty >= 2:
            return index
    return 0


def _headers_match(left: list[str], right: list[str]) -> bool:
    if len(left) != len(right):
        return False
    return [_cell_key(cell) for cell in left] == [_cell_key(cell) for cell in right]


def _looks_like_subheader(row: list[str]) -> bool:
    values = [cell.strip() for cell in row if cell.strip()]
    if len(values) < 2:
        return False
    markers = {"金额", "占比", "比例", "数量", "单价", "均价", "收入", "成本", "毛利率"}
    marker_hits = sum(1 for value in values if value in markers)
    return marker_hits / len(values) >= 0.5


def _merge_multirow_header(parent: list[str], child: list[str]) -> list[str]:
    filled_parent = _fill_header_spans(parent)
    width = max(len(filled_parent), len(child))
    filled_parent = filled_parent + [""] * (width - len(filled_parent))
    child = child + [""] * (width - len(child))

    merged: list[str] = []
    for parent_cell, child_cell in zip(filled_parent, child, strict=False):
        parent_cell = parent_cell.strip()
        child_cell = child_cell.strip()
        if parent_cell and child_cell and child_cell not in parent_cell:
            merged.append(f"{parent_cell}{child_cell}")
        else:
            merged.append(parent_cell or child_cell)
    return merged


def _fill_header_spans(header: list[str]) -> list[str]:
    filled: list[str] = []
    last = ""
    for cell in header:
        value = cell.strip()
        if value:
            last = value
            filled.append(value)
        else:
            filled.append(last)
    return filled


def _cell_key(value: str) -> str:
    return normalize_whitespace(value).replace(" ", "")


def _is_continuation(previous: TableBlock, candidate: TableBlock) -> bool:
    """Decide whether a later table continues the previous table."""
    if candidate.caption.strip():
        return False
    return previous.column_count == candidate.column_count


def merge_cross_page_tables(tables: list[TableBlock]) -> list[TableBlock]:
    """Merge adjacent page tables that appear to be one continuous table."""
    merged: list[TableBlock] = []
    for table in tables:
        if not merged:
            merged.append(table)
            continue

        previous = merged[-1]
        adjacent_pages = previous.page_end < table.page_start <= previous.page_end + 1
        if adjacent_pages and _is_continuation(previous, table):
            if _headers_match(previous.header, table.header):
                data_rows = table.rows
            else:
                data_rows = [table.header, *table.rows]
            previous.rows.extend(data_rows)
            previous.page_end = max(previous.page_end, table.page_end)
        else:
            merged.append(table)
    return merged


def serialize_table(table: TableBlock) -> str:
    """Render a table as retrieval-friendly key-value text."""
    column_names = [
        name.strip() if name.strip() else f"列{index + 1}"
        for index, name in enumerate(table.header)
    ]

    lines: list[str] = []
    caption = table.caption.strip()
    if caption:
        if _is_unit_note(caption):
            lines.append(caption)
        else:
            lines.append(f"表格：{caption}")
    if table.page_start:
        lines.append(f"页码：{format_page_range(table.page_start, table.page_end)}")
    if any(column_names):
        lines.append(f"表头：{'，'.join(column_names)}")

    for row_number, row in enumerate(table.rows, start=1):
        relation_line = _serialize_relation_row(caption, column_names, row, row_number)
        if relation_line:
            lines.append(relation_line)
            continue
        enterprise_relation_line = _serialize_enterprise_relation_row(
            caption, column_names, row, row_number
        )
        if enterprise_relation_line:
            lines.append(enterprise_relation_line)
            continue

        pairs = []
        for index, name in enumerate(column_names):
            value = row[index].strip() if index < len(row) else ""
            if value:
                pairs.append(f"{name}：{value}")
        if pairs:
            lines.append(f"第{row_number}行：" + "，".join(pairs))
    return "\n".join(lines)


def _serialize_relation_row(
    caption: str,
    column_names: list[str],
    row: list[str],
    row_number: int,
) -> str:
    if "存在控制关系的关联方" not in caption:
        return ""
    compact_header = "".join(column_names)
    if not all(key in compact_header for key in ("关联方名称", "持股比例", "与本公司关系")):
        return ""

    values = [cell.strip() for cell in row if cell and cell.strip()]
    if len(values) != 3:
        return ""
    name, ratio, relation = values
    if "%" not in ratio:
        return ""
    return (
        f"第{row_number}行："
        f"关联方名称：{name}，持股比例：{ratio}，与本公司关系：{relation}"
    )


def _serialize_enterprise_relation_row(
    caption: str,
    column_names: list[str],
    row: list[str],
    row_number: int,
) -> str:
    if "不存在控制关系的关联方" not in caption:
        return ""
    compact_header = "".join(column_names)
    if not all(key in compact_header for key in ("企业名称", "与本公司关系")):
        return ""

    values = [cell.strip() for cell in row if cell and cell.strip()]
    if len(values) != 2:
        return ""
    name, relation = values
    return f"第{row_number}行：企业名称：{name}，与本公司关系：{relation}"


def format_page_range(page_start: int, page_end: int) -> str:
    if page_end and page_end != page_start:
        return f"{page_start}-{page_end}"
    return str(page_start)


def _is_unit_note(text: str) -> bool:
    compact = text.replace(" ", "")
    return compact.startswith(("单位：", "单位:", "(单位：", "（单位："))
