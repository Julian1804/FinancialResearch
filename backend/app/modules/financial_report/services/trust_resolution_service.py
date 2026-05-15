from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.provisional_fact_contract import (
    ProvisionalFinancialFact,
    ResolvedFinancialFact,
    TrustResolutionResult,
    TrustResolutionSummary,
)
from backend.app.modules.financial_report.services.parse_lab_field_candidate_ingestion_service import (
    PROVISIONAL_FACT_OUTPUT_DIR,
    ingest_parse_lab_round3_field_candidates,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
TRUST_RESOLUTION_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "trust_resolution" / "parse_lab_round3"
)

TRUSTED_STATUSES = {"trusted_by_text", "trusted_by_external"}
CANDIDATE_STATUSES = {"validated_candidate", "candidate_only"}
CORE_FIELD_KEYWORDS = {
    "revenue",
    "profit",
    "loss",
    "income",
    "sales",
    "cost",
    "expense",
    "expenses",
    "asset",
    "assets",
    "liability",
    "liabilities",
    "equity",
    "cash",
    "operating",
    "net",
    "gross",
    "comprehensive",
    "收入",
    "收益",
    "营收",
    "營收",
    "利润",
    "利潤",
    "亏损",
    "虧損",
    "资产",
    "資產",
    "负债",
    "負債",
    "权益",
    "權益",
    "现金",
    "現金",
    "成本",
    "费用",
    "費用",
    "開支",
    "合计",
    "合計",
}
NON_CORE_HINTS = {
    "participant",
    "employee",
    "director",
    "vesting",
    "shares granted",
    "share award",
    "date",
    "number of award",
    "相關獎勵對象",
    "獎勵股份",
    "归属",
    "歸屬",
}
CORE_FIELD_RULE = (
    "Core fields are recognized when field_name or evidence_text contains financial statement terms "
    "for revenue/profit/loss/income/assets/liabilities/equity/cash/cost/expense or their Chinese "
    "equivalents, excluding obvious share-award/admin labels."
)


def resolve_parse_lab_round3_trust(
    source_dir: Path | str = PROVISIONAL_FACT_OUTPUT_DIR,
    output_dir: Path | str = TRUST_RESOLUTION_OUTPUT_DIR,
) -> TrustResolutionResult:
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    provisional_facts = _load_provisional_facts(source_dir)

    warnings: list[str] = []
    errors: list[str] = []
    resolved: list[ResolvedFinancialFact] = []
    for index, fact in enumerate(provisional_facts, start=1):
        resolved_fact = _resolve_fact(fact, index)
        validation_errors = _validate_resolved_fact(resolved_fact)
        if validation_errors:
            errors.extend(validation_errors)
            continue
        resolved.append(resolved_fact)

    trusted_facts = [fact for fact in resolved if fact.trust_status in TRUSTED_STATUSES]
    validated_candidates = [fact for fact in resolved if fact.trust_status == "validated_candidate"]
    candidate_only_facts = [fact for fact in resolved if fact.trust_status == "candidate_only"]
    needs_human_review = [fact for fact in resolved if fact.trust_status == "needs_human_review"]
    rejected_facts = [fact for fact in resolved if fact.trust_status == "rejected"]

    summary = _build_summary(
        source_dir=source_dir,
        output_dir=output_dir,
        input_count=len(provisional_facts),
        resolved=resolved,
        trusted_facts=trusted_facts,
        validated_candidates=validated_candidates,
        candidate_only_facts=candidate_only_facts,
        needs_human_review=needs_human_review,
        rejected_facts=rejected_facts,
        warnings=warnings,
        errors=errors,
    )
    result = TrustResolutionResult(
        summary=summary,
        trusted_facts=trusted_facts,
        validated_candidates=validated_candidates,
        candidate_only_facts=candidate_only_facts,
        needs_human_review=needs_human_review,
        rejected_facts=rejected_facts,
    )
    _write_outputs(output_dir, result)
    return result


def load_trusted_facts_for_analysis(
    resolution_dir: Path | str = TRUST_RESOLUTION_OUTPUT_DIR,
) -> list[ResolvedFinancialFact]:
    resolution_dir = Path(resolution_dir)
    trusted_path = resolution_dir / "analysis_consumption_trusted_facts.json"
    if not trusted_path.exists():
        resolve_parse_lab_round3_trust(output_dir=resolution_dir)
    payload = _read_json(trusted_path, {"items": []})
    facts = [ResolvedFinancialFact(**row) for row in payload.get("items", [])]
    return [fact for fact in facts if fact.trusted and fact.trust_status in TRUSTED_STATUSES]


def summarize_trust_resolution(result: TrustResolutionResult) -> dict[str, Any]:
    return _model_dump(result.summary)


def is_core_financial_field(fact: ProvisionalFinancialFact | ResolvedFinancialFact) -> bool:
    text = _normalize_text(f"{fact.field_name} {fact.evidence_text}")
    if any(hint in text for hint in NON_CORE_HINTS):
        return False
    return any(keyword in text for keyword in CORE_FIELD_KEYWORDS)


def _load_provisional_facts(source_dir: Path) -> list[ProvisionalFinancialFact]:
    json_path = source_dir / "provisional_facts.json"
    jsonl_path = source_dir / "provisional_facts.jsonl"
    if not json_path.exists() and not jsonl_path.exists():
        ingest_parse_lab_round3_field_candidates(output_dir=source_dir)
    if json_path.exists():
        payload = _read_json(json_path, {"items": []})
        return [ProvisionalFinancialFact(**row) for row in payload.get("items", [])]
    return [ProvisionalFinancialFact(**row) for row in _read_jsonl(jsonl_path)]


def _resolve_fact(fact: ProvisionalFinancialFact, index: int) -> ResolvedFinancialFact:
    is_core = is_core_financial_field(fact)
    external_match = _simulate_external_provider_match(fact, is_core)
    trust_status = "candidate_only"
    trust_reason = "unverified_candidate_retained_outside_analysis_layer"
    external_provider = ""
    trusted = False
    candidate_only = True

    if fact.validation_status == "conflict":
        trust_status = "rejected"
        trust_reason = "source_conflict_rejects_candidate_until_reconciliation"
    elif _is_direct_text_fact(fact):
        trust_status = "trusted_by_text"
        trust_reason = "financial_report_text_source_is_automatically_trusted"
        trusted = True
        candidate_only = False
    elif fact.validation_status == "matched" and is_core and fact.evidence_text:
        trust_status = "trusted_by_text"
        trust_reason = "core_field_matched_report_text_evidence"
        trusted = True
        candidate_only = False
    elif external_match:
        trust_status = "trusted_by_external"
        trust_reason = "simulated_authoritative_external_provider_match"
        external_provider = "simulated_authoritative_financial_data_provider"
        trusted = True
        candidate_only = False
    elif fact.validation_status == "matched" and fact.evidence_text:
        trust_status = "validated_candidate"
        trust_reason = "text_table_validation_passed_but_field_is_not_core_financial_fact"
    elif fact.validation_status == "partially_matched" and is_core:
        trust_status = "needs_human_review"
        trust_reason = "core_field_partially_matched_without_text_or_external_trust"
    elif fact.validation_status == "partially_matched":
        trust_status = "candidate_only"
        trust_reason = "non_core_partial_match_retained_without_human_review"

    provenance = dict(fact.provenance)
    provenance.update(
        {
            "trust_resolution_policy": "trusted_only_analysis_consumption",
            "core_field_rule": CORE_FIELD_RULE,
            "original_candidate_only": fact.candidate_only,
            "original_trusted": fact.trusted,
        }
    )
    return ResolvedFinancialFact(
        fact_id=f"parse_lab_round3_resolved_{index:04d}",
        original_fact_id=fact.fact_id,
        field_name=fact.field_name,
        value=fact.value,
        unit=fact.unit,
        currency=fact.currency,
        period=fact.period,
        source_pdf=fact.source_pdf,
        source_page=fact.source_page,
        source_type=fact.source_type,
        evidence_text=fact.evidence_text,
        table_id=fact.table_id,
        engine_name=fact.engine_name,
        validation_status=fact.validation_status,
        confidence=fact.confidence,
        trust_status=trust_status,
        trust_reason=trust_reason,
        candidate_only_reason=fact.candidate_only_reason,
        is_core_field=is_core,
        external_provider=external_provider,
        trusted=trusted,
        candidate_only=candidate_only,
        provenance=provenance,
    )


def _simulate_external_provider_match(fact: ProvisionalFinancialFact, is_core: bool) -> bool:
    if not is_core or fact.value in (None, ""):
        return False
    if fact.validation_status not in {"matched", "partially_matched"}:
        return False
    try:
        float(fact.value)
    except (TypeError, ValueError):
        return False
    text = _normalize_text(f"{fact.field_name} {fact.evidence_text}")
    provider_keywords = {"revenue", "profit", "income", "assets", "liabilities", "收入", "收益", "利润", "利潤", "資產", "资产", "負債", "负债"}
    return fact.validation_status == "partially_matched" and any(keyword in text for keyword in provider_keywords)


def _is_direct_text_fact(fact: ProvisionalFinancialFact) -> bool:
    return fact.source_type == "text" and bool(fact.evidence_text)


def _validate_resolved_fact(fact: ResolvedFinancialFact) -> list[str]:
    errors: list[str] = []
    if fact.trust_status in TRUSTED_STATUSES and not fact.trusted:
        errors.append(f"{fact.fact_id}: trusted status must set trusted=true")
    if fact.trust_status not in TRUSTED_STATUSES and fact.trusted:
        errors.append(f"{fact.fact_id}: non-trusted status must set trusted=false")
    if fact.trust_status in CANDIDATE_STATUSES and not fact.candidate_only:
        errors.append(f"{fact.fact_id}: candidate status must remain candidate_only")
    if fact.trust_status == "needs_human_review" and not fact.is_core_field:
        errors.append(f"{fact.fact_id}: human review is only allowed for core fields")
    for field in (
        "field_name",
        "source_pdf",
        "source_page",
        "source_type",
        "validation_status",
        "confidence",
    ):
        if getattr(fact, field) in ("", None):
            errors.append(f"{fact.fact_id}: missing provenance field {field}")
    return errors


def _build_summary(
    source_dir: Path,
    output_dir: Path,
    input_count: int,
    resolved: list[ResolvedFinancialFact],
    trusted_facts: list[ResolvedFinancialFact],
    validated_candidates: list[ResolvedFinancialFact],
    candidate_only_facts: list[ResolvedFinancialFact],
    needs_human_review: list[ResolvedFinancialFact],
    rejected_facts: list[ResolvedFinancialFact],
    warnings: list[str],
    errors: list[str],
) -> TrustResolutionSummary:
    trusted_by_text_count = sum(1 for fact in trusted_facts if fact.trust_status == "trusted_by_text")
    trusted_by_external_count = sum(1 for fact in trusted_facts if fact.trust_status == "trusted_by_external")
    return TrustResolutionSummary(
        resolution_id="parse_lab_round3_trust_resolution",
        source_dir=str(source_dir),
        output_dir=str(output_dir),
        total_input_fact_count=input_count,
        trusted_fact_count=len(trusted_facts),
        trusted_by_text_count=trusted_by_text_count,
        trusted_by_external_count=trusted_by_external_count,
        validated_candidate_count=len(validated_candidates),
        candidate_only_count=len(candidate_only_facts),
        needs_human_review_count=len(needs_human_review),
        rejected_count=len(rejected_facts),
        core_field_count=sum(1 for fact in resolved if fact.is_core_field),
        non_core_field_count=sum(1 for fact in resolved if not fact.is_core_field),
        trust_status_distribution=dict(Counter(fact.trust_status for fact in resolved)),
        validation_status_distribution=dict(Counter(fact.validation_status for fact in resolved)),
        source_pdf_distribution=dict(Counter(fact.source_pdf for fact in resolved)),
        analysis_consumption_policy="trusted_only",
        core_field_rule=CORE_FIELD_RULE,
        warnings=warnings,
        errors=errors,
    )


def _write_outputs(output_dir: Path, result: TrustResolutionResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    trusted_facts = [_model_dump(fact) for fact in result.trusted_facts]
    validated_candidates = [_model_dump(fact) for fact in result.validated_candidates]
    candidate_only_facts = [_model_dump(fact) for fact in result.candidate_only_facts]
    needs_human_review = [_model_dump(fact) for fact in result.needs_human_review]
    rejected_facts = [_model_dump(fact) for fact in result.rejected_facts]
    _write_json(output_dir / "trusted_facts.json", {"items": trusted_facts, "count": len(trusted_facts)})
    _write_json(output_dir / "validated_candidates.json", {"items": validated_candidates, "count": len(validated_candidates)})
    _write_json(output_dir / "candidate_only_facts.json", {"items": candidate_only_facts, "count": len(candidate_only_facts)})
    _write_json(output_dir / "needs_human_review.json", {"items": needs_human_review, "count": len(needs_human_review)})
    _write_json(output_dir / "rejected_facts.json", {"items": rejected_facts, "count": len(rejected_facts)})
    _write_json(output_dir / "analysis_consumption_trusted_facts.json", {"items": trusted_facts, "count": len(trusted_facts)})
    _write_json(output_dir / "trust_resolution_summary.json", _model_dump(result.summary))


def _normalize_text(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", no_tags).strip().lower()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
