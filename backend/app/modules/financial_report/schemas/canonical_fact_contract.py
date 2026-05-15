from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CanonicalFinancialFieldDefinition(BaseModel):
    canonical_field: str
    aliases: list[str] = Field(default_factory=list)
    category: str = ""
    amount_like: bool = True


class TrustedCanonicalFinancialFact(BaseModel):
    fact_id: str
    canonical_field: str
    original_field_name: str
    value: float
    value_normalized: float
    unit: str
    currency: str
    period: str
    fiscal_year: int
    fiscal_period_type: str
    source_pdf: str
    source_page: int = 0
    source_type: str
    source_text: str
    trust_status: str
    sufficient_for_analysis: bool = True
    extraction_method: str
    confidence: float = 0.0
    provenance: dict[str, Any] = Field(default_factory=dict)


class CanonicalNeedsHumanReviewItem(BaseModel):
    review_item_id: str
    canonical_field: str
    source_pdf: str
    period: str
    reason: str
    candidate_only: bool = True
    trusted: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)


class CanonicalCandidateOnlyItem(BaseModel):
    candidate_id: str
    canonical_field: str = ""
    original_field_name: str = ""
    value: Any = None
    source_pdf: str
    source_page: int
    source_type: str = ""
    evidence_text: str = ""
    candidate_only_reason: str
    trusted: bool = False
    candidate_only: bool = True
    provenance: dict[str, Any] = Field(default_factory=dict)


class CanonicalExtractionSummary(BaseModel):
    extraction_id: str
    output_dir: str
    canonical_field_count: int = 0
    trusted_by_text_count: int = 0
    trusted_by_external_count: int = 0
    trusted_canonical_fact_count: int = 0
    needs_human_review_count: int = 0
    candidate_only_count: int = 0
    excluded_note_header_or_time_bucket_count: int = 0
    noncanonical_candidate_count: int = 0
    source_pdf_distribution: dict[str, int] = Field(default_factory=dict)
    trusted_status_distribution: dict[str, int] = Field(default_factory=dict)
    canonical_field_distribution: dict[str, int] = Field(default_factory=dict)
    analysis_consumption_policy: str = "canonical_trusted_only"
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class CanonicalExtractionResult(BaseModel):
    summary: CanonicalExtractionSummary
    canonical_fields: list[CanonicalFinancialFieldDefinition] = Field(default_factory=list)
    trusted_canonical_facts: list[TrustedCanonicalFinancialFact] = Field(default_factory=list)
    needs_human_review: list[CanonicalNeedsHumanReviewItem] = Field(default_factory=list)
    candidate_only: list[CanonicalCandidateOnlyItem] = Field(default_factory=list)
