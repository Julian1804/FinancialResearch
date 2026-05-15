from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProvisionalFinancialFact(BaseModel):
    fact_id: str
    field_name: str
    value: Any = None
    unit: str = ""
    currency: str = ""
    period: str = ""
    source_pdf: str
    source_page: int
    source_type: str
    evidence_text: str
    table_id: str = ""
    engine_name: str = ""
    validation_status: str
    confidence: float = 0.0
    candidate_only_reason: str
    candidate_only: bool = True
    trusted: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)


class CandidateOnlyReviewQueueItem(BaseModel):
    review_item_id: str
    field_name: str = ""
    value: Any = None
    source_pdf: str
    source_page: int
    source_type: str = "text"
    evidence_text: str = ""
    table_id: str = ""
    engine_name: str = ""
    validation_status: str
    candidate_only_reason: str
    recommended_next_action: str = "needs_human_review"
    candidate_only: bool = True
    trusted: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)


class CandidateOnlyIngestionSummary(BaseModel):
    ingestion_id: str
    source_dir: str
    output_dir: str
    provisional_fact_count: int = 0
    review_queue_count: int = 0
    trusted_fact_count: int = 0
    validation_status_distribution: dict[str, int] = Field(default_factory=dict)
    review_queue_status_distribution: dict[str, int] = Field(default_factory=dict)
    source_pdf_distribution: dict[str, int] = Field(default_factory=dict)
    source_type_distribution: dict[str, int] = Field(default_factory=dict)
    candidate_only: bool = True
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class CandidateOnlyIngestionResult(BaseModel):
    summary: CandidateOnlyIngestionSummary
    provisional_facts: list[ProvisionalFinancialFact] = Field(default_factory=list)
    review_queue: list[CandidateOnlyReviewQueueItem] = Field(default_factory=list)


class ResolvedFinancialFact(BaseModel):
    fact_id: str
    original_fact_id: str
    field_name: str
    value: Any = None
    unit: str = ""
    currency: str = ""
    period: str = ""
    source_pdf: str
    source_page: int
    source_type: str
    evidence_text: str
    table_id: str = ""
    engine_name: str = ""
    validation_status: str
    confidence: float = 0.0
    trust_status: str
    trust_reason: str
    candidate_only_reason: str = ""
    is_core_field: bool = False
    external_provider: str = ""
    trusted: bool = False
    candidate_only: bool = True
    provenance: dict[str, Any] = Field(default_factory=dict)


class TrustResolutionSummary(BaseModel):
    resolution_id: str
    source_dir: str
    output_dir: str
    total_input_fact_count: int = 0
    trusted_fact_count: int = 0
    trusted_by_text_count: int = 0
    trusted_by_external_count: int = 0
    validated_candidate_count: int = 0
    candidate_only_count: int = 0
    needs_human_review_count: int = 0
    rejected_count: int = 0
    core_field_count: int = 0
    non_core_field_count: int = 0
    trust_status_distribution: dict[str, int] = Field(default_factory=dict)
    validation_status_distribution: dict[str, int] = Field(default_factory=dict)
    source_pdf_distribution: dict[str, int] = Field(default_factory=dict)
    analysis_consumption_policy: str = "trusted_only"
    core_field_rule: str = ""
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class TrustResolutionResult(BaseModel):
    summary: TrustResolutionSummary
    trusted_facts: list[ResolvedFinancialFact] = Field(default_factory=list)
    validated_candidates: list[ResolvedFinancialFact] = Field(default_factory=list)
    candidate_only_facts: list[ResolvedFinancialFact] = Field(default_factory=list)
    needs_human_review: list[ResolvedFinancialFact] = Field(default_factory=list)
    rejected_facts: list[ResolvedFinancialFact] = Field(default_factory=list)


class TrustedFactGroupSummary(BaseModel):
    group_id: str
    source_pdf: str
    source_page: int
    field_name: str
    period: str = ""
    unit: str = ""
    trust_status: str
    fact_count: int = 0
    values: list[Any] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)


class TrustedFactsAnalysisDigest(BaseModel):
    digest_id: str
    trusted_fact_count: int = 0
    source_pdf_count: int = 0
    source_page_count: int = 0
    field_group_count: int = 0
    trust_status_distribution: dict[str, int] = Field(default_factory=dict)
    source_pdf_distribution: dict[str, int] = Field(default_factory=dict)
    insufficient_trusted_evidence: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class TrustedFactsAnalysisConsumptionResult(BaseModel):
    digest: TrustedFactsAnalysisDigest
    grouped_summary: list[TrustedFactGroupSummary] = Field(default_factory=list)
    consumption_payload: list[ResolvedFinancialFact] = Field(default_factory=list)


class NormalizedTrustedFinancialFact(BaseModel):
    normalized_fact_id: str
    fact_id: str
    original_fact_id: str
    field_name: str
    value_original: Any = None
    unit_original: str = ""
    currency_original: str = ""
    period_original: str = ""
    source_pdf: str
    source_page: int
    source_type: str
    evidence_text: str
    table_id: str = ""
    engine_name: str = ""
    validation_status: str
    confidence: float = 0.0
    trust_status: str
    trusted: bool = True
    candidate_only: bool = False
    period_normalized: str = ""
    fiscal_year: int | None = None
    fiscal_period_type: str = ""
    currency_normalized: str = ""
    unit_normalized: str = ""
    value_normalized: float | None = None
    normalization_status: str = "insufficient_evidence"
    normalization_warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class TrustedFactNormalizationSummary(BaseModel):
    normalization_id: str
    output_dir: str
    input_trusted_fact_count: int = 0
    normalized_success_count: int = 0
    insufficient_evidence_count: int = 0
    period_normalized_count: int = 0
    currency_normalized_count: int = 0
    unit_normalized_count: int = 0
    value_normalized_count: int = 0
    trust_status_distribution: dict[str, int] = Field(default_factory=dict)
    normalization_status_distribution: dict[str, int] = Field(default_factory=dict)
    source_pdf_distribution: dict[str, int] = Field(default_factory=dict)
    candidate_input_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class TrustedFactNormalizationGapReport(BaseModel):
    missing_period_count: int = 0
    missing_currency_count: int = 0
    missing_unit_count: int = 0
    missing_value_normalization_count: int = 0
    missing_period_fact_ids: list[str] = Field(default_factory=list)
    missing_currency_fact_ids: list[str] = Field(default_factory=list)
    missing_unit_fact_ids: list[str] = Field(default_factory=list)
    missing_value_normalization_fact_ids: list[str] = Field(default_factory=list)


class TrustedFactNormalizationResult(BaseModel):
    summary: TrustedFactNormalizationSummary
    gap_report: TrustedFactNormalizationGapReport
    normalized_facts: list[NormalizedTrustedFinancialFact] = Field(default_factory=list)


class EnrichedTrustedFinancialFact(BaseModel):
    enriched_fact_id: str
    fact_id: str
    original_fact_id: str
    field_name: str
    value_original: Any = None
    unit_original: str = ""
    currency_original: str = ""
    period_original: str = ""
    source_pdf: str
    source_page: int
    source_type: str
    evidence_text: str
    table_id: str = ""
    engine_name: str = ""
    validation_status: str
    confidence: float = 0.0
    trust_status: str
    trusted: bool = True
    candidate_only: bool = False
    period_enriched: str = ""
    fiscal_year: int | None = None
    fiscal_period_type: str = ""
    currency_enriched: str = ""
    unit_enriched: str = ""
    value_enriched: float | None = None
    enrichment_status: str = "insufficient_evidence"
    metadata_status: dict[str, str] = Field(default_factory=dict)
    enrichment_sources: list[dict[str, Any]] = Field(default_factory=list)
    metadata_gaps: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class TrustedFactEnrichmentSummary(BaseModel):
    enrichment_id: str
    output_dir: str
    input_trusted_fact_count: int = 0
    enriched_success_count: int = 0
    fully_enriched_count: int = 0
    partially_enriched_count: int = 0
    insufficient_evidence_count: int = 0
    period_enriched_count: int = 0
    currency_enriched_count: int = 0
    unit_enriched_count: int = 0
    value_enriched_count: int = 0
    candidate_input_count: int = 0
    enrichment_status_distribution: dict[str, int] = Field(default_factory=dict)
    trust_status_distribution: dict[str, int] = Field(default_factory=dict)
    source_pdf_distribution: dict[str, int] = Field(default_factory=dict)
    enrichment_source_distribution: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class TrustedFactEnrichmentGapReport(BaseModel):
    missing_period_count: int = 0
    missing_currency_count: int = 0
    missing_unit_count: int = 0
    missing_value_enrichment_count: int = 0
    missing_period_fact_ids: list[str] = Field(default_factory=list)
    missing_currency_fact_ids: list[str] = Field(default_factory=list)
    missing_unit_fact_ids: list[str] = Field(default_factory=list)
    missing_value_enrichment_fact_ids: list[str] = Field(default_factory=list)


class TrustedFactEnrichmentResult(BaseModel):
    summary: TrustedFactEnrichmentSummary
    gap_report: TrustedFactEnrichmentGapReport
    enriched_facts: list[EnrichedTrustedFinancialFact] = Field(default_factory=list)
