from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExtractedFinancialField(BaseModel):
    field_id: str
    canonical_field_name: str
    statement_type: str
    value: str = ""
    normalized_value: float | None = None
    unit: str = "unknown"
    currency: str = "unknown"
    period_label: str = "unknown_period"
    source_pages: list[int] = Field(default_factory=list)
    source_table_id: str = ""
    source_table_group_id: str = ""
    confidence: float = 0.0
    requires_review: bool = False
    extraction_reason: str = ""


class ExtractedFinancialStatement(BaseModel):
    statement_type: str
    fields: list[ExtractedFinancialField] = Field(default_factory=list)
    periods_detected: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    quality_flags: list[Any] = Field(default_factory=list)
    requires_review: bool = False


class MinimalFinancialExtractionResult(BaseModel):
    document_id: str
    task_id: str = ""
    pdf_name: str = ""
    extraction_mode: str = "blocked"
    statements: list[ExtractedFinancialStatement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
