from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.document_role_detector import assess_document_role
from backend.app.modules.financial_report.services.financial_table_candidate_service import (
    CANDIDATE_OUTPUT_DIR,
    build_extraction_candidate_set,
)
from backend.app.modules.financial_report.services.minimal_financial_extraction_service import (
    build_minimal_financial_extraction,
)
from backend.app.modules.financial_report.services.parsed_document_registry import load_registry_entries
from backend.app.modules.financial_report.services.statement_field_mapping_service import (
    MAPPING_OUTPUT_DIR,
    build_statement_mapping_result,
)


OUTPUT_DIR = PROJECT_ROOT / "runtime" / "financial_report" / "human_review_pack"
CSV_FIELDS = [
    "review_item_id",
    "document_id",
    "pdf_name",
    "review_type",
    "reason",
    "source_pages",
    "table_id",
    "table_group_id",
    "canonical_field_name",
    "raw_field_name",
    "raw_value",
    "normalized_value",
    "period_label",
    "unit",
    "currency",
    "confidence",
    "suggested_user_action",
    "evidence_excerpt",
]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_items: list[dict[str, Any]] = []
    for entry in load_registry_entries():
        items = build_review_items_for_document(entry)
        all_items.extend(items[:30])

    _write_jsonl(all_items)
    _write_csv(all_items)
    _write_md(all_items)
    print(json.dumps({"human_review_items_count": len(all_items), "output_dir": str(OUTPUT_DIR)}, ensure_ascii=False, indent=2))
    return 0


def build_review_items_for_document(entry: dict[str, Any]) -> list[dict[str, Any]]:
    document_id = entry.get("document_id", "")
    pdf_name = entry.get("pdf_name", "")
    candidate_set = _load_or_build_candidates(document_id)
    mapping = _load_or_build_mapping(document_id)
    minimal = build_minimal_financial_extraction(document_id, allow_override=True)
    merged_tables = _load_json_list(entry.get("merged_tables_json_path", ""))
    continuation_by_group = {
        group.get("table_group_id", ""): float(group.get("continuation_confidence") or 0.0)
        for group in merged_tables
    }
    candidate_by_table = {candidate.get("table_id"): candidate for candidate in candidate_set.get("candidates", [])}
    pages = _load_pages(entry.get("pages_jsonl_path", ""))

    items: list[dict[str, Any]] = []
    for field in mapping.get("fields", []):
        candidate = candidate_by_table.get(field.get("table_id"), {})
        table_group_id = field.get("table_group_id", "")
        continuation = _continuation_confidence(table_group_id, continuation_by_group)
        reason_parts = []
        review_type = "field_mapping_semantic_check"
        if candidate.get("source_type") == "merged_cross_page_table" or (table_group_id and continuation < 0.85):
            review_type = "cross_page_numeric_check"
            reason_parts.append(f"cross-page table confidence={continuation:.2f}")
        if float(field.get("confidence") or 0.0) < 0.75:
            reason_parts.append("confidence<0.75")
        if "weak_aliases" in str(field.get("mapping_reason", "")):
            reason_parts.append("weak alias match")
        if field.get("period_label") == "unknown_period":
            reason_parts.append("unknown period")
        if field.get("unit") == "unknown":
            reason_parts.append("unknown unit")
        if field.get("requires_review"):
            reason_parts.append("field requires review")
        if _looks_broken_value(field.get("raw_value", ""), field.get("normalized_value")):
            review_type = "cross_page_numeric_check" if table_group_id else review_type
            reason_parts.append("raw or normalized value looks suspicious")

        if reason_parts:
            items.append(
                _item(
                    document_id=document_id,
                    pdf_name=pdf_name,
                    review_type=review_type,
                    reason="; ".join(dict.fromkeys(reason_parts)),
                    source_pages=field.get("source_pages", []),
                    table_id=field.get("table_id", ""),
                    table_group_id=table_group_id,
                    canonical_field_name=field.get("canonical_field_name", ""),
                    raw_field_name=field.get("raw_field_name", ""),
                    raw_value=field.get("raw_value", ""),
                    normalized_value=field.get("normalized_value"),
                    period_label=field.get("period_label", ""),
                    unit=field.get("unit", ""),
                    currency=field.get("currency", ""),
                    confidence=field.get("confidence", 0.0),
                    suggested_user_action="Compare this mapped field with the original PDF table and confirm value, period, unit, and row label.",
                    evidence_excerpt=f"{field.get('raw_field_name', '')} = {field.get('raw_value', '')}",
                )
            )

    items.extend(_visual_table_items(entry, pages))
    items.extend(_document_role_items(entry, candidate_set, minimal))
    return sorted(items, key=_risk_rank, reverse=True)


def _visual_table_items(entry: dict[str, Any], pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for page in pages:
        final_tables = page.get("final_tables") or []
        table_count = len(final_tables) if isinstance(final_tables, list) else 0
        if page.get("visual_table_route_triggered") or (float(page.get("table_intent_score") or 0.0) >= 0.8 and table_count <= 1):
            items.append(
                _item(
                    document_id=entry.get("document_id", ""),
                    pdf_name=entry.get("pdf_name", ""),
                    review_type="visual_table_check",
                    reason=f"visual_table_route_triggered={page.get('visual_table_route_triggered')}; table_intent_score={page.get('table_intent_score')}; table_count={table_count}",
                    source_pages=[page.get("page_number")],
                    table_id="",
                    table_group_id=page.get("table_group_id", ""),
                    canonical_field_name="",
                    raw_field_name="",
                    raw_value="",
                    normalized_value=None,
                    period_label="",
                    unit="",
                    currency="",
                    confidence=page.get("table_intent_score", 0.0),
                    suggested_user_action="Open the original PDF page and confirm whether visual tables were recovered correctly.",
                    evidence_excerpt=str(page.get("final_text", ""))[:300],
                )
            )
    return items


def _document_role_items(entry: dict[str, Any], candidate_set: dict[str, Any], minimal: Any) -> list[dict[str, Any]]:
    assessment = assess_document_role(entry.get("document_id", ""))
    candidates = candidate_set.get("candidates", [])
    three_statement_candidate_count = sum(1 for candidate in candidates if candidate.get("candidate_statement_type") in {"balance_sheet", "income_statement", "cash_flow_statement"})
    statement_count = len(getattr(minimal, "statements", []))
    reason = ""
    if assessment.document_role == "unknown":
        reason = "document role is unknown"
    elif assessment.document_role == "auxiliary_material" and three_statement_candidate_count >= 10:
        reason = f"auxiliary material has many three-statement candidates: {three_statement_candidate_count}"
    elif assessment.document_role == "primary_financial_report" and statement_count < 2:
        reason = f"primary report has few extracted statements: {statement_count}"
    if not reason:
        return []
    return [
        _item(
            document_id=entry.get("document_id", ""),
            pdf_name=entry.get("pdf_name", ""),
            review_type="auxiliary_material_role_check",
            reason=reason,
            source_pages=[],
            table_id="",
            table_group_id="",
            canonical_field_name="",
            raw_field_name="",
            raw_value="",
            normalized_value=None,
            period_label="",
            unit="",
            currency="",
            confidence=assessment.confidence,
            suggested_user_action="Confirm whether this document is a primary financial report or auxiliary material before extraction.",
            evidence_excerpt="; ".join(assessment.evidence),
        )
    ]


def _item(**kwargs: Any) -> dict[str, Any]:
    item = {field: kwargs.get(field, "") for field in CSV_FIELDS}
    item["review_item_id"] = ""
    return item


def _write_jsonl(items: list[dict[str, Any]]) -> None:
    with (OUTPUT_DIR / "human_review_items.jsonl").open("w", encoding="utf-8") as handle:
        for index, item in enumerate(items, start=1):
            item["review_item_id"] = f"hri_{index:05d}"
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _write_csv(items: list[dict[str, Any]]) -> None:
    with (OUTPUT_DIR / "human_review_items.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in items:
            row = dict(item)
            row["source_pages"] = json.dumps(row.get("source_pages", []), ensure_ascii=False)
            writer.writerow(row)


def _write_md(items: list[dict[str, Any]]) -> None:
    by_type = {}
    for item in items:
        by_type[item["review_type"]] = by_type.get(item["review_type"], 0) + 1
    lines = [
        "# Human Review Pack",
        "",
        "This pack contains only semantic or numeric checks that require comparing the extracted evidence with the original PDF.",
        "",
        f"- total_review_items: {len(items)}",
        f"- review_type_distribution: `{json.dumps(by_type, ensure_ascii=False)}`",
        "",
        "## Top Items",
        "",
    ]
    for item in items[:30]:
        lines.extend(
            [
                f"### {item['review_item_id']} {item['review_type']}",
                "",
                f"- document_id: `{item['document_id']}`",
                f"- source_pages: `{item['source_pages']}`",
                f"- reason: {item['reason']}",
                f"- field: `{item['canonical_field_name']}`",
                f"- raw: `{item['raw_field_name']} = {item['raw_value']}`",
                f"- suggested action: {item['suggested_user_action']}",
                "",
            ]
        )
    (OUTPUT_DIR / "HUMAN_REVIEW_PACK.md").write_text("\n".join(lines), encoding="utf-8")


def _load_or_build_candidates(document_id: str) -> dict[str, Any]:
    path = CANDIDATE_OUTPUT_DIR / f"{document_id}.financial_table_candidates.json"
    if not path.exists():
        build_extraction_candidate_set(document_id, allow_override=True)
    return _load_json(path)


def _load_or_build_mapping(document_id: str) -> dict[str, Any]:
    path = MAPPING_OUTPUT_DIR / f"{document_id}.statement_field_candidates_refined.json"
    if not path.exists():
        build_statement_mapping_result(document_id, allow_override=True)
    return _load_json(path)


def _load_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _load_json_list(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


def _load_pages(path: str) -> list[dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    pages = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                pages.append(json.loads(line))
    return pages


def _continuation_confidence(table_group_id: str, by_group: dict[str, float]) -> float:
    if table_group_id in by_group:
        return by_group[table_group_id]
    values = [by_group.get(part, 0.0) for part in str(table_group_id).split(",") if part]
    return min(values) if values else 0.0


def _looks_broken_value(raw_value: Any, normalized_value: Any) -> bool:
    text = str(raw_value or "")
    return (not text.strip()) or ("\n" in text and len(text.strip()) <= 4) or (normalized_value is None and any(char.isdigit() for char in text))


def _risk_rank(item: dict[str, Any]) -> tuple[int, float]:
    type_score = {
        "cross_page_numeric_check": 5,
        "visual_table_check": 4,
        "field_mapping_semantic_check": 3,
        "statement_type_check": 2,
        "auxiliary_material_role_check": 1,
    }.get(item.get("review_type"), 0)
    confidence = float(item.get("confidence") or 0.0)
    return (type_score, 1.0 - confidence)


if __name__ == "__main__":
    sys.exit(main())
