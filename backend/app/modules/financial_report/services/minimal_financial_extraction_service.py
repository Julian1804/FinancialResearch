from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.minimal_extraction_contract import (
    ExtractedFinancialField,
    ExtractedFinancialStatement,
    MinimalFinancialExtractionResult,
)
from backend.app.modules.financial_report.schemas.statement_field_contract import (
    StatementFieldCandidate,
    StatementMappingResult,
)
from backend.app.modules.financial_report.services.document_role_detector import (
    assess_document_role,
)
from backend.app.modules.financial_report.services.parse_review_decision_service import (
    get_extraction_eligibility,
)
from backend.app.modules.financial_report.services.statement_field_mapping_service import (
    MAPPING_OUTPUT_DIR,
    build_statement_mapping_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
MINIMAL_EXTRACTION_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "financial_report" / "minimal_extraction"


def load_refined_field_candidates(document_id: str) -> StatementMappingResult:
    path = MAPPING_OUTPUT_DIR / f"{document_id}.statement_field_candidates_refined.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            return StatementMappingResult(**json.load(handle))
    return build_statement_mapping_result(document_id, allow_override=True)


def group_fields_by_statement_and_period(
    fields: list[StatementFieldCandidate],
) -> dict[tuple[str, str], list[StatementFieldCandidate]]:
    grouped: dict[tuple[str, str], list[StatementFieldCandidate]] = defaultdict(list)
    for field in fields:
        grouped[(field.candidate_statement_type, field.period_label)].append(field)
    return grouped


def choose_best_field_candidate(candidates: list[StatementFieldCandidate]) -> StatementFieldCandidate:
    return sorted(candidates, key=_field_rank, reverse=True)[0]


def build_minimal_financial_extraction(
    document_id: str,
    allow_override: bool = False,
) -> MinimalFinancialExtractionResult:
    role = assess_document_role(document_id)
    if role.document_role == "auxiliary_material":
        warnings = [
            "auxiliary_material_no_three_statement_expected",
            f"document_role={role.document_role}",
            f"report_type={role.report_type}",
            f"expected_extraction_strategy={role.expected_extraction_strategy}",
        ]
        result = MinimalFinancialExtractionResult(
            document_id=document_id,
            extraction_mode="auxiliary_material_dry_run" if allow_override else "blocked_by_document_role",
            warnings=warnings,
        )
        _write_extraction_result(result, "minimal_financial_extraction" if allow_override else "blocked_minimal_extraction")
        return result

    if role.document_role == "unknown" and not allow_override:
        result = MinimalFinancialExtractionResult(
            document_id=document_id,
            extraction_mode="blocked_by_document_role",
            warnings=["document_role_unknown_requires_review", *role.evidence],
        )
        _write_extraction_result(result, "blocked_minimal_extraction")
        return result

    eligibility = get_extraction_eligibility(document_id)
    if not eligibility.get("eligible_for_extraction") and not allow_override:
        mapping = _load_blocked_or_refined_mapping(document_id)
        result = MinimalFinancialExtractionResult(
            document_id=document_id,
            task_id=mapping.task_id,
            pdf_name=mapping.pdf_name,
            extraction_mode="blocked",
            warnings=[eligibility.get("reason", "not eligible for extraction")],
            errors=list(mapping.errors),
        )
        _write_extraction_result(result, "blocked_minimal_extraction")
        return result

    mapping = load_refined_field_candidates(document_id)
    warnings = [
        f"document_role={role.document_role}",
        f"report_type={role.report_type}",
        f"expected_extraction_strategy={role.expected_extraction_strategy}",
        *list(mapping.warnings),
    ]
    if allow_override and not eligibility.get("eligible_for_extraction"):
        warnings.append("override_used")
        warnings.append(f"eligibility_block_reason={eligibility.get('reason', '')}")

    statements, discarded_count = _build_statements(mapping.fields)
    if discarded_count:
        warnings.append(f"discarded_field_candidates_count={discarded_count}")
    result = MinimalFinancialExtractionResult(
        document_id=document_id,
        task_id=mapping.task_id,
        pdf_name=mapping.pdf_name,
        extraction_mode="dry_run_override" if allow_override and not eligibility.get("eligible_for_extraction") else "eligible",
        statements=statements,
        warnings=warnings,
        errors=list(mapping.errors),
    )
    _write_extraction_result(result, "minimal_financial_extraction")
    return result


def _build_statements(
    fields: list[StatementFieldCandidate],
) -> tuple[list[ExtractedFinancialStatement], int]:
    best_by_key: dict[tuple[str, str, str], StatementFieldCandidate] = {}
    discarded_count = 0
    for field in fields:
        key = (field.candidate_statement_type, field.canonical_field_name, field.period_label)
        existing = best_by_key.get(key)
        if not existing:
            best_by_key[key] = field
            continue
        if _field_rank(field) > _field_rank(existing):
            best_by_key[key] = field
        discarded_count += 1

    statement_fields: dict[str, list[ExtractedFinancialField]] = defaultdict(list)
    for field in best_by_key.values():
        extracted = ExtractedFinancialField(
            field_id=f"extracted_{field.field_id}",
            canonical_field_name=field.canonical_field_name,
            statement_type=field.candidate_statement_type,
            value=field.raw_value,
            normalized_value=field.normalized_value,
            unit=field.unit,
            currency=field.currency,
            period_label=field.period_label,
            source_pages=field.source_pages,
            source_table_id=field.table_id,
            source_table_group_id=field.table_group_id,
            confidence=field.confidence,
            requires_review=field.requires_review,
            extraction_reason=f"selected_best_candidate; {field.mapping_reason}",
        )
        statement_fields[field.candidate_statement_type].append(extracted)

    statements: list[ExtractedFinancialStatement] = []
    for statement_type, extracted_fields in sorted(statement_fields.items()):
        periods = sorted({field.period_label for field in extracted_fields})
        source_pages = sorted({page for field in extracted_fields for page in field.source_pages})
        statements.append(
            ExtractedFinancialStatement(
                statement_type=statement_type,
                fields=sorted(extracted_fields, key=lambda item: (item.period_label, item.canonical_field_name)),
                periods_detected=periods,
                source_pages=source_pages,
                quality_flags=[],
                requires_review=any(field.requires_review for field in extracted_fields),
            )
        )
    return statements, discarded_count


def _field_rank(field: StatementFieldCandidate) -> tuple[int, int, int, float]:
    reason = field.mapping_reason or ""
    if "exact_aliases" in reason:
        alias_score = 3
    elif "phrase_aliases" in reason:
        alias_score = 2
    elif "weak_aliases" in reason:
        alias_score = 1
    else:
        alias_score = 0
    period_score = 0 if field.period_label == "unknown_period" else 1
    unit_score = 0 if field.unit == "unknown" else 1
    source_score = 0 if field.table_group_id and "," in field.table_group_id else 1
    return (
        alias_score,
        period_score,
        unit_score + source_score,
        field.confidence,
    )


def _load_blocked_or_refined_mapping(document_id: str) -> StatementMappingResult:
    blocked = MAPPING_OUTPUT_DIR / f"{document_id}.blocked_statement_mapping.json"
    if blocked.exists():
        with blocked.open("r", encoding="utf-8") as handle:
            return StatementMappingResult(**json.load(handle))
    refined = MAPPING_OUTPUT_DIR / f"{document_id}.statement_field_candidates_refined.json"
    if refined.exists():
        with refined.open("r", encoding="utf-8") as handle:
            return StatementMappingResult(**json.load(handle))
    return build_statement_mapping_result(document_id, allow_override=False)


def _write_extraction_result(result: MinimalFinancialExtractionResult, suffix: str) -> Path:
    MINIMAL_EXTRACTION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MINIMAL_EXTRACTION_OUTPUT_DIR / f"{result.document_id}.{suffix}.json"
    output_path.write_text(json.dumps(_model_dump(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
