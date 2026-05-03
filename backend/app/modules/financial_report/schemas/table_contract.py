from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TableSourceType = Literal[
    "page_table",
    "merged_cross_page_table",
    "visual_table",
    "parser_validation_table",
]

CandidateStatementType = Literal[
    "balance_sheet",
    "income_statement",
    "cash_flow_statement",
    "shareholder_table",
    "segment_revenue_table",
    "unknown",
]


class CanonicalCell(BaseModel):
    row_index: int
    col_index: int
    text: str = ""
    normalized_text: str = ""
    is_header: bool = False
    row_span: int = 1
    col_span: int = 1
    confidence: float = 1.0


class CanonicalTableSource(BaseModel):
    source_file: str = ""
    source_pages: list[int] = Field(default_factory=list)
    parser_source: str = ""
    table_group_id: str = ""
    source_type: TableSourceType = "page_table"


class CanonicalTableQuality(BaseModel):
    has_header: bool = False
    row_count: int = 0
    col_count: int = 0
    empty_cell_ratio: float = 0.0
    numeric_cell_ratio: float = 0.0
    continuation_confidence: float = 0.0
    table_intent_score: float = 0.0
    quality_flags: list[Any] = Field(default_factory=list)


class CanonicalTable(BaseModel):
    table_id: str
    title: str = ""
    source: CanonicalTableSource
    quality: CanonicalTableQuality
    cells: list[CanonicalCell] = Field(default_factory=list)
    raw_text: str = ""
    raw_markdown: str = ""
    candidate_statement_type: CandidateStatementType = "unknown"


class TableNormalizationResult(BaseModel):
    document_id: str = ""
    task_id: str = ""
    pdf_name: str = ""
    tables: list[CanonicalTable] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
