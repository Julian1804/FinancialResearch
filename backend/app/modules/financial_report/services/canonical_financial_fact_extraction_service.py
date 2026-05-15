from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.canonical_fact_contract import (
    CanonicalCandidateOnlyItem,
    CanonicalExtractionResult,
    CanonicalExtractionSummary,
    CanonicalFinancialFieldDefinition,
    CanonicalNeedsHumanReviewItem,
    TrustedCanonicalFinancialFact,
)
from backend.app.modules.financial_report.services.external_provider_interface import (
    ExternalFinancialDataProvider,
    ExternalProviderFact,
    SimulatedExternalFinancialDataProvider,
)
from backend.app.modules.financial_report.services.parse_lab_field_candidate_ingestion_service import (
    DEFAULT_PARSE_LAB_EXPORT_DIR,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
CANONICAL_EXTRACTION_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "canonical_extraction" / "parse_lab_round3"
)

PRODUCTION_TRUSTED_STATUSES = {"trusted_by_text", "trusted_by_real_external"}
DEV_TEST_TRUSTED_STATUSES = {"trusted_by_text", "trusted_by_real_external", "trusted_by_simulated_external"}
TRUSTED_STATUSES = DEV_TEST_TRUSTED_STATUSES
EXCLUDED_FIELD_TOKENS = {
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
}
CANONICAL_FIELD_DEFINITIONS = [
    CanonicalFinancialFieldDefinition(
        canonical_field="revenue",
        aliases=["revenue", "营业收入", "營業收入", "收入", "收益"],
        category="income_statement",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="gross_profit",
        aliases=["gross profit", "毛利", "毛利润", "毛利潤"],
        category="income_statement",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="operating_profit",
        aliases=["operating profit", "经营利润", "經營利潤", "营业利润", "營業利潤"],
        category="income_statement",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="net_profit",
        aliases=["net profit", "profit for the period", "净利润", "淨利潤", "期内溢利", "期內溢利"],
        category="income_statement",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="net_profit_attributable_to_parent",
        aliases=["profit attributable to owners", "profit attributable to shareholders", "归母净利润", "歸母淨利潤", "母公司股东的净利润"],
        category="income_statement",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="total_assets",
        aliases=["total assets", "总资产", "總資產", "资产总计", "資產總計"],
        category="balance_sheet",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="total_liabilities",
        aliases=["total liabilities", "负债合计", "負債合計", "总负债", "總負債"],
        category="balance_sheet",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="total_equity",
        aliases=["total equity", "total shareholders equity", "权益合计", "權益合計", "所有者权益合计"],
        category="balance_sheet",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="operating_cash_flow",
        aliases=["operating cash flow", "net cash flows from operating activities", "经营活动现金流量净额", "經營活動現金流量淨額"],
        category="cash_flow",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="cash_and_cash_equivalents",
        aliases=["cash and cash equivalents", "现金及现金等价物", "現金及現金等價物", "货币资金"],
        category="balance_sheet",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="cost",
        aliases=["cost", "cost of sales", "cost of revenue", "营业成本", "營業成本", "成本"],
        category="income_statement",
    ),
    CanonicalFinancialFieldDefinition(
        canonical_field="expense",
        aliases=["expense", "expenses", "费用", "費用", "开支", "開支"],
        category="income_statement",
    ),
]

TRUSTED_FACT_CSV_FIELDS = [
    "fact_id",
    "canonical_field",
    "original_field_name",
    "value",
    "value_normalized",
    "unit",
    "currency",
    "period",
    "source_pdf",
    "source_page",
    "source_type",
    "trust_status",
    "sufficient_for_analysis",
    "extraction_method",
    "confidence",
    "provider_name",
    "provider_type",
    "retrieved_at",
    "source_url_or_reference",
    "is_simulated",
]


def extract_parse_lab_round3_canonical_financial_facts(
    source_dir: Path | str = DEFAULT_PARSE_LAB_EXPORT_DIR,
    output_dir: Path | str = CANONICAL_EXTRACTION_OUTPUT_DIR,
    external_providers: list[ExternalFinancialDataProvider] | None = None,
) -> CanonicalExtractionResult:
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    raw_candidates = _load_field_candidates(source_dir)
    source_pdfs = sorted({str(row.get("source_pdf") or "") for row in raw_candidates if row.get("source_pdf")})
    page_context = _build_page_context(raw_candidates)

    trusted_by_text, used_candidate_ids = _extract_trusted_by_text(raw_candidates, page_context)
    trusted_by_external = _external_provider_facts(
        source_pdfs,
        trusted_by_text,
        external_providers or [SimulatedExternalFinancialDataProvider()],
    )
    trusted_facts = _dedupe_trusted_facts([*trusted_by_text, *trusted_by_external])
    trusted_keys = {(fact.source_pdf, fact.canonical_field) for fact in trusted_facts}
    needs_human_review = _build_human_review_queue(source_pdfs, trusted_keys)
    candidate_only = _build_candidate_only_items(raw_candidates, used_candidate_ids)
    errors = _validate_trusted_facts(trusted_facts)
    summary = _build_summary(output_dir, trusted_facts, needs_human_review, candidate_only, errors)
    result = CanonicalExtractionResult(
        summary=summary,
        canonical_fields=CANONICAL_FIELD_DEFINITIONS,
        trusted_canonical_facts=trusted_facts,
        needs_human_review=needs_human_review,
        candidate_only=candidate_only,
    )
    _write_outputs(output_dir, result)
    return result


def load_trusted_canonical_facts_for_analysis(
    output_dir: Path | str = CANONICAL_EXTRACTION_OUTPUT_DIR,
    mode: str = "production",
) -> list[TrustedCanonicalFinancialFact]:
    output_dir = Path(output_dir)
    trusted_path = output_dir / "trusted_canonical_facts.json"
    if not trusted_path.exists():
        extract_parse_lab_round3_canonical_financial_facts(output_dir=output_dir)
    payload = _read_json(trusted_path, {"items": []})
    facts = [TrustedCanonicalFinancialFact(**row) for row in payload.get("items", [])]
    allowed_statuses = DEV_TEST_TRUSTED_STATUSES if mode in {"dev", "test"} else PRODUCTION_TRUSTED_STATUSES
    return [
        fact
        for fact in facts
        if fact.trust_status in allowed_statuses
        and fact.sufficient_for_analysis
        and fact.canonical_field in _canonical_field_names()
        and (mode in {"dev", "test"} or not fact.is_simulated)
    ]


def summarize_canonical_extraction_result(result: CanonicalExtractionResult) -> dict[str, Any]:
    return _model_dump(result.summary)


def canonical_field_for_name(field_name: str) -> str:
    normalized = _normalize_text(field_name)
    if _is_excluded_field_name(normalized):
        return ""
    matches: list[tuple[int, str]] = []
    for definition in CANONICAL_FIELD_DEFINITIONS:
        for alias in definition.aliases:
            normalized_alias = _normalize_text(alias)
            if normalized_alias in normalized:
                matches.append((len(normalized_alias), definition.canonical_field))
    if not matches:
        return ""
    return sorted(matches, reverse=True)[0][1]


def _extract_trusted_by_text(
    raw_candidates: list[dict[str, Any]],
    page_context: dict[tuple[str, int], str],
) -> tuple[list[TrustedCanonicalFinancialFact], set[str]]:
    facts: list[TrustedCanonicalFinancialFact] = []
    used_candidate_ids: set[str] = set()
    for row in raw_candidates:
        canonical_field = canonical_field_for_name(str(row.get("field_name") or ""))
        if not canonical_field:
            continue
        if canonical_field != "net_profit":
            continue
        value = _parse_float(row.get("value"))
        if value is None:
            continue
        source_pdf = str(row.get("source_pdf") or "")
        source_page = int(row.get("source_page") or 0)
        context = page_context.get((source_pdf, source_page), "")
        currency, unit, multiplier = _currency_unit_from_text(context)
        period, fiscal_year, fiscal_period_type = _period_from_pdf_name(source_pdf)
        if not all([currency, unit, multiplier, period, fiscal_year, fiscal_period_type]):
            continue
        candidate_id = str(row.get("field_candidate_id") or "")
        used_candidate_ids.add(candidate_id)
        facts.append(
            TrustedCanonicalFinancialFact(
                fact_id=f"text_{candidate_id}",
                canonical_field=canonical_field,
                original_field_name=str(row.get("field_name") or ""),
                value=value,
                value_normalized=value * multiplier,
                unit=unit,
                currency=currency,
                period=period,
                fiscal_year=fiscal_year,
                fiscal_period_type=fiscal_period_type,
                source_pdf=source_pdf,
                source_page=source_page,
                source_type="financial_report_text",
                source_text=str(row.get("evidence_text") or ""),
                trust_status="trusted_by_text",
                sufficient_for_analysis=True,
                extraction_method="canonical_field_name_with_page_text_metadata",
                confidence=0.84,
                provenance={
                    "field_candidate_id": candidate_id,
                    "evidence_id": row.get("evidence_id", ""),
                    "table_candidate_id": row.get("table_candidate_id", ""),
                    "table_candidate_used_for": "auxiliary_text_validation_only",
                    "metadata_source": "same_page_text_context",
                },
            )
        )
    return facts, used_candidate_ids


def _external_provider_facts(
    source_pdfs: list[str],
    text_facts: list[TrustedCanonicalFinancialFact],
    external_providers: list[ExternalFinancialDataProvider],
) -> list[TrustedCanonicalFinancialFact]:
    text_keys = {(fact.source_pdf, fact.canonical_field) for fact in text_facts}
    facts: list[TrustedCanonicalFinancialFact] = []
    for provider in external_providers:
        for external_fact in provider.fetch_canonical_facts(source_pdfs):
            if (external_fact.source_pdf, external_fact.canonical_field) in text_keys:
                continue
            facts.append(_trusted_fact_from_external_provider(external_fact))
    return facts


def _trusted_fact_from_external_provider(external_fact: ExternalProviderFact) -> TrustedCanonicalFinancialFact:
    trust_status = "trusted_by_simulated_external" if external_fact.is_simulated else "trusted_by_real_external"
    return TrustedCanonicalFinancialFact(
        fact_id=f"external_{_slug(external_fact.provider_name)}_{_slug(external_fact.source_pdf)}_{external_fact.canonical_field}",
        canonical_field=external_fact.canonical_field,
        original_field_name=external_fact.canonical_field,
        value=external_fact.value,
        value_normalized=external_fact.value,
        unit=external_fact.unit,
        currency=external_fact.currency,
        period=external_fact.period,
        fiscal_year=external_fact.fiscal_year,
        fiscal_period_type=external_fact.fiscal_period_type,
        source_pdf=external_fact.source_pdf,
        source_page=0,
        source_type=external_fact.provider_type,
        source_text=f"{external_fact.provider_name}: {external_fact.source_url_or_reference}",
        trust_status=trust_status,
        sufficient_for_analysis=True,
        extraction_method="external_provider_interface",
        confidence=external_fact.confidence,
        provider_name=external_fact.provider_name,
        provider_type=external_fact.provider_type,
        retrieved_at=external_fact.retrieved_at,
        source_url_or_reference=external_fact.source_url_or_reference,
        is_simulated=external_fact.is_simulated,
        provenance={
            "provider_name": external_fact.provider_name,
            "provider_type": external_fact.provider_type,
            "retrieved_at": external_fact.retrieved_at.isoformat(),
            "source_url_or_reference": external_fact.source_url_or_reference,
            "is_simulated": external_fact.is_simulated,
            "table_candidate_used_for": "not_used_for_trust",
        },
    )


def _build_human_review_queue(
    source_pdfs: list[str],
    trusted_keys: set[tuple[str, str]],
) -> list[CanonicalNeedsHumanReviewItem]:
    items: list[CanonicalNeedsHumanReviewItem] = []
    for source_pdf in source_pdfs:
        period, _, _ = _period_from_pdf_name(source_pdf)
        for canonical_field in _canonical_field_names():
            if (source_pdf, canonical_field) in trusted_keys:
                continue
            items.append(
                CanonicalNeedsHumanReviewItem(
                    review_item_id=f"canonical_review_{_slug(source_pdf)}_{canonical_field}",
                    canonical_field=canonical_field,
                    source_pdf=source_pdf,
                    period=period,
                    reason="canonical_field_missing_from_text_and_simulated_external_provider",
                    provenance={"review_policy": "core_canonical_field_without_trusted_source"},
                )
            )
    return items


def _build_candidate_only_items(
    raw_candidates: list[dict[str, Any]],
    used_candidate_ids: set[str],
) -> list[CanonicalCandidateOnlyItem]:
    items: list[CanonicalCandidateOnlyItem] = []
    for index, row in enumerate(raw_candidates, start=1):
        candidate_id = str(row.get("field_candidate_id") or f"raw_candidate_{index:04d}")
        if candidate_id in used_candidate_ids:
            continue
        field_name = str(row.get("field_name") or "")
        canonical_field = canonical_field_for_name(field_name)
        reason = "table_or_noncanonical_candidate_not_trusted"
        if _is_excluded_field_name(_normalize_text(field_name)):
            reason = "excluded_note_header_or_time_bucket"
        elif not canonical_field:
            reason = "noncanonical_field_candidate"
        items.append(
            CanonicalCandidateOnlyItem(
                candidate_id=f"canonical_candidate_only_{index:04d}",
                canonical_field=canonical_field,
                original_field_name=field_name,
                value=row.get("value"),
                source_pdf=str(row.get("source_pdf") or ""),
                source_page=int(row.get("source_page") or 0),
                source_type=str(row.get("source_type") or ""),
                evidence_text=str(row.get("evidence_text") or ""),
                candidate_only_reason=reason,
                provenance={
                    "field_candidate_id": candidate_id,
                    "validation_status": row.get("validation_status", ""),
                    "table_id": row.get("table_id", ""),
                    "engine_name": row.get("engine_name", ""),
                    "trusted": False,
                },
            )
        )
    return items


def _dedupe_trusted_facts(facts: list[TrustedCanonicalFinancialFact]) -> list[TrustedCanonicalFinancialFact]:
    deduped: dict[tuple[str, str, str, float], TrustedCanonicalFinancialFact] = {}
    for fact in facts:
        key = (fact.source_pdf, fact.canonical_field, fact.period, fact.value_normalized)
        existing = deduped.get(key)
        if existing is None or fact.confidence > existing.confidence:
            deduped[key] = fact
    return sorted(deduped.values(), key=lambda fact: (fact.source_pdf, fact.canonical_field, fact.trust_status))


def _build_page_context(raw_candidates: list[dict[str, Any]]) -> dict[tuple[str, int], str]:
    context: dict[tuple[str, int], list[str]] = {}
    for row in raw_candidates:
        key = (str(row.get("source_pdf") or ""), int(row.get("source_page") or 0))
        context.setdefault(key, []).append(str(row.get("evidence_text") or ""))
    return {key: " ".join(values) for key, values in context.items()}


def _currency_unit_from_text(text: str) -> tuple[str, str, float | None]:
    normalized = _normalize_text(text)
    currency = "CNY" if any(token in normalized for token in ("rmb", "人民幣", "人民币", "cny")) else ""
    if "rmb'000" in normalized or "rmb’000" in normalized or "千元" in normalized:
        return currency, "thousand", 1000.0
    return currency, "", None


def _period_from_pdf_name(source_pdf: str) -> tuple[str, int | None, str]:
    normalized = _normalize_text(source_pdf)
    match = re.search(r"20\d{2}", normalized)
    if not match:
        return "", None, ""
    fiscal_year = int(match.group(0))
    if "中报" in normalized or "半年" in normalized or "interim" in normalized:
        return f"FY{fiscal_year}_H1", fiscal_year, "interim_h1"
    if "年报" in normalized or "annual" in normalized:
        return f"FY{fiscal_year}", fiscal_year, "annual"
    return "", fiscal_year, ""


def _validate_trusted_facts(facts: list[TrustedCanonicalFinancialFact]) -> list[str]:
    errors: list[str] = []
    for fact in facts:
        if fact.canonical_field not in _canonical_field_names():
            errors.append(f"{fact.fact_id}: noncanonical field entered trusted facts")
        if fact.trust_status not in TRUSTED_STATUSES:
            errors.append(f"{fact.fact_id}: invalid trust status")
        if fact.trust_status in {"trusted_by_real_external", "trusted_by_simulated_external"}:
            for provider_field in ("provider_name", "provider_type", "retrieved_at", "source_url_or_reference"):
                if not getattr(fact, provider_field):
                    errors.append(f"{fact.fact_id}: missing external provider field {provider_field}")
        if fact.trust_status == "trusted_by_real_external" and fact.is_simulated:
            errors.append(f"{fact.fact_id}: real external fact marked simulated")
        if fact.trust_status == "trusted_by_simulated_external" and not fact.is_simulated:
            errors.append(f"{fact.fact_id}: simulated external fact missing is_simulated")
        if not fact.sufficient_for_analysis:
            errors.append(f"{fact.fact_id}: trusted fact is not sufficient for analysis")
        for field_name in ("unit", "currency", "period", "source_pdf", "source_text"):
            if not getattr(fact, field_name):
                errors.append(f"{fact.fact_id}: missing {field_name}")
        if fact.value_normalized is None:
            errors.append(f"{fact.fact_id}: missing value_normalized")
        if _is_excluded_field_name(_normalize_text(fact.original_field_name)):
            errors.append(f"{fact.fact_id}: excluded header/note field entered trusted facts")
    return errors


def _build_summary(
    output_dir: Path,
    trusted_facts: list[TrustedCanonicalFinancialFact],
    needs_human_review: list[CanonicalNeedsHumanReviewItem],
    candidate_only: list[CanonicalCandidateOnlyItem],
    errors: list[str],
) -> CanonicalExtractionSummary:
    return CanonicalExtractionSummary(
        extraction_id="parse_lab_round3_canonical_financial_fact_extraction",
        output_dir=str(output_dir),
        canonical_field_count=len(CANONICAL_FIELD_DEFINITIONS),
        trusted_by_text_count=sum(1 for fact in trusted_facts if fact.trust_status == "trusted_by_text"),
        trusted_by_external_count=sum(
            1 for fact in trusted_facts if fact.trust_status in {"trusted_by_real_external", "trusted_by_simulated_external"}
        ),
        trusted_by_real_external_count=sum(1 for fact in trusted_facts if fact.trust_status == "trusted_by_real_external"),
        trusted_by_simulated_external_count=sum(
            1 for fact in trusted_facts if fact.trust_status == "trusted_by_simulated_external"
        ),
        trusted_canonical_fact_count=len(trusted_facts),
        production_consumable_count=sum(
            1
            for fact in trusted_facts
            if fact.trust_status in PRODUCTION_TRUSTED_STATUSES and fact.sufficient_for_analysis and not fact.is_simulated
        ),
        dev_test_consumable_count=sum(
            1 for fact in trusted_facts if fact.trust_status in DEV_TEST_TRUSTED_STATUSES and fact.sufficient_for_analysis
        ),
        needs_human_review_count=len(needs_human_review),
        candidate_only_count=len(candidate_only),
        excluded_note_header_or_time_bucket_count=sum(
            1 for item in candidate_only if item.candidate_only_reason == "excluded_note_header_or_time_bucket"
        ),
        noncanonical_candidate_count=sum(
            1 for item in candidate_only if item.candidate_only_reason == "noncanonical_field_candidate"
        ),
        source_pdf_distribution=dict(Counter(fact.source_pdf for fact in trusted_facts)),
        trusted_status_distribution=dict(Counter(fact.trust_status for fact in trusted_facts)),
        canonical_field_distribution=dict(Counter(fact.canonical_field for fact in trusted_facts)),
        analysis_consumption_policy="canonical_trusted_only",
        errors=errors,
    )


def _write_outputs(output_dir: Path, result: CanonicalExtractionResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    trusted_facts = [_model_dump(fact) for fact in result.trusted_canonical_facts]
    needs_human_review = [_model_dump(item) for item in result.needs_human_review]
    candidate_only = [_model_dump(item) for item in result.candidate_only]
    _write_json(output_dir / "canonical_field_mapping.json", {"items": [_model_dump(item) for item in result.canonical_fields]})
    _write_json(output_dir / "trusted_canonical_facts.json", {"items": trusted_facts, "count": len(trusted_facts)})
    _write_csv(output_dir / "trusted_canonical_facts.csv", trusted_facts, TRUSTED_FACT_CSV_FIELDS)
    _write_json(output_dir / "needs_human_review.json", {"items": needs_human_review, "count": len(needs_human_review)})
    _write_json(output_dir / "candidate_only.json", {"items": candidate_only, "count": len(candidate_only)})
    _write_json(output_dir / "canonical_extraction_summary.json", _model_dump(result.summary))


def _load_field_candidates(source_dir: Path) -> list[dict[str, Any]]:
    json_path = source_dir / "financialresearch_field_candidates.json"
    if not json_path.exists():
        raise FileNotFoundError(f"field candidates export not found: {json_path}")
    payload = _read_json(json_path, {"items": []})
    return list(payload.get("items") or [])


def _canonical_field_names() -> set[str]:
    return {definition.canonical_field for definition in CANONICAL_FIELD_DEFINITIONS}


def _is_excluded_field_name(normalized_field_name: str) -> bool:
    if any(token in normalized_field_name for token in EXCLUDED_FIELD_TOKENS):
        return True
    return bool(re.fullmatch(r"\d+\s*years?", normalized_field_name))


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", no_tags).strip().lower()


def _slug(text: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    return slug or "source"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
