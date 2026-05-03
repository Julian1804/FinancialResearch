from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ParseQualityLevel = Literal["pass", "pass_with_warnings", "needs_review", "failed"]


class ParseTaskRecord(BaseModel):
    task_id: str
    pdf_path: str
    pdf_name: str = ""
    status: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    output_dir: str = ""
    error_tail: str = ""


class ParseResultManifest(BaseModel):
    task_id: str
    output_dir: str
    summary_path: str
    pages_jsonl_path: str
    merged_md_path: str
    tables_json_path: str
    merged_tables_json_path: str
    quality_flags_path: str
    cross_page_candidates_path: str


class ParseQualityAssessment(BaseModel):
    parse_quality_level: ParseQualityLevel
    parse_quality_reasons: list[str] = Field(default_factory=list)
    failed_pages_count: int = 0
    empty_pages_count: int = 0
    total_pages: int = 0
    heavy_parser_ratio: float = 0.0
    ocr_ratio: float = 0.0
    visual_table_route_pages_count: int = 0
    cross_page_table_candidate_count: int = 0
    merged_table_count: int = 0


class ParsedDocumentRegistryEntry(BaseModel):
    document_id: str
    pdf_path: str
    pdf_name: str
    parse_task_id: str
    parse_result_manifest: ParseResultManifest
    parse_quality_assessment: ParseQualityAssessment
    registered_at: datetime = Field(default_factory=datetime.utcnow)
