from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.services.parsed_document_registry import (
    list_registry_entries,
    load_registry_entries,
)
from backend.app.modules.financial_report.services.parse_review_decision_service import (
    find_decision_by_document_id,
)


HIGH_OCR_RATIO_THRESHOLD = 0.40
HIGH_HEAVY_RATIO_THRESHOLD = 0.60


def build_review_queue(limit: int = 100) -> list[dict[str, Any]]:
    entries = list_registry_entries(limit=limit)
    return [_build_review_item(entry) for entry in entries]


def classify_registry_entry(entry: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    parse_quality_level = entry.get("parse_quality_level", "")
    parse_status = entry.get("parse_status", "")

    if parse_quality_level == "failed" or parse_status in {"failed", "cancelled"}:
        reasons.append(f"parse_status={parse_status}, parse_quality_level={parse_quality_level}")
        return "failed", reasons

    missing_outputs = _missing_output_files(entry)
    if missing_outputs:
        reasons.append(f"missing_outputs={missing_outputs}")
        return "failed", reasons

    if parse_quality_level == "needs_review":
        reasons.append("parse_quality_level=needs_review")
    if int(entry.get("cross_page_table_candidate_count") or 0) > 0:
        reasons.append(f"cross_page_table_candidate_count={entry.get('cross_page_table_candidate_count')}")
    if int(entry.get("visual_table_route_pages_count") or 0) > 0:
        reasons.append(f"visual_table_route_pages_count={entry.get('visual_table_route_pages_count')}")
    if float(entry.get("ocr_ratio") or 0.0) >= HIGH_OCR_RATIO_THRESHOLD:
        reasons.append(f"ocr_ratio={float(entry.get('ocr_ratio') or 0.0):.4f}")
    if float(entry.get("heavy_parser_ratio") or 0.0) >= HIGH_HEAVY_RATIO_THRESHOLD:
        reasons.append(f"heavy_parser_ratio={float(entry.get('heavy_parser_ratio') or 0.0):.4f}")
    if reasons:
        return "needs_review", reasons

    if parse_quality_level == "pass":
        return "ready_for_extraction", ["parse_quality_level=pass"]
    if parse_quality_level == "pass_with_warnings":
        return "ready_with_warnings", ["parse_quality_level=pass_with_warnings without high-risk flags"]

    return "needs_review", [f"unrecognized parse_quality_level={parse_quality_level}"]


def get_review_item_by_document_id(document_id: str) -> dict[str, Any] | None:
    for entry in load_registry_entries():
        if entry.get("document_id") == document_id:
            return _build_review_item(entry)
    return None


def get_review_queue_summary(limit: int = 100) -> dict[str, Any]:
    queue = build_review_queue(limit=limit)
    return {
        "registry_count": len(list_registry_entries(limit=limit)),
        "review_queue_count": len(queue),
        "review_status_distribution": dict(Counter(item["review_status"] for item in queue)),
        "parse_quality_distribution": dict(Counter(item["parse_quality_level"] for item in queue)),
    }


def _build_review_item(entry: dict[str, Any]) -> dict[str, Any]:
    review_status, review_reasons = classify_registry_entry(entry)
    decision = find_decision_by_document_id(entry.get("document_id", ""))
    current_review_decision = decision.get("review_decision") if decision else "pending_review"
    approved_for_extraction = bool(decision.get("approved_for_extraction")) if decision else False
    requires_manual_check = bool(decision.get("requires_manual_check")) if decision else True
    return {
        "document_id": entry.get("document_id", ""),
        "pdf_name": entry.get("pdf_name", ""),
        "pdf_path": entry.get("pdf_path", ""),
        "parse_task_id": entry.get("parse_task_id", ""),
        "parse_quality_level": entry.get("parse_quality_level", ""),
        "review_status": review_status,
        "review_reasons": review_reasons,
        "current_review_decision": current_review_decision,
        "approved_for_extraction": approved_for_extraction,
        "requires_manual_check": requires_manual_check,
        "output_dir": entry.get("output_dir", ""),
        "summary_path": entry.get("summary_path", ""),
        "merged_md_path": entry.get("merged_md_path", ""),
        "tables_json_path": entry.get("tables_json_path", ""),
        "merged_tables_json_path": entry.get("merged_tables_json_path", ""),
        "quality_flags_path": entry.get("quality_flags_path", ""),
        "cross_page_candidates_path": entry.get("cross_page_candidates_path", ""),
        "total_pages": entry.get("total_pages", 0),
        "heavy_parser_ratio": entry.get("heavy_parser_ratio", 0.0),
        "ocr_ratio": entry.get("ocr_ratio", 0.0),
        "cross_page_table_candidate_count": entry.get("cross_page_table_candidate_count", 0),
        "visual_table_route_pages_count": entry.get("visual_table_route_pages_count", 0),
        "registered_at": entry.get("registered_at", ""),
    }


def _missing_output_files(entry: dict[str, Any]) -> list[str]:
    keys = [
        "summary_path",
        "pages_jsonl_path",
        "merged_md_path",
        "tables_json_path",
        "merged_tables_json_path",
        "quality_flags_path",
        "cross_page_candidates_path",
    ]
    missing = []
    for key in keys:
        value = entry.get(key)
        if not value or not Path(value).exists():
            missing.append(key)
    return missing
