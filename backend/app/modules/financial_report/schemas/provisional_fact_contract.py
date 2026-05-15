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

