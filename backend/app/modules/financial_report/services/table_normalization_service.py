from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.table_contract import (
    CanonicalCell,
    CanonicalTable,
    CanonicalTableQuality,
    CanonicalTableSource,
    TableNormalizationResult,
)


NUMERIC_RE = re.compile(r"^[\s,，\-—()（）.%％\d.]+$")


def load_tables_json(path: str | Path) -> list[Any]:
    return _load_json_list(path)


def load_merged_tables_json(path: str | Path) -> list[Any]:
    return _load_json_list(path)


def normalize_table_record(record: dict[str, Any], source_type: str) -> CanonicalTable:
    rows = _extract_rows(record)
    source_pages = _extract_source_pages(record)
    source = CanonicalTableSource(
        source_file=record.get("source_file", ""),
        source_pages=source_pages,
        parser_source=record.get("parser_source", ""),
        table_group_id=record.get("table_group_id", ""),
        source_type=source_type,
    )
    cells = _build_cells(rows)
    quality = _build_quality(record, rows, cells)
    table = CanonicalTable(
        table_id=record.get("table_id") or _table_id(source_type, source_pages, record.get("index", 0)),
        title=record.get("title", ""),
        source=source,
        quality=quality,
        cells=cells,
        raw_text=_rows_to_text(rows),
        raw_markdown=_rows_to_markdown(rows),
        candidate_statement_type="unknown",
    )
    table.candidate_statement_type = infer_candidate_statement_type(table)
    return table


def normalize_parse_lab_tables(manifest: dict[str, Any]) -> TableNormalizationResult:
    result = TableNormalizationResult(
        document_id=manifest.get("document_id", ""),
        task_id=manifest.get("task_id") or manifest.get("parse_task_id", ""),
        pdf_name=manifest.get("pdf_name", ""),
    )

    tables_path = manifest.get("tables_json_path") or manifest.get("tables_json")
    merged_tables_path = manifest.get("merged_tables_json_path") or manifest.get("merged_tables_json")
    quality_flags_path = manifest.get("quality_flags_path") or manifest.get("quality_flags_json")
    pages_path = manifest.get("pages_jsonl_path") or manifest.get("pages_jsonl")

    page_quality = _load_page_quality(pages_path)
    quality_flags = _load_quality_flags(quality_flags_path)

    try:
        for record in _iter_page_table_records(tables_path, page_quality, quality_flags):
            result.tables.append(normalize_table_record(record, "page_table"))
    except Exception as exc:  # pragma: no cover - defensive boundary for malformed runtime files.
        result.errors.append(f"tables_json normalization failed: {exc}")

    try:
        for record in _iter_merged_table_records(merged_tables_path, quality_flags):
            result.tables.append(normalize_table_record(record, "merged_cross_page_table"))
    except Exception as exc:  # pragma: no cover
        result.errors.append(f"merged_tables_json normalization failed: {exc}")

    if not result.tables:
        result.warnings.append("no canonical tables generated")
    return result


def infer_candidate_statement_type(table: CanonicalTable) -> str:
    text = (table.title + "\n" + table.raw_text).lower()
    if _contains_any(text, ["资产负债表", "資產負債表", "balance sheet", "资产总计", "負債合計", "所有者权益"]):
        return "balance_sheet"
    if _contains_any(text, ["利润表", "利潤表", "income statement", "损益", "損益", "营业收入", "營業收入", "净利润", "淨利潤"]):
        return "income_statement"
    if _contains_any(text, ["现金流量表", "現金流量表", "cash flow", "经营活动", "經營活動", "投资活动", "籌資活動"]):
        return "cash_flow_statement"
    if _contains_any(text, ["股东信息", "股東信息", "前十名股东", "前十名股東", "质押", "質押", "持股数量", "持股比例"]):
        return "shareholder_table"
    if _contains_any(text, ["分部", "分行业", "分產品", "收益明细", "收益明細", "segment", "revenue by"]):
        return "segment_revenue_table"
    return "unknown"


def _iter_page_table_records(
    tables_path: str | None,
    page_quality: dict[int, dict[str, Any]],
    quality_flags: dict[str, Any],
) -> list[dict[str, Any]]:
    if not tables_path:
        return []
    records: list[dict[str, Any]] = []
    for page_record in load_tables_json(tables_path):
        page_number = int(page_record.get("page_number") or 0)
        for index, table_rows in enumerate(page_record.get("tables") or []):
            page_info = page_quality.get(page_number, {})
            records.append(
                {
                    "index": index,
                    "source_file": str(tables_path),
                    "source_pages": [page_number] if page_number else [],
                    "parser_source": page_info.get("parser_source", ""),
                    "table_group_id": page_info.get("table_group_id", ""),
                    "table_intent_score": page_info.get("table_intent_score", 0.0),
                    "quality_flags": page_info.get("quality_flags", []) or quality_flags.get(str(page_number), []),
                    "table": table_rows,
                }
            )
    return records


def _iter_merged_table_records(merged_tables_path: str | None, quality_flags: dict[str, Any]) -> list[dict[str, Any]]:
    if not merged_tables_path:
        return []
    records: list[dict[str, Any]] = []
    for index, group in enumerate(load_merged_tables_json(merged_tables_path)):
        source_pages = [int(page) for page in group.get("source_pages") or [] if str(page).isdigit()]
        rows: list[list[Any]] = []
        for table_record in group.get("tables") or []:
            table_rows = table_record.get("table") or []
            if table_rows:
                rows.extend(table_rows)
        records.append(
            {
                "index": index,
                "source_file": str(merged_tables_path),
                "source_pages": source_pages,
                "parser_source": group.get("parser_source", ""),
                "table_group_id": group.get("table_group_id", ""),
                "continuation_confidence": group.get("continuation_confidence", 0.0),
                "quality_flags": [quality_flags.get(str(page), []) for page in source_pages],
                "table": rows,
            }
        )
    return records


def _extract_rows(record: dict[str, Any]) -> list[list[str]]:
    rows = record.get("table") or record.get("rows") or []
    normalized_rows: list[list[str]] = []
    for row in rows:
        if isinstance(row, list):
            normalized_rows.append([_normalize_text(cell) for cell in row])
        else:
            normalized_rows.append([_normalize_text(row)])
    return normalized_rows


def _extract_source_pages(record: dict[str, Any]) -> list[int]:
    pages = record.get("source_pages")
    if pages:
        return [int(page) for page in pages if str(page).isdigit()]
    page_number = record.get("page_number")
    return [int(page_number)] if page_number else []


def _build_cells(rows: list[list[str]]) -> list[CanonicalCell]:
    cells: list[CanonicalCell] = []
    for row_index, row in enumerate(rows):
        for col_index, text in enumerate(row):
            cells.append(
                CanonicalCell(
                    row_index=row_index,
                    col_index=col_index,
                    text=text,
                    normalized_text=_normalize_text(text),
                    is_header=row_index == 0,
                    confidence=1.0,
                )
            )
    return cells


def _build_quality(record: dict[str, Any], rows: list[list[str]], cells: list[CanonicalCell]) -> CanonicalTableQuality:
    row_count = len(rows)
    col_count = max((len(row) for row in rows), default=0)
    total_slots = row_count * col_count if row_count and col_count else 0
    empty_cells = sum(1 for cell in cells if not cell.normalized_text.strip())
    numeric_cells = sum(1 for cell in cells if _is_numeric_like(cell.normalized_text))
    return CanonicalTableQuality(
        has_header=bool(rows and any(cell.strip() for cell in rows[0])),
        row_count=row_count,
        col_count=col_count,
        empty_cell_ratio=round(empty_cells / total_slots, 4) if total_slots else 0.0,
        numeric_cell_ratio=round(numeric_cells / len(cells), 4) if cells else 0.0,
        continuation_confidence=float(record.get("continuation_confidence") or 0.0),
        table_intent_score=float(record.get("table_intent_score") or 0.0),
        quality_flags=record.get("quality_flags") or [],
    )


def _load_json_list(path: str | Path | None) -> list[Any]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


def _load_quality_flags(path: str | Path | None) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    pages = data.get("pages") if isinstance(data, dict) else {}
    return pages if isinstance(pages, dict) else {}


def _load_page_quality(path: str | Path | None) -> dict[int, dict[str, Any]]:
    if not path or not Path(path).exists():
        return {}
    page_quality: dict[int, dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            page_number = int(record.get("page_number") or 0)
            if page_number:
                page_quality[page_number] = record
    return page_quality


def _rows_to_text(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(row) for row in rows)


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    col_count = max(len(row) for row in rows)
    padded = [row + [""] * (col_count - len(row)) for row in rows]
    header = "| " + " | ".join(padded[0]) + " |"
    separator = "| " + " | ".join(["---"] * col_count) + " |"
    body = ["| " + " | ".join(row) + " |" for row in padded[1:]]
    return "\n".join([header, separator, *body])


def _normalize_text(value: Any) -> str:
    return str(value or "").replace("\r", "\n").strip()


def _is_numeric_like(text: str) -> bool:
    return bool(text and NUMERIC_RE.match(text) and any(char.isdigit() for char in text))


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def _table_id(source_type: str, source_pages: list[int], index: int) -> str:
    page_part = "_".join(str(page) for page in source_pages) or "unknown"
    return f"{source_type}_{page_part}_{index}"
