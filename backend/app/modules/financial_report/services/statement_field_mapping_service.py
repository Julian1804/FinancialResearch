from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.extraction_contract import FinancialExtractionCandidateSet
from backend.app.modules.financial_report.schemas.statement_field_contract import (
    StatementFieldCandidate,
    StatementMappingResult,
    StatementMappingRule,
)
from backend.app.modules.financial_report.schemas.table_contract import (
    CanonicalTable,
    CanonicalTableQuality,
)
from backend.app.modules.financial_report.services.financial_table_candidate_service import (
    CANDIDATE_OUTPUT_DIR,
    build_extraction_candidate_set,
    load_normalized_tables_for_document,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
RULES_PATH = PROJECT_ROOT / "backend" / "app" / "modules" / "financial_report" / "config" / "statement_mapping_rules.json"
MAPPING_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "financial_report" / "statement_mapping"
SUPPORTED_STATEMENT_TYPES = {"balance_sheet", "income_statement", "cash_flow_statement", "shareholder_table"}
MATCH_PRIORITY = {"exact_aliases": 3, "phrase_aliases": 2, "weak_aliases": 1}
SOURCE_PRIORITY = {"page_table": 2, "merged_cross_page_table": 1}
NUMBER_RE = re.compile(r"^\(?-?[\d,，]+(?:\.\d+)?\)?%?$")


def load_statement_mapping_rules() -> dict[str, list[StatementMappingRule]]:
    with RULES_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    rules: dict[str, list[StatementMappingRule]] = {}
    for statement_type, items in raw.items():
        rules[statement_type] = [StatementMappingRule(statement_type=statement_type, **item) for item in items]
    return rules


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def normalize_number(value_text: str) -> float | None:
    text = str(value_text or "").strip()
    if not text:
        return None
    text = text.replace(",", "").replace("，", "").replace("%", "").replace("％", "")
    is_negative = (text.startswith("(") and text.endswith(")")) or (text.startswith("（") and text.endswith("）"))
    text = text.strip("()（）")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if is_negative else value


def classify_alias_match(raw_text: str, rule: StatementMappingRule) -> str:
    text = normalize_text(raw_text)
    if not text:
        return ""
    for alias in rule.exact_aliases:
        if text == normalize_text(alias):
            return "exact_aliases"
    for alias in rule.phrase_aliases:
        normalized_alias = normalize_text(alias)
        if normalized_alias and normalized_alias in text:
            return "phrase_aliases"
    for alias in rule.weak_aliases:
        normalized_alias = normalize_text(alias)
        if normalized_alias and normalized_alias in text:
            return "weak_aliases"
    return ""


def is_likely_row_header(cell: str, table: CanonicalTable, row_index: int, col_index: int) -> bool:
    if row_index in detect_header_rows(table):
        return False
    if col_index > 1:
        return False
    text = normalize_text(cell)
    if not text or normalize_number(text) is not None:
        return False
    row = _table_rows(table)[row_index]
    right_cells = row[col_index + 1 :]
    numeric_right = sum(1 for item in right_cells if normalize_number(item) is not None)
    return col_index == 0 or numeric_right > 0


def is_likely_value_cell(cell: str, table: CanonicalTable, row_index: int, col_index: int) -> bool:
    if row_index in detect_header_rows(table):
        return False
    if col_index == 0:
        return False
    if table.candidate_statement_type == "shareholder_table":
        return bool(str(cell or "").strip())
    return normalize_number(cell) is not None


def detect_header_rows(table: CanonicalTable) -> list[int]:
    rows = _table_rows(table)
    header_rows: list[int] = []
    for row_index, row in enumerate(rows[:3]):
        normalized_row = normalize_text(" ".join(row))
        numeric_count = sum(1 for cell in row if normalize_number(cell) is not None)
        if _looks_like_period(normalized_row) or numeric_count <= max(1, len(row) // 3):
            header_rows.append(row_index)
    return header_rows or ([0] if rows else [])


def detect_period_columns(table: CanonicalTable) -> dict[int, str]:
    rows = _table_rows(table)
    if not rows:
        return {}
    period_by_col: dict[int, str] = {}
    for row_index in detect_header_rows(table):
        if row_index >= len(rows):
            continue
        for col_index, cell in enumerate(rows[row_index]):
            text = str(cell or "").strip()
            if _looks_like_period(normalize_text(text)):
                period_by_col[col_index] = text or "unknown_period"
    return period_by_col


def detect_unit_and_currency(table: CanonicalTable, surrounding_text: str | None = None) -> tuple[str, str]:
    text = normalize_text((surrounding_text or "") + "\n" + table.title + "\n" + table.raw_text)
    unit = "unknown"
    currency = "unknown"
    if any(marker in text for marker in ["百万元", "百萬元", "million"]):
        unit = "million"
    elif any(marker in text for marker in ["万元", "萬元"]):
        unit = "ten_thousand"
    elif "千元" in text:
        unit = "thousand"
    elif "元" in text:
        unit = "yuan"

    if any(marker in text for marker in ["人民币", "人民幣", "rmb", "cny"]):
        currency = "CNY"
    elif any(marker in text for marker in ["港币", "港幣", "hkd"]):
        currency = "HKD"
    elif any(marker in text for marker in ["美元", "usd"]):
        currency = "USD"
    return unit, currency


def calculate_mapping_confidence(
    match_type: str,
    table_quality: CanonicalTableQuality,
    period_detected: bool,
    unit_detected: bool,
    source_type: str,
    value_parse_failed: bool = False,
) -> float:
    score = {"exact_aliases": 0.82, "phrase_aliases": 0.72, "weak_aliases": 0.55}.get(match_type, 0.45)
    if period_detected:
        score += 0.05
    else:
        score -= 0.08
    if unit_detected:
        score += 0.04
    else:
        score -= 0.05
    if table_quality.numeric_cell_ratio >= 0.15:
        score += 0.04
    if source_type == "merged_cross_page_table":
        score -= 0.03
    if value_parse_failed:
        score -= 0.18
    return round(max(0.0, min(score, 1.0)), 4)


def map_table_fields(table: CanonicalTable, rules: dict[str, list[StatementMappingRule]]) -> list[StatementFieldCandidate]:
    statement_type = table.candidate_statement_type
    if statement_type not in SUPPORTED_STATEMENT_TYPES:
        return []
    rows = _table_rows(table)
    if not rows:
        return []
    unit, currency = detect_unit_and_currency(table)
    period_by_col = detect_period_columns(table)
    mapped: list[StatementFieldCandidate] = []

    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row[:2]):
            if not is_likely_row_header(cell, table, row_index, col_index):
                continue
            for rule in rules.get(statement_type, []):
                match_type = classify_alias_match(cell, rule)
                if not match_type:
                    continue
                if match_type == "weak_aliases" and not _allow_weak_alias_match(row, statement_type):
                    continue
                if not any(is_likely_value_cell(value_cell, table, row_index, value_col) for value_col, value_cell in enumerate(row[col_index + 1 :], start=col_index + 1)):
                    continue
                value_col, raw_value = _find_value_in_row(row, rule.value_type)
                mapped.append(
                    _field_candidate(
                        table=table,
                        rule=rule,
                        raw_field_name=cell,
                        raw_value=raw_value,
                        source_row_index=row_index,
                        source_col_index=value_col,
                        unit=unit,
                        currency=currency,
                        period_label=period_by_col.get(value_col, "unknown_period"),
                        mapping_reason=f"row_alias_match:{match_type}",
                        match_type=match_type,
                    )
                )

    if statement_type == "shareholder_table":
        mapped.extend(_map_shareholder_columns(table, rules.get(statement_type, []), unit, currency, period_by_col, len(mapped)))
    return mapped


def build_statement_mapping_result(document_id: str, allow_override: bool = False) -> StatementMappingResult:
    candidate_set = _load_or_build_candidate_set(document_id, allow_override=allow_override)
    if candidate_set.extraction_mode == "blocked" and not allow_override:
        result = StatementMappingResult(
            document_id=document_id,
            task_id=candidate_set.task_id,
            pdf_name=candidate_set.pdf_name,
            extraction_mode="blocked",
            warnings=list(candidate_set.warnings),
            errors=list(candidate_set.errors),
        )
        _write_mapping_result(result, "blocked_statement_mapping")
        return result

    normalization = load_normalized_tables_for_document(document_id)
    table_by_id = {table.table_id: table for table in normalization.tables}
    rules = load_statement_mapping_rules()
    fields: list[StatementFieldCandidate] = []
    warnings = list(candidate_set.warnings)
    errors = list(candidate_set.errors) + list(normalization.errors)

    for candidate in candidate_set.candidates:
        if candidate.candidate_statement_type not in SUPPORTED_STATEMENT_TYPES:
            continue
        table = table_by_id.get(candidate.table_id)
        if not table:
            errors.append(f"canonical table not found for candidate table_id={candidate.table_id}")
            continue
        for field in map_table_fields(table, rules):
            field.document_id = document_id
            field.task_id = candidate_set.task_id
            fields.append(field)

    deduped_fields, discarded_count, discarded_examples = deduplicate_field_candidates(fields)
    if discarded_count:
        warnings.append(f"discarded_candidates_count={discarded_count}")
    result = StatementMappingResult(
        document_id=document_id,
        task_id=candidate_set.task_id,
        pdf_name=candidate_set.pdf_name,
        extraction_mode=candidate_set.extraction_mode,
        fields=deduped_fields,
        warnings=warnings,
        errors=errors,
        discarded_candidates_count=discarded_count,
        discarded_candidate_examples=discarded_examples,
    )
    suffix = "statement_field_candidates_refined" if result.extraction_mode != "blocked" else "blocked_statement_mapping"
    _write_mapping_result(result, suffix)
    return result


def deduplicate_field_candidates(
    fields: list[StatementFieldCandidate],
) -> tuple[list[StatementFieldCandidate], int, list[dict[str, Any]]]:
    best_by_key: dict[tuple[str, str, tuple[int, ...]], StatementFieldCandidate] = {}
    discarded: list[StatementFieldCandidate] = []
    for field in fields:
        key = (field.canonical_field_name, field.period_label, tuple(field.source_pages))
        existing = best_by_key.get(key)
        if not existing:
            best_by_key[key] = field
            continue
        if _field_rank(field) > _field_rank(existing):
            discarded.append(existing)
            best_by_key[key] = field
        else:
            discarded.append(field)
    examples = [
        {
            "canonical_field_name": item.canonical_field_name,
            "raw_field_name": item.raw_field_name,
            "raw_value": item.raw_value,
            "table_id": item.table_id,
            "confidence": item.confidence,
            "mapping_reason": item.mapping_reason,
        }
        for item in discarded[:10]
    ]
    return list(best_by_key.values()), len(discarded), examples


def _map_shareholder_columns(
    table: CanonicalTable,
    rules: list[StatementMappingRule],
    unit: str,
    currency: str,
    period_by_col: dict[int, str],
    start_index: int,
) -> list[StatementFieldCandidate]:
    rows = _table_rows(table)
    if len(rows) < 2:
        return []
    header = rows[0]
    mapped: list[StatementFieldCandidate] = []
    for col_index, header_text in enumerate(header):
        for rule in rules:
            match_type = classify_alias_match(header_text, rule)
            if not match_type or match_type == "weak_aliases":
                continue
            for row_index, row in enumerate(rows[1:], start=1):
                raw_value = row[col_index] if col_index < len(row) else ""
                if not raw_value:
                    continue
                mapped.append(
                    _field_candidate(
                        table=table,
                        rule=rule,
                        raw_field_name=header_text,
                        raw_value=raw_value,
                        source_row_index=row_index,
                        source_col_index=col_index,
                        unit=unit,
                        currency=currency,
                        period_label=period_by_col.get(col_index, "unknown_period"),
                        mapping_reason=f"shareholder_column_alias_match:{match_type}",
                        match_type=match_type,
                        sequence_offset=start_index + len(mapped),
                    )
                )
    return mapped


def _field_candidate(
    table: CanonicalTable,
    rule: StatementMappingRule,
    raw_field_name: str,
    raw_value: str,
    source_row_index: int,
    source_col_index: int,
    unit: str,
    currency: str,
    period_label: str,
    mapping_reason: str,
    match_type: str,
    sequence_offset: int = 0,
) -> StatementFieldCandidate:
    normalized_value = normalize_number(raw_value) if rule.value_type == "number" else None
    value_parse_failed = rule.value_type == "number" and normalized_value is None
    confidence = calculate_mapping_confidence(
        match_type=match_type,
        table_quality=table.quality,
        period_detected=period_label != "unknown_period",
        unit_detected=unit != "unknown",
        source_type=table.source.source_type,
        value_parse_failed=value_parse_failed,
    )
    requires_review = (
        table.source.source_type == "merged_cross_page_table"
        or not raw_value
        or _is_suspicious_value(raw_value, rule.value_type, normalized_value)
        or period_label == "unknown_period"
        or unit == "unknown"
        or match_type == "weak_aliases"
        or confidence < 0.75
    )
    return StatementFieldCandidate(
        field_id=f"{table.table_id}_{rule.canonical_field_name}_{source_row_index}_{source_col_index}_{sequence_offset}",
        document_id="",
        task_id="",
        table_id=table.table_id,
        candidate_statement_type=table.candidate_statement_type,
        canonical_field_name=rule.canonical_field_name,
        raw_field_name=raw_field_name,
        raw_value=raw_value,
        normalized_value=normalized_value,
        unit=unit,
        currency=currency,
        period_label=period_label or "unknown_period",
        source_pages=table.source.source_pages,
        source_row_index=source_row_index,
        source_col_index=source_col_index,
        table_group_id=table.source.table_group_id,
        confidence=confidence,
        mapping_reason=mapping_reason,
        requires_review=requires_review,
    )


def _load_or_build_candidate_set(document_id: str, allow_override: bool) -> FinancialExtractionCandidateSet:
    suffix = "financial_table_candidates" if allow_override else "blocked_extraction"
    path = CANDIDATE_OUTPUT_DIR / f"{document_id}.{suffix}.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            return FinancialExtractionCandidateSet(**json.load(handle))
    return build_extraction_candidate_set(document_id, allow_override=allow_override)


def _table_rows(table: CanonicalTable) -> list[list[str]]:
    rows: dict[int, dict[int, str]] = defaultdict(dict)
    for cell in table.cells:
        rows[cell.row_index][cell.col_index] = cell.normalized_text or cell.text
    result: list[list[str]] = []
    for row_index in sorted(rows):
        row = rows[row_index]
        max_col = max(row) if row else -1
        result.append([row.get(col_index, "") for col_index in range(max_col + 1)])
    return result


def _find_value_in_row(row: list[str], value_type: str) -> tuple[int, str]:
    for col_index in range(1, len(row)):
        value = row[col_index]
        if value_type == "number" and normalize_number(value) is not None:
            return col_index, value
        if value_type == "text" and value:
            return col_index, value
    return (1, row[1] if len(row) > 1 else "")


def _allow_weak_alias_match(row: list[str], statement_type: str) -> bool:
    row_text = normalize_text(" ".join(row[:2]))
    has_numeric_value = any(normalize_number(cell) is not None for cell in row[1:])
    if not has_numeric_value:
        return False
    strong_context = {
        "income_statement": ["营业", "主营", "净利润", "经营", "operating"],
        "balance_sheet": ["合计", "总计", "余额"],
        "cash_flow_statement": ["现金流量", "活动", "cashflow"],
        "shareholder_table": ["股东", "持股", "质押"],
    }
    return any(normalize_text(marker) in row_text for marker in strong_context.get(statement_type, []))


def _looks_like_period(text: str) -> bool:
    markers = [
        "本期",
        "上期",
        "本年",
        "上年",
        "期末",
        "期初",
        "报告期",
        "currentperiod",
        "previousperiod",
        "yearended",
        "asat",
        "2025",
        "2024",
        "2023",
    ]
    return any(marker in text for marker in markers)


def _is_suspicious_value(raw_value: str, value_type: str, normalized_value: float | None) -> bool:
    text = str(raw_value or "").strip()
    if not text:
        return True
    if "\n" in text and len(text) <= 4:
        return True
    if value_type == "number" and normalized_value is None:
        return True
    if value_type == "number" and not NUMBER_RE.match(text.replace(" ", "")):
        return True
    return False


def _field_rank(field: StatementFieldCandidate) -> tuple[int, int, float]:
    match_type = field.mapping_reason.split(":")[-1]
    return (
        MATCH_PRIORITY.get(match_type, 0),
        SOURCE_PRIORITY.get(field.source_pages and "page_table" or "", 0),
        field.confidence,
    )


def _write_mapping_result(result: StatementMappingResult, suffix: str) -> Path:
    MAPPING_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MAPPING_OUTPUT_DIR / f"{result.document_id}.{suffix}.json"
    output_path.write_text(json.dumps(_model_dump(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
