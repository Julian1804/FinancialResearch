from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.extraction_contract import (
    ExtractedTableCandidate,
    ExtractionEligibilityResult,
    FinancialExtractionCandidateSet,
)
from backend.app.modules.financial_report.schemas.table_contract import (
    CanonicalTable,
    TableNormalizationResult,
)
from backend.app.modules.financial_report.services.parse_review_decision_service import (
    get_extraction_eligibility,
)
from backend.app.modules.financial_report.services.parsed_document_registry import (
    load_registry_entries,
)
from backend.app.modules.financial_report.services.table_normalization_service import (
    normalize_parse_lab_tables,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
CANDIDATE_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "financial_report" / "extraction_candidates"
SUPPORTED_CANDIDATE_TYPES = {
    "balance_sheet",
    "income_statement",
    "cash_flow_statement",
    "shareholder_table",
    "segment_revenue_table",
}


def check_extraction_eligibility(document_id: str) -> ExtractionEligibilityResult:
    raw = get_extraction_eligibility(document_id)
    return ExtractionEligibilityResult(
        document_id=document_id,
        eligible_for_extraction=bool(raw.get("eligible_for_extraction")),
        reason=raw.get("reason", ""),
        parse_quality_level=raw.get("parse_quality_level", ""),
        review_decision=raw.get("review_decision", ""),
        required_files_present=bool(raw.get("required_files_present")),
    )


def load_normalized_tables_for_document(document_id: str) -> TableNormalizationResult:
    entry = _find_registry_entry(document_id)
    if not entry:
        return TableNormalizationResult(document_id=document_id, errors=[f"document_id not found: {document_id}"])
    manifest = _manifest_from_registry_entry(entry)
    return normalize_parse_lab_tables(manifest)


def select_financial_table_candidates(
    normalization_result: TableNormalizationResult,
) -> list[ExtractedTableCandidate]:
    candidates: list[ExtractedTableCandidate] = []
    for table in normalization_result.tables:
        if table.candidate_statement_type not in SUPPORTED_CANDIDATE_TYPES:
            continue
        candidates.append(_candidate_from_table(normalization_result, table, len(candidates)))
    return candidates


def build_extraction_candidate_set(
    document_id: str,
    allow_override: bool = False,
) -> FinancialExtractionCandidateSet:
    eligibility = check_extraction_eligibility(document_id)
    entry = _find_registry_entry(document_id)
    task_id = entry.get("parse_task_id", "") if entry else ""
    pdf_name = entry.get("pdf_name", "") if entry else ""

    if not eligibility.eligible_for_extraction and not allow_override:
        candidate_set = FinancialExtractionCandidateSet(
            document_id=document_id,
            task_id=task_id,
            pdf_name=pdf_name,
            eligible_for_extraction=False,
            extraction_mode="blocked",
            warnings=[eligibility.reason],
        )
        _write_candidate_set(candidate_set, "blocked_extraction")
        return candidate_set

    normalization_result = load_normalized_tables_for_document(document_id)
    candidates = select_financial_table_candidates(normalization_result)
    mode = "eligible" if eligibility.eligible_for_extraction else "dry_run_override"
    warnings = list(normalization_result.warnings)
    if allow_override and not eligibility.eligible_for_extraction:
        warnings.append("override_used")
        warnings.append(f"eligibility_block_reason={eligibility.reason}")

    candidate_set = FinancialExtractionCandidateSet(
        document_id=document_id,
        task_id=normalization_result.task_id or task_id,
        pdf_name=normalization_result.pdf_name or pdf_name,
        eligible_for_extraction=eligibility.eligible_for_extraction,
        extraction_mode=mode,
        candidates=candidates,
        warnings=warnings,
        errors=list(normalization_result.errors),
    )
    suffix = "financial_table_candidates" if mode != "blocked" else "blocked_extraction"
    _write_candidate_set(candidate_set, suffix)
    return candidate_set


def summarize_candidate_set(candidate_set: FinancialExtractionCandidateSet) -> dict[str, Any]:
    return {
        "document_id": candidate_set.document_id,
        "eligible_for_extraction": candidate_set.eligible_for_extraction,
        "extraction_mode": candidate_set.extraction_mode,
        "candidates_count": len(candidate_set.candidates),
        "candidate_statement_type_distribution": dict(
            Counter(candidate.candidate_statement_type for candidate in candidate_set.candidates)
        ),
        "source_type_distribution": dict(Counter(candidate.source_type for candidate in candidate_set.candidates)),
        "merged_cross_page_table_candidate_count": sum(
            1 for candidate in candidate_set.candidates if candidate.source_type == "merged_cross_page_table"
        ),
        "warnings": candidate_set.warnings,
        "errors": candidate_set.errors,
    }


def _candidate_from_table(
    normalization_result: TableNormalizationResult,
    table: CanonicalTable,
    index: int,
) -> ExtractedTableCandidate:
    notes: list[str] = []
    requires_review = False
    confidence = _table_confidence(table)
    if table.source.source_type == "merged_cross_page_table":
        notes.append("cross_page_table_candidate")
        requires_review = True
    if table.quality.quality_flags:
        notes.append("quality_flags_present")
        requires_review = True
    if confidence < 0.65:
        notes.append("low_candidate_confidence")
        requires_review = True

    return ExtractedTableCandidate(
        candidate_id=f"{normalization_result.document_id}_{index:04d}",
        document_id=normalization_result.document_id,
        task_id=normalization_result.task_id,
        table_id=table.table_id,
        candidate_statement_type=table.candidate_statement_type,
        source_pages=table.source.source_pages,
        source_type=table.source.source_type,
        table_group_id=table.source.table_group_id,
        title=table.title,
        row_count=table.quality.row_count,
        col_count=table.quality.col_count,
        numeric_cell_ratio=table.quality.numeric_cell_ratio,
        confidence=confidence,
        extraction_notes=notes,
        requires_review=requires_review,
        quality_flags=table.quality.quality_flags,
    )


def _table_confidence(table: CanonicalTable) -> float:
    score = 0.5
    if table.quality.has_header:
        score += 0.15
    if table.quality.row_count >= 3 and table.quality.col_count >= 2:
        score += 0.15
    if table.quality.numeric_cell_ratio >= 0.15:
        score += 0.10
    if table.source.source_type == "merged_cross_page_table":
        score += min(table.quality.continuation_confidence, 1.0) * 0.10
    if table.quality.empty_cell_ratio > 0.35:
        score -= 0.10
    return round(max(0.0, min(score, 1.0)), 4)


def _find_registry_entry(document_id: str) -> dict[str, Any] | None:
    for entry in load_registry_entries():
        if entry.get("document_id") == document_id:
            return entry
    return None


def _manifest_from_registry_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": entry.get("document_id", ""),
        "task_id": entry.get("parse_task_id", ""),
        "pdf_name": entry.get("pdf_name", ""),
        "summary_path": entry.get("summary_path", ""),
        "pages_jsonl_path": entry.get("pages_jsonl_path", ""),
        "merged_md_path": entry.get("merged_md_path", ""),
        "tables_json_path": entry.get("tables_json_path", ""),
        "merged_tables_json_path": entry.get("merged_tables_json_path", ""),
        "quality_flags_path": entry.get("quality_flags_path", ""),
        "cross_page_candidates_path": entry.get("cross_page_candidates_path", ""),
    }


def _write_candidate_set(candidate_set: FinancialExtractionCandidateSet, suffix: str) -> Path:
    CANDIDATE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CANDIDATE_OUTPUT_DIR / f"{candidate_set.document_id}.{suffix}.json"
    output_path.write_text(json.dumps(_model_dump(candidate_set), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
