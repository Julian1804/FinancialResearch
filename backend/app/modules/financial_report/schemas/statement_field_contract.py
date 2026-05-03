from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StatementFieldCandidate(BaseModel):
    field_id: str
    document_id: str
    task_id: str
    table_id: str
    candidate_statement_type: str
    canonical_field_name: str
    raw_field_name: str = ""
    raw_value: str = ""
    normalized_value: float | None = None
    unit: str = "unknown"
    currency: str = "unknown"
    period_label: str = "unknown_period"
    source_pages: list[int] = Field(default_factory=list)
    source_row_index: int = 0
    source_col_index: int = 0
    table_group_id: str = ""
    confidence: float = 0.0
    mapping_reason: str = ""
    requires_review: bool = False


class StatementMappingResult(BaseModel):
    document_id: str
    task_id: str = ""
    pdf_name: str = ""
    extraction_mode: str = "blocked"
    fields: list[StatementFieldCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    discarded_candidates_count: int = 0
    discarded_candidate_examples: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class StatementMappingRule(BaseModel):
    statement_type: str
    canonical_field_name: str
    exact_aliases: list[str] = Field(default_factory=list)
    phrase_aliases: list[str] = Field(default_factory=list)
    weak_aliases: list[str] = Field(default_factory=list)
    value_type: str = "number"
    required: bool = False
    notes: str = ""
