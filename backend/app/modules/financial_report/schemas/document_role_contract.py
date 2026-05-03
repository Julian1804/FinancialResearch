from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DocumentRole = Literal["primary_financial_report", "auxiliary_material", "unknown"]
ReportType = Literal[
    "annual_report",
    "semi_annual_report",
    "quarterly_report",
    "q1_report",
    "q3_report",
    "earnings_announcement",
    "earnings_release",
    "earnings_presentation",
    "conference_call_transcript",
    "investor_presentation",
    "other_announcement",
    "unknown",
]
ExpectedExtractionStrategy = Literal[
    "three_statement_extraction",
    "auxiliary_performance_extraction",
    "transcript_or_commentary_extraction",
    "unknown",
]


class DocumentRoleAssessment(BaseModel):
    document_id: str = ""
    pdf_name: str = ""
    document_role: DocumentRole = "unknown"
    report_type: ReportType = "unknown"
    expects_three_statements: bool = False
    expected_extraction_strategy: ExpectedExtractionStrategy = "unknown"
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    requires_review: bool = True
