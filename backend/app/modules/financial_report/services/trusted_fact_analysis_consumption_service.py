from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.provisional_fact_contract import (
    ResolvedFinancialFact,
    TrustedFactGroupSummary,
    TrustedFactsAnalysisConsumptionResult,
    TrustedFactsAnalysisDigest,
)
from backend.app.modules.financial_report.services.trust_resolution_service import (
    TRUSTED_STATUSES,
    TRUST_RESOLUTION_OUTPUT_DIR,
    load_trusted_facts_for_analysis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
ANALYSIS_CONSUMPTION_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "analysis_consumption" / "parse_lab_round3_trusted"
)

REQUIRED_ANALYSIS_CATEGORIES = {
    "revenue_or_income": {"revenue", "income", "sales", "收入", "收益", "營收", "营收"},
    "profit_or_loss": {"profit", "loss", "net", "利润", "利潤", "亏损", "虧損"},
    "balance_sheet": {"assets", "liabilities", "equity", "资产", "資產", "负债", "負債", "权益", "權益"},
    "cash_flow": {"cash flow", "operating cash", "现金流", "現金流", "经营现金", "經營現金"},
}


def build_parse_lab_round3_trusted_analysis_consumption(
    output_dir: Path | str = ANALYSIS_CONSUMPTION_OUTPUT_DIR,
) -> TrustedFactsAnalysisConsumptionResult:
    output_dir = Path(output_dir)
    trusted_facts = load_trusted_facts_for_analysis(TRUST_RESOLUTION_OUTPUT_DIR)
    consumption_payload = _trusted_only_payload(trusted_facts)
    grouped_summary = _group_trusted_facts(consumption_payload)
    digest = _build_digest(consumption_payload, grouped_summary)
    result = TrustedFactsAnalysisConsumptionResult(
        digest=digest,
        grouped_summary=grouped_summary,
        consumption_payload=consumption_payload,
    )
    _write_outputs(output_dir, result)
    return result


def summarize_analysis_consumption(result: TrustedFactsAnalysisConsumptionResult) -> dict[str, Any]:
    return _model_dump(result.digest)


def _trusted_only_payload(facts: list[ResolvedFinancialFact]) -> list[ResolvedFinancialFact]:
    return [
        fact
        for fact in facts
        if fact.trusted
        and not fact.candidate_only
        and fact.trust_status in TRUSTED_STATUSES
    ]


def _group_trusted_facts(facts: list[ResolvedFinancialFact]) -> list[TrustedFactGroupSummary]:
    groups: dict[tuple[str, int, str, str, str, str], list[ResolvedFinancialFact]] = defaultdict(list)
    for fact in facts:
        key = (
            fact.source_pdf,
            fact.source_page,
            fact.field_name,
            fact.period,
            fact.unit,
            fact.trust_status,
        )
        groups[key].append(fact)

    grouped_summary: list[TrustedFactGroupSummary] = []
    for index, (key, group_facts) in enumerate(sorted(groups.items(), key=lambda item: item[0]), start=1):
        source_pdf, source_page, field_name, period, unit, trust_status = key
        grouped_summary.append(
            TrustedFactGroupSummary(
                group_id=f"parse_lab_round3_trusted_group_{index:04d}",
                source_pdf=source_pdf,
                source_page=source_page,
                field_name=field_name,
                period=period,
                unit=unit,
                trust_status=trust_status,
                fact_count=len(group_facts),
                values=[fact.value for fact in group_facts],
                provenance=[_fact_provenance(fact) for fact in group_facts],
            )
        )
    return grouped_summary


def _build_digest(
    facts: list[ResolvedFinancialFact],
    grouped_summary: list[TrustedFactGroupSummary],
) -> TrustedFactsAnalysisDigest:
    source_pages = {(fact.source_pdf, fact.source_page) for fact in facts}
    return TrustedFactsAnalysisDigest(
        digest_id="parse_lab_round3_trusted_analysis_digest",
        trusted_fact_count=len(facts),
        source_pdf_count=len({fact.source_pdf for fact in facts}),
        source_page_count=len(source_pages),
        field_group_count=len(grouped_summary),
        trust_status_distribution=dict(Counter(fact.trust_status for fact in facts)),
        source_pdf_distribution=dict(Counter(fact.source_pdf for fact in facts)),
        insufficient_trusted_evidence=_find_insufficient_trusted_evidence(facts),
        notes=[
            "Digest is intentionally small and does not perform forecasting, backtesting, or valuation.",
            "Consumption payload is populated only through load_trusted_facts_for_analysis().",
        ],
    )


def _find_insufficient_trusted_evidence(facts: list[ResolvedFinancialFact]) -> list[str]:
    fact_text = _normalize_text(" ".join(f"{fact.field_name} {fact.evidence_text}" for fact in facts))
    insufficient = []
    for category, keywords in REQUIRED_ANALYSIS_CATEGORIES.items():
        if not any(keyword in fact_text for keyword in keywords):
            insufficient.append(f"insufficient_trusted_evidence:{category}")
    if not any(fact.period for fact in facts):
        insufficient.append("insufficient_trusted_evidence:period_normalization")
    if not any(fact.currency for fact in facts):
        insufficient.append("insufficient_trusted_evidence:currency_normalization")
    if len({fact.period for fact in facts if fact.period}) < 2:
        insufficient.append("insufficient_trusted_evidence:multi_period_trend")
    if not facts:
        insufficient.append("insufficient_trusted_evidence:no_trusted_facts")
    return insufficient


def _fact_provenance(fact: ResolvedFinancialFact) -> dict[str, Any]:
    return {
        "fact_id": fact.fact_id,
        "original_fact_id": fact.original_fact_id,
        "field_name": fact.field_name,
        "value": fact.value,
        "unit": fact.unit,
        "currency": fact.currency,
        "period": fact.period,
        "source_pdf": fact.source_pdf,
        "source_page": fact.source_page,
        "source_type": fact.source_type,
        "evidence_text": fact.evidence_text,
        "table_id": fact.table_id,
        "engine_name": fact.engine_name,
        "validation_status": fact.validation_status,
        "confidence": fact.confidence,
        "trust_status": fact.trust_status,
        "trust_reason": fact.trust_reason,
        "provenance": fact.provenance,
    }


def _write_outputs(output_dir: Path, result: TrustedFactsAnalysisConsumptionResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = [_model_dump(fact) for fact in result.consumption_payload]
    grouped_summary = [_model_dump(group) for group in result.grouped_summary]
    _write_json(output_dir / "trusted_facts_consumption_payload.json", {"items": payload, "count": len(payload)})
    _write_json(output_dir / "trusted_facts_grouped_summary.json", {"items": grouped_summary, "count": len(grouped_summary)})
    _write_json(output_dir / "trusted_facts_digest.json", _model_dump(result.digest))


def _normalize_text(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", no_tags).strip().lower()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
