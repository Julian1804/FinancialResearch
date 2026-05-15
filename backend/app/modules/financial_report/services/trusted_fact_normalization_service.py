from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.provisional_fact_contract import (
    NormalizedTrustedFinancialFact,
    ResolvedFinancialFact,
    TrustedFactNormalizationGapReport,
    TrustedFactNormalizationResult,
    TrustedFactNormalizationSummary,
)
from backend.app.modules.financial_report.services.trust_resolution_service import (
    TRUSTED_STATUSES,
    load_trusted_facts_for_analysis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
NORMALIZED_TRUSTED_FACT_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "normalization" / "parse_lab_round3_trusted"
)

CSV_FIELDS = [
    "normalized_fact_id",
    "fact_id",
    "field_name",
    "value_original",
    "value_normalized",
    "unit_original",
    "unit_normalized",
    "currency_original",
    "currency_normalized",
    "period_original",
    "period_normalized",
    "fiscal_year",
    "fiscal_period_type",
    "source_pdf",
    "source_page",
    "trust_status",
    "normalization_status",
]


def normalize_parse_lab_round3_trusted_facts(
    output_dir: Path | str = NORMALIZED_TRUSTED_FACT_OUTPUT_DIR,
) -> TrustedFactNormalizationResult:
    output_dir = Path(output_dir)
    trusted_facts = load_trusted_facts_for_analysis()
    normalized_facts = [_normalize_fact(fact, index) for index, fact in enumerate(trusted_facts, start=1)]
    errors = _validate_normalized_facts(normalized_facts)
    gap_report = _build_gap_report(normalized_facts)
    summary = _build_summary(output_dir, normalized_facts, errors)
    result = TrustedFactNormalizationResult(
        summary=summary,
        gap_report=gap_report,
        normalized_facts=normalized_facts,
    )
    _write_outputs(output_dir, result)
    return result


def summarize_normalization_result(result: TrustedFactNormalizationResult) -> dict[str, Any]:
    return _model_dump(result.summary)


def _normalize_fact(fact: ResolvedFinancialFact, index: int) -> NormalizedTrustedFinancialFact:
    period_normalized, fiscal_year, fiscal_period_type, period_warning = _normalize_period(fact)
    currency_normalized, currency_warning = _normalize_currency(fact)
    unit_normalized, multiplier, unit_warning = _normalize_unit(fact)
    value_normalized, value_warning = _normalize_value(fact.value, multiplier)

    warnings = [
        warning
        for warning in [period_warning, currency_warning, unit_warning, value_warning]
        if warning
    ]
    normalization_status = "normalized"
    if not period_normalized or not currency_normalized or not unit_normalized or value_normalized is None:
        normalization_status = "insufficient_evidence"

    provenance = dict(fact.provenance)
    provenance.update(
        {
            "normalization_input": "load_trusted_facts_for_analysis",
            "normalization_policy": "trusted_only_conservative_period_currency_unit_normalization",
            "source_fact_id": fact.fact_id,
            "source_original_fact_id": fact.original_fact_id,
        }
    )
    return NormalizedTrustedFinancialFact(
        normalized_fact_id=f"parse_lab_round3_normalized_{index:04d}",
        fact_id=fact.fact_id,
        original_fact_id=fact.original_fact_id,
        field_name=fact.field_name,
        value_original=fact.value,
        unit_original=fact.unit,
        currency_original=fact.currency,
        period_original=fact.period,
        source_pdf=fact.source_pdf,
        source_page=fact.source_page,
        source_type=fact.source_type,
        evidence_text=fact.evidence_text,
        table_id=fact.table_id,
        engine_name=fact.engine_name,
        validation_status=fact.validation_status,
        confidence=fact.confidence,
        trust_status=fact.trust_status,
        trusted=fact.trusted,
        candidate_only=fact.candidate_only,
        period_normalized=period_normalized,
        fiscal_year=fiscal_year,
        fiscal_period_type=fiscal_period_type,
        currency_normalized=currency_normalized,
        unit_normalized=unit_normalized,
        value_normalized=value_normalized,
        normalization_status=normalization_status,
        normalization_warnings=warnings,
        provenance=provenance,
    )


def _normalize_period(fact: ResolvedFinancialFact) -> tuple[str, int | None, str, str]:
    source_text = _normalize_text(f"{fact.period} {fact.source_pdf} {fact.evidence_text}")
    fiscal_year = _extract_year(source_text)
    if not fiscal_year:
        return "", None, "", "missing_period_evidence"
    if any(token in source_text for token in ("中报", "半年", "interim", "half year", "six months")):
        return f"FY{fiscal_year}_H1", fiscal_year, "interim_h1", ""
    if any(token in source_text for token in ("年报", "annual", "twelve months")):
        return f"FY{fiscal_year}", fiscal_year, "annual", ""
    return "", fiscal_year, "", "unsupported_period_type"


def _normalize_currency(fact: ResolvedFinancialFact) -> tuple[str, str]:
    text = _normalize_text(f"{fact.currency} {fact.evidence_text}")
    if any(token in text for token in ("rmb", "人民幣", "人民币", "cny")):
        return "CNY", ""
    if any(token in text for token in ("hkd", "港元")):
        return "HKD", ""
    if any(token in text for token in ("usd", "美元")):
        return "USD", ""
    return "", "missing_currency_evidence"


def _normalize_unit(fact: ResolvedFinancialFact) -> tuple[str, float | None, str]:
    text = _normalize_text(f"{fact.unit} {fact.evidence_text}")
    if "rmb'000" in text or "rmb’000" in text or "千元" in text:
        return "thousand", 1000.0, ""
    if "million" in text or "百万元" in text or "百萬" in text:
        return "million", 1000000.0, ""
    if fact.unit and fact.unit not in {"table_cell", "raw_table_cell"}:
        return fact.unit, 1.0, ""
    return "", None, "missing_unit_evidence"


def _normalize_value(value: Any, multiplier: float | None) -> tuple[float | None, str]:
    if multiplier is None:
        return None, "value_not_normalized_without_unit"
    try:
        return float(value) * multiplier, ""
    except (TypeError, ValueError):
        return None, "value_not_numeric"


def _extract_year(text: str) -> int | None:
    match = re.search(r"20\d{2}", text)
    if not match:
        return None
    return int(match.group(0))


def _validate_normalized_facts(facts: list[NormalizedTrustedFinancialFact]) -> list[str]:
    errors: list[str] = []
    for fact in facts:
        if fact.trust_status not in TRUSTED_STATUSES:
            errors.append(f"{fact.normalized_fact_id}: non-trusted status entered normalization")
        if not fact.trusted:
            errors.append(f"{fact.normalized_fact_id}: trusted must be true")
        if fact.candidate_only:
            errors.append(f"{fact.normalized_fact_id}: candidate_only must be false")
        if not fact.provenance:
            errors.append(f"{fact.normalized_fact_id}: missing provenance")
    return errors


def _build_gap_report(facts: list[NormalizedTrustedFinancialFact]) -> TrustedFactNormalizationGapReport:
    missing_period = [fact.fact_id for fact in facts if not fact.period_normalized]
    missing_currency = [fact.fact_id for fact in facts if not fact.currency_normalized]
    missing_unit = [fact.fact_id for fact in facts if not fact.unit_normalized]
    missing_value = [fact.fact_id for fact in facts if fact.value_normalized is None]
    return TrustedFactNormalizationGapReport(
        missing_period_count=len(missing_period),
        missing_currency_count=len(missing_currency),
        missing_unit_count=len(missing_unit),
        missing_value_normalization_count=len(missing_value),
        missing_period_fact_ids=missing_period,
        missing_currency_fact_ids=missing_currency,
        missing_unit_fact_ids=missing_unit,
        missing_value_normalization_fact_ids=missing_value,
    )


def _build_summary(
    output_dir: Path,
    facts: list[NormalizedTrustedFinancialFact],
    errors: list[str],
) -> TrustedFactNormalizationSummary:
    return TrustedFactNormalizationSummary(
        normalization_id="parse_lab_round3_trusted_fact_normalization",
        output_dir=str(output_dir),
        input_trusted_fact_count=len(facts),
        normalized_success_count=sum(1 for fact in facts if fact.normalization_status == "normalized"),
        insufficient_evidence_count=sum(1 for fact in facts if fact.normalization_status == "insufficient_evidence"),
        period_normalized_count=sum(1 for fact in facts if fact.period_normalized),
        currency_normalized_count=sum(1 for fact in facts if fact.currency_normalized),
        unit_normalized_count=sum(1 for fact in facts if fact.unit_normalized),
        value_normalized_count=sum(1 for fact in facts if fact.value_normalized is not None),
        trust_status_distribution=dict(Counter(fact.trust_status for fact in facts)),
        normalization_status_distribution=dict(Counter(fact.normalization_status for fact in facts)),
        source_pdf_distribution=dict(Counter(fact.source_pdf for fact in facts)),
        candidate_input_count=sum(1 for fact in facts if fact.candidate_only or fact.trust_status not in TRUSTED_STATUSES),
        warnings=[],
        errors=errors,
    )


def _write_outputs(output_dir: Path, result: TrustedFactNormalizationResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_facts = [_model_dump(fact) for fact in result.normalized_facts]
    _write_json(output_dir / "normalized_trusted_facts.json", {"items": normalized_facts, "count": len(normalized_facts)})
    _write_csv(output_dir / "normalized_trusted_facts.csv", normalized_facts)
    _write_json(output_dir / "normalization_summary.json", _model_dump(result.summary))
    _write_json(output_dir / "normalization_gap_report.json", _model_dump(result.gap_report))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _normalize_text(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", no_tags).strip().lower()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
