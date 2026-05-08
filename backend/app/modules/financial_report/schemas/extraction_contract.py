from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ExtractionMode = Literal["blocked", "eligible", "dry_run_override"]


class ExtractionEligibilityResult(BaseModel):
    document_id: str
    eligible_for_extraction: bool = False
    reason: str = ""
    parse_quality_level: str = ""
    review_decision: str = ""
    required_files_present: bool = False


class ExtractedTableCandidate(BaseModel):
    candidate_id: str
    document_id: str
    task_id: str
    table_id: str
    candidate_statement_type: str
    source_pages: list[int] = Field(default_factory=list)
    source_type: str = ""
    table_group_id: str = ""
    title: str = ""
    row_count: int = 0
    col_count: int = 0
    numeric_cell_ratio: float = 0.0
    confidence: float = 0.0
    extraction_notes: list[str] = Field(default_factory=list)
    requires_review: bool = False
    quality_flags: list[Any] = Field(default_factory=list)


class FinancialExtractionCandidateSet(BaseModel):
    document_id: str
    task_id: str = ""
    pdf_name: str = ""
    eligible_for_extraction: bool = False
    extraction_mode: ExtractionMode = "blocked"
    candidates: list[ExtractedTableCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
