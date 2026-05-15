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
    TrustedFactEnrichmentGapReport,
    TrustedFactEnrichmentResult,
    TrustedFactEnrichmentSummary,
)
from backend.app.modules.financial_report.services.trust_resolution_service import (
    TRUSTED_STATUSES,
    load_trusted_facts_for_analysis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
ENRICHED_TRUSTED_FACT_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "metadata_enrichment" / "parse_lab_round3_trusted"
)

CSV_FIELDS = [
    "enriched_fact_id",
    "fact_id",
    "field_name",
    "value_original",
    "value_enriched",
    "unit_original",
    "unit_enriched",
    "currency_original",
    "currency_enriched",
    "period_original",
    "period_enriched",
    "fiscal_year",
    "fiscal_period_type",
    "source_pdf",
    "source_page",
    "trust_status",
    "enrichment_status",
]

PERIOD_HALF_YEAR_TOKENS = (
    "\u4e2d\u62a5",
    "\u534a\u5e74",
    "interim",
    "half year",
    "six months",
)
PERIOD_ANNUAL_TOKENS = ("\u5e74\u62a5", "annual", "twelve months")
CNY_TOKENS = ("rmb", "cny", "\u4eba\u6c11\u5e63", "\u4eba\u6c11\u5e01")
HKD_TOKENS = ("hkd", "\u6e2f\u5143")
USD_TOKENS = ("usd", "\u7f8e\u5143")
THOUSAND_TOKENS = ("rmb'000", "rmb\u2019000", "\u5343\u5143")
MILLION_TOKENS = ("million", "\u767e\u4e07\u5143", "\u767e\u842c\u5143")


def enrich_parse_lab_round3_trusted_fact_metadata(
    output_dir: Path | str = ENRICHED_TRUSTED_FACT_OUTPUT_DIR,
) -> TrustedFactEnrichmentResult:
    output_dir = Path(output_dir)
    trusted_facts = load_trusted_facts_for_analysis()
    enriched_facts = [_enrich_fact(fact, index) for index, fact in enumerate(trusted_facts, start=1)]
    errors = _validate_enriched_facts(enriched_facts)
    gap_report = _build_gap_report(enriched_facts)
    summary = _build_summary(output_dir, enriched_facts, errors)
    result = TrustedFactEnrichmentResult(
        summary=summary,
        gap_report=gap_report,
        enriched_facts=enriched_facts,
    )
    _write_outputs(output_dir, result)
    return result


def summarize_enrichment_result(result: TrustedFactEnrichmentResult) -> dict[str, Any]:
    return _model_dump(result.summary)


def _enrich_fact(fact: ResolvedFinancialFact, index: int) -> EnrichedTrustedFinancialFact:
    sources: list[dict[str, Any]] = []
    period, fiscal_year, fiscal_period_type, period_status = _enrich_period(fact, sources)
    currency, currency_status = _enrich_currency(fact, sources)
    unit, multiplier, unit_status = _enrich_unit(fact, sources)
    value, value_status = _enrich_value(fact.value, multiplier)

    metadata_status = {
        "period": period_status,
        "currency": currency_status,
        "unit": unit_status,
        "value": value_status,
    }
    metadata_gaps = [
        name
        for name, status in metadata_status.items()
        if status == "insufficient_evidence"
    ]
    if period and currency and unit and value is not None:
        enrichment_status = "enriched"
    elif sources:
        enrichment_status = "partially_enriched"
    else:
        enrichment_status = "insufficient_evidence"

    provenance = dict(fact.provenance)
    provenance.update(
        {
            "metadata_enrichment_input": "load_trusted_facts_for_analysis",
            "metadata_enrichment_policy": "trusted_only_metadata_enrichment_with_source_confidence",
            "source_fact_id": fact.fact_id,
            "source_original_fact_id": fact.original_fact_id,
        }
    )
    return EnrichedTrustedFinancialFact(
        enriched_fact_id=f"parse_lab_round3_enriched_{index:04d}",
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
        period_enriched=period,
        fiscal_year=fiscal_year,
        fiscal_period_type=fiscal_period_type,
        currency_enriched=currency,
        unit_enriched=unit,
        value_enriched=value,
        enrichment_status=enrichment_status,
        metadata_status=metadata_status,
        enrichment_sources=sources,
        metadata_gaps=metadata_gaps,
        provenance=provenance,
    )


def _enrich_period(
    fact: ResolvedFinancialFact,
    sources: list[dict[str, Any]],
) -> tuple[str, int | None, str, str]:
    existing_text = _normalize_text(fact.period)
    source_pdf_text = _normalize_text(fact.source_pdf)
    evidence_text = _normalize_text(fact.evidence_text)
    fiscal_year = _extract_year(existing_text) or _extract_year(source_pdf_text) or _extract_year(evidence_text)
    if not fiscal_year:
        return "", None, "", "insufficient_evidence"

    if fact.period:
        period_type = _period_type_from_text(existing_text)
        if period_type:
            sources.append(_source("period", "existing_field", 1.0, fact.period, fact.source_page))
            return _period_value(fiscal_year, period_type), fiscal_year, period_type, "enriched"

    period_type = _period_type_from_text(source_pdf_text)
    if period_type:
        sources.append(_source("period", "filename", 0.86, _matched_period_text(fact.source_pdf), fact.source_page))
        return _period_value(fiscal_year, period_type), fiscal_year, period_type, "enriched"

    period_type = _period_type_from_text(evidence_text)
    if period_type:
        sources.append(_source("period", "evidence_text", 0.74, _matched_period_text(fact.evidence_text), fact.source_page))
        return _period_value(fiscal_year, period_type), fiscal_year, period_type, "enriched"
    return "", fiscal_year, "", "insufficient_evidence"


def _enrich_currency(
    fact: ResolvedFinancialFact,
    sources: list[dict[str, Any]],
) -> tuple[str, str]:
    for field_name, raw_text, inference_source, confidence in _metadata_text_sources(fact):
        normalized = _normalize_text(raw_text)
        currency, matched_text = _currency_from_text(normalized, raw_text)
        if currency:
            sources.append(_source("currency", inference_source, confidence, matched_text, fact.source_page, field_name))
            return currency, "enriched"
    return "", "insufficient_evidence"


def _enrich_unit(
    fact: ResolvedFinancialFact,
    sources: list[dict[str, Any]],
) -> tuple[str, float | None, str]:
    for field_name, raw_text, inference_source, confidence in _metadata_text_sources(fact):
        normalized = _normalize_text(raw_text)
        unit, multiplier, matched_text = _unit_from_text(normalized, raw_text)
        if unit:
            sources.append(_source("unit", inference_source, confidence, matched_text, fact.source_page, field_name))
            return unit, multiplier, "enriched"
    return "", None, "insufficient_evidence"


def _enrich_value(value: Any, multiplier: float | None) -> tuple[float | None, str]:
    if multiplier is None:
        return None, "insufficient_evidence"
    try:
        return float(value) * multiplier, "enriched"
    except (TypeError, ValueError):
        return None, "insufficient_evidence"


def _metadata_text_sources(fact: ResolvedFinancialFact) -> list[tuple[str, str, str, float]]:
    sources = [
        ("currency", fact.currency, "existing_field", 1.0),
        ("unit", fact.unit, "existing_field", 1.0),
        ("evidence_text", fact.evidence_text, "evidence_text", 0.82),
    ]
    table_context = fact.provenance.get("table_context_metadata") if isinstance(fact.provenance, dict) else None
    if isinstance(table_context, dict):
        context_text = " ".join(str(table_context.get(key) or "") for key in ("source_text", "header_text", "caption", "nearby_text"))
        sources.append(("table_context_metadata", context_text, "table_context_metadata", 0.88))
    elif table_context:
        sources.append(("table_context_metadata", str(table_context), "table_context_metadata", 0.84))
    return sources


def _currency_from_text(normalized_text: str, raw_text: str) -> tuple[str, str]:
    if any(token in normalized_text for token in CNY_TOKENS):
        return "CNY", _matched_text(raw_text, CNY_TOKENS)
    if any(token in normalized_text for token in HKD_TOKENS):
        return "HKD", _matched_text(raw_text, HKD_TOKENS)
    if any(token in normalized_text for token in USD_TOKENS):
        return "USD", _matched_text(raw_text, USD_TOKENS)
    return "", ""


def _unit_from_text(normalized_text: str, raw_text: str) -> tuple[str, float | None, str]:
    if any(token in normalized_text for token in THOUSAND_TOKENS):
        return "thousand", 1000.0, _matched_text(raw_text, THOUSAND_TOKENS)
    if any(token in normalized_text for token in MILLION_TOKENS):
        return "million", 1000000.0, _matched_text(raw_text, MILLION_TOKENS)
    return "", None, ""


def _period_type_from_text(text: str) -> str:
    if any(token in text for token in PERIOD_HALF_YEAR_TOKENS):
        return "interim_h1"
    if any(token in text for token in PERIOD_ANNUAL_TOKENS):
        return "annual"
    return ""


def _period_value(fiscal_year: int, fiscal_period_type: str) -> str:
    if fiscal_period_type == "interim_h1":
        return f"FY{fiscal_year}_H1"
    if fiscal_period_type == "annual":
        return f"FY{fiscal_year}"
    return ""


def _source(
    field: str,
    inference_source: str,
    confidence: float,
    matched_text: str,
    source_page: int,
    source_text_field: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "field": field,
        "inference_source": inference_source,
        "confidence": confidence,
        "source_page": source_page,
    }
    if inference_source == "filename":
        payload["matched_text"] = matched_text
    elif inference_source == "evidence_text":
        payload["matched_text"] = matched_text
    elif inference_source == "table_context_metadata":
        payload["source_text"] = matched_text
        payload["source_text_field"] = source_text_field
    else:
        payload["matched_text"] = matched_text
    return payload


def _matched_period_text(raw_text: str) -> str:
    for token in (*PERIOD_HALF_YEAR_TOKENS, *PERIOD_ANNUAL_TOKENS):
        if token in _normalize_text(raw_text):
            return token
    year = _extract_year(raw_text)
    return str(year) if year else ""


def _matched_text(raw_text: str, tokens: tuple[str, ...]) -> str:
    raw_lower = raw_text.lower()
    for token in tokens:
        if token in raw_lower or token in raw_text:
            return token
    return tokens[0] if tokens else ""


def _extract_year(text: str) -> int | None:
    match = re.search(r"20\d{2}", text)
    if not match:
        return None
    return int(match.group(0))


def _validate_enriched_facts(facts: list[EnrichedTrustedFinancialFact]) -> list[str]:
    errors: list[str] = []
    for fact in facts:
        if fact.trust_status not in TRUSTED_STATUSES:
            errors.append(f"{fact.enriched_fact_id}: non-trusted status entered enrichment")
        if not fact.trusted:
            errors.append(f"{fact.enriched_fact_id}: trusted must be true")
        if fact.candidate_only:
            errors.append(f"{fact.enriched_fact_id}: candidate_only must be false")
        for source in fact.enrichment_sources:
            if "inference_source" not in source or "confidence" not in source:
                errors.append(f"{fact.enriched_fact_id}: enrichment source missing inference_source/confidence")
            if source.get("inference_source") == "filename" and source.get("field") == "period" and not source.get("matched_text"):
                errors.append(f"{fact.enriched_fact_id}: filename period inference missing matched_text")
            if source.get("inference_source") == "evidence_text" and not source.get("matched_text"):
                errors.append(f"{fact.enriched_fact_id}: evidence inference missing matched_text")
            if source.get("inference_source") == "table_context_metadata" and not source.get("source_text"):
                errors.append(f"{fact.enriched_fact_id}: table context inference missing source_text")
    return errors


def _build_gap_report(facts: list[EnrichedTrustedFinancialFact]) -> TrustedFactEnrichmentGapReport:
    missing_period = [fact.fact_id for fact in facts if not fact.period_enriched]
    missing_currency = [fact.fact_id for fact in facts if not fact.currency_enriched]
    missing_unit = [fact.fact_id for fact in facts if not fact.unit_enriched]
    missing_value = [fact.fact_id for fact in facts if fact.value_enriched is None]
    return TrustedFactEnrichmentGapReport(
        missing_period_count=len(missing_period),
        missing_currency_count=len(missing_currency),
        missing_unit_count=len(missing_unit),
        missing_value_enrichment_count=len(missing_value),
        missing_period_fact_ids=missing_period,
        missing_currency_fact_ids=missing_currency,
        missing_unit_fact_ids=missing_unit,
        missing_value_enrichment_fact_ids=missing_value,
    )


def _build_summary(
    output_dir: Path,
    facts: list[EnrichedTrustedFinancialFact],
    errors: list[str],
) -> TrustedFactEnrichmentSummary:
    source_distribution: Counter[str] = Counter()
    for fact in facts:
        source_distribution.update(source.get("inference_source", "") for source in fact.enrichment_sources)
    return TrustedFactEnrichmentSummary(
        enrichment_id="parse_lab_round3_trusted_fact_metadata_enrichment",
        output_dir=str(output_dir),
        input_trusted_fact_count=len(facts),
        enriched_success_count=sum(1 for fact in facts if fact.enrichment_status in {"enriched", "partially_enriched"}),
        fully_enriched_count=sum(1 for fact in facts if fact.enrichment_status == "enriched"),
        partially_enriched_count=sum(1 for fact in facts if fact.enrichment_status == "partially_enriched"),
        insufficient_evidence_count=sum(1 for fact in facts if fact.metadata_gaps),
        period_enriched_count=sum(1 for fact in facts if fact.period_enriched),
        currency_enriched_count=sum(1 for fact in facts if fact.currency_enriched),
        unit_enriched_count=sum(1 for fact in facts if fact.unit_enriched),
        value_enriched_count=sum(1 for fact in facts if fact.value_enriched is not None),
        candidate_input_count=sum(1 for fact in facts if fact.candidate_only or fact.trust_status not in TRUSTED_STATUSES),
        enrichment_status_distribution=dict(Counter(fact.enrichment_status for fact in facts)),
        trust_status_distribution=dict(Counter(fact.trust_status for fact in facts)),
        source_pdf_distribution=dict(Counter(fact.source_pdf for fact in facts)),
        enrichment_source_distribution=dict(source_distribution),
        errors=errors,
    )


def _write_outputs(output_dir: Path, result: TrustedFactEnrichmentResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched_facts = [_model_dump(fact) for fact in result.enriched_facts]
    _write_json(output_dir / "enriched_trusted_facts.json", {"items": enriched_facts, "count": len(enriched_facts)})
    _write_csv(output_dir / "enriched_trusted_facts.csv", enriched_facts)
    _write_json(output_dir / "enrichment_summary.json", _model_dump(result.summary))
    _write_json(output_dir / "enrichment_gap_report.json", _model_dump(result.gap_report))


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
