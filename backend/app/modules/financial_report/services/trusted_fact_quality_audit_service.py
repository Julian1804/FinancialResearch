from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.provisional_fact_contract import (
    EnrichedTrustedFinancialFact,
    ResolvedFinancialFact,
    TrustedFactQualityAuditRecord,
    TrustedFactQualityAuditResult,
    TrustedFactQualityAuditSummary,
)
from backend.app.modules.financial_report.services.trust_resolution_service import TRUSTED_STATUSES
from backend.app.modules.financial_report.services.trusted_fact_metadata_enrichment_service import (
    enrich_parse_lab_round3_trusted_fact_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "quality_audit" / "parse_lab_round3_trusted"
)

AUDIT_CSV_FIELDS = [
    "audit_record_id",
    "fact_id",
    "field_name",
    "value_original",
    "source_pdf",
    "source_page",
    "trust_status_before",
    "audit_decision",
    "revised_trust_status",
    "canonical_field_name",
    "value_interpretability",
    "downgrade_reasons",
]

HEADER_OR_NOTE_TOKENS = {
    "note",
    "附註",
    "附注",
    "1 year",
    "5 years",
    "years",
    "table header",
    "column header",
    "balance at",
    "income approach",
    "合计",
    "合計",
}

CANONICAL_FIELD_PATTERNS = {
    "cost": ("cost", "成本"),
    "profit_for_period": ("profit for the period", "期內溢利", "期内溢利"),
    "currency_translation_difference": ("currency translation difference", "貨幣換算差額", "货币换算差额"),
    "fixed_assets": ("fixed assets", "固定资产", "固定資產"),
    "intangible_assets": ("intangible assets", "无形资产", "無形資產"),
    "derivative_financial_assets": ("derivative financial assets", "衍生金融资产", "衍生金融資產"),
    "other_equity_instruments": ("other equity instruments", "其他权益工具", "其他權益工具"),
}


def audit_parse_lab_round3_trusted_fact_quality(
    output_dir: Path | str = TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR,
) -> TrustedFactQualityAuditResult:
    output_dir = Path(output_dir)
    enrichment_result = enrich_parse_lab_round3_trusted_fact_metadata()
    audit_records: list[TrustedFactQualityAuditRecord] = []
    downgraded_facts: list[EnrichedTrustedFinancialFact] = []
    revised_trusted_facts: list[ResolvedFinancialFact] = []

    for index, fact in enumerate(enrichment_result.enriched_facts, start=1):
        record, revised_fact = _audit_fact(fact, index)
        audit_records.append(record)
        if record.audit_decision == "keep_trusted" and revised_fact:
            revised_trusted_facts.append(revised_fact)
        else:
            downgraded_facts.append(fact)

    errors = _validate_audit(audit_records, revised_trusted_facts)
    summary = _build_summary(output_dir, audit_records, revised_trusted_facts, errors)
    result = TrustedFactQualityAuditResult(
        summary=summary,
        audit_records=audit_records,
        downgraded_facts=downgraded_facts,
        revised_trusted_facts=revised_trusted_facts,
    )
    _write_outputs(output_dir, result)
    return result


def load_revised_trusted_facts_for_analysis(
    output_dir: Path | str = TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR,
) -> list[ResolvedFinancialFact]:
    output_dir = Path(output_dir)
    trusted_path = output_dir / "revised_analysis_consumption_trusted_facts.json"
    if not trusted_path.exists():
        audit_parse_lab_round3_trusted_fact_quality(output_dir)
    payload = _read_json(trusted_path, {"items": []})
    facts = [ResolvedFinancialFact(**row) for row in payload.get("items", [])]
    return [fact for fact in facts if fact.trusted and not fact.candidate_only and fact.trust_status in TRUSTED_STATUSES]


def summarize_quality_audit_result(result: TrustedFactQualityAuditResult) -> dict[str, Any]:
    return _model_dump(result.summary)


def _audit_fact(
    fact: EnrichedTrustedFinancialFact,
    index: int,
) -> tuple[TrustedFactQualityAuditRecord, ResolvedFinancialFact | None]:
    reasons: list[str] = []
    warnings: list[str] = []
    canonical_field_name = _canonical_field_name(fact.field_name)
    value_interpretability = "interpretable"

    if _is_note_header_or_time_bucket(fact.field_name):
        reasons.append("field_name_is_note_header_or_time_bucket")
    if not canonical_field_name:
        reasons.append("field_name_not_in_canonical_mapping")
    if not fact.provenance:
        reasons.append("missing_provenance")
    if fact.source_page <= 0:
        reasons.append("invalid_source_page")
    if _is_amount_like_field(canonical_field_name or fact.field_name):
        if not fact.currency_enriched or not fact.unit_enriched or fact.value_enriched is None:
            reasons.append("amount_missing_currency_unit_or_value_normalized")
    if _looks_like_split_number_fragment(fact):
        reasons.append("value_looks_like_split_number_fragment")
        value_interpretability = "split_number_fragment"

    if reasons:
        audit_decision = "downgrade"
        revised_trust_status = "candidate_only"
    else:
        audit_decision = "keep_trusted"
        revised_trust_status = fact.trust_status

    record = TrustedFactQualityAuditRecord(
        audit_record_id=f"parse_lab_round3_quality_audit_{index:04d}",
        fact_id=fact.fact_id,
        field_name=fact.field_name,
        value_original=fact.value_original,
        source_pdf=fact.source_pdf,
        source_page=fact.source_page,
        trust_status_before=fact.trust_status,
        audit_decision=audit_decision,
        revised_trust_status=revised_trust_status,
        downgrade_reasons=reasons,
        canonical_field_name=canonical_field_name,
        value_interpretability=value_interpretability,
        metadata_status=fact.metadata_status,
        quality_warnings=warnings,
        provenance=_audit_provenance(fact),
    )
    if audit_decision != "keep_trusted":
        return record, None
    return record, _revised_fact_from_enriched(fact, canonical_field_name)


def _revised_fact_from_enriched(
    fact: EnrichedTrustedFinancialFact,
    canonical_field_name: str,
) -> ResolvedFinancialFact:
    provenance = dict(fact.provenance)
    provenance.update(
        {
            "quality_audit_decision": "keep_trusted",
            "canonical_field_name": canonical_field_name,
            "metadata_enrichment": {
                "period": fact.period_enriched,
                "fiscal_year": fact.fiscal_year,
                "fiscal_period_type": fact.fiscal_period_type,
                "currency": fact.currency_enriched,
                "unit": fact.unit_enriched,
                "value_enriched": fact.value_enriched,
            },
        }
    )
    return ResolvedFinancialFact(
        fact_id=fact.fact_id,
        original_fact_id=fact.original_fact_id,
        field_name=fact.field_name,
        value=fact.value_enriched if fact.value_enriched is not None else fact.value_original,
        unit=fact.unit_enriched or fact.unit_original,
        currency=fact.currency_enriched or fact.currency_original,
        period=fact.period_enriched or fact.period_original,
        source_pdf=fact.source_pdf,
        source_page=fact.source_page,
        source_type=fact.source_type,
        evidence_text=fact.evidence_text,
        table_id=fact.table_id,
        engine_name=fact.engine_name,
        validation_status=fact.validation_status,
        confidence=fact.confidence,
        trust_status=fact.trust_status,
        trust_reason="quality_audit_revised_trusted_fact",
        candidate_only_reason="",
        is_core_field=True,
        trusted=True,
        candidate_only=False,
        provenance=provenance,
    )


def _canonical_field_name(field_name: str) -> str:
    normalized = _normalize_text(field_name)
    for canonical, patterns in CANONICAL_FIELD_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return canonical
    return ""


def _is_note_header_or_time_bucket(field_name: str) -> bool:
    normalized = _normalize_text(field_name)
    if any(token in normalized for token in HEADER_OR_NOTE_TOKENS):
        return True
    return bool(re.fullmatch(r"\d+\s*years?", normalized))


def _is_amount_like_field(field_name: str) -> bool:
    normalized = _normalize_text(field_name)
    return any(
        token in normalized
        for token in (
            "cost",
            "profit",
            "income",
            "asset",
            "equity",
            "difference",
            "成本",
            "资产",
            "資產",
            "权益",
            "權益",
            "收益",
            "溢利",
            "差額",
            "差额",
        )
    )


def _looks_like_split_number_fragment(fact: EnrichedTrustedFinancialFact) -> bool:
    try:
        value = float(fact.value_original)
    except (TypeError, ValueError):
        return False
    if value < 0 or value >= 1000 or value != int(value):
        return False
    text = fact.evidence_text
    integer = str(int(value))
    return bool(re.search(rf"(?<!\d){re.escape(integer)}\s*,\s*\d{{3}}", text))


def _audit_provenance(fact: EnrichedTrustedFinancialFact) -> dict[str, Any]:
    provenance = dict(fact.provenance)
    provenance.update(
        {
            "quality_audit_input": "enriched_trusted_facts",
            "quality_audit_policy": "canonical_field_and_minimum_metadata_required_for_analysis",
            "enrichment_sources": fact.enrichment_sources,
            "metadata_gaps": fact.metadata_gaps,
        }
    )
    return provenance


def _validate_audit(
    audit_records: list[TrustedFactQualityAuditRecord],
    revised_trusted_facts: list[ResolvedFinancialFact],
) -> list[str]:
    errors: list[str] = []
    for fact in revised_trusted_facts:
        if _is_note_header_or_time_bucket(fact.field_name):
            errors.append(f"{fact.fact_id}: note/header/time bucket remained trusted")
        if fact.trust_status not in TRUSTED_STATUSES or not fact.trusted or fact.candidate_only:
            errors.append(f"{fact.fact_id}: revised trusted fact failed trusted-only guard")
        if not fact.currency or not fact.unit or not fact.period:
            errors.append(f"{fact.fact_id}: revised trusted fact missing minimum metadata")
    if any(record.audit_decision == "keep_trusted" and record.downgrade_reasons for record in audit_records):
        errors.append("kept trusted record has downgrade reasons")
    return errors


def _build_summary(
    output_dir: Path,
    audit_records: list[TrustedFactQualityAuditRecord],
    revised_trusted_facts: list[ResolvedFinancialFact],
    errors: list[str],
) -> TrustedFactQualityAuditSummary:
    reasons = Counter(reason for record in audit_records for reason in record.downgrade_reasons)
    note_or_year_excluded = all(
        not _is_note_header_or_time_bucket(fact.field_name)
        for fact in revised_trusted_facts
    )
    return TrustedFactQualityAuditSummary(
        audit_id="parse_lab_round3_trusted_fact_quality_audit",
        output_dir=str(output_dir),
        original_trusted_count=len(audit_records),
        revised_trusted_count=len(revised_trusted_facts),
        downgraded_count=len(audit_records) - len(revised_trusted_facts),
        downgrade_reason_distribution=dict(reasons),
        audit_decision_distribution=dict(Counter(record.audit_decision for record in audit_records)),
        revised_analysis_consumption_policy="revised_trusted_only",
        note_or_year_excluded=note_or_year_excluded,
        missing_metadata_amount_handling=(
            "amount-like fields missing currency, unit, or normalized value are downgraded to candidate_only"
        ),
        candidate_retained=True,
        errors=errors,
    )


def _write_outputs(output_dir: Path, result: TrustedFactQualityAuditResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_records = [_model_dump(record) for record in result.audit_records]
    downgraded_facts = [_model_dump(fact) for fact in result.downgraded_facts]
    revised_trusted_facts = [_model_dump(fact) for fact in result.revised_trusted_facts]
    _write_json(output_dir / "trusted_fact_quality_audit.json", {"items": audit_records, "count": len(audit_records)})
    _write_csv(output_dir / "trusted_fact_quality_audit.csv", audit_records)
    _write_json(output_dir / "downgraded_facts.json", {"items": downgraded_facts, "count": len(downgraded_facts)})
    _write_json(output_dir / "revised_trusted_facts.json", {"items": revised_trusted_facts, "count": len(revised_trusted_facts)})
    _write_json(
        output_dir / "revised_analysis_consumption_trusted_facts.json",
        {"items": revised_trusted_facts, "count": len(revised_trusted_facts)},
    )
    _write_json(output_dir / "trust_gate_refinement_summary.json", _model_dump(result.summary))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _normalize_text(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", no_tags).strip().lower()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
