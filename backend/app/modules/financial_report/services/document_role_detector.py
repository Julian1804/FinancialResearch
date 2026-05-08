from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.document_role_contract import (
    DocumentRoleAssessment,
)
from backend.app.modules.financial_report.services.parsed_document_registry import (
    load_registry_entries,
)


PRIMARY_PATTERNS = [
    ("annual_report", ["年报", "年度报告", "annualreport", "annual report"]),
    ("semi_annual_report", ["半年报", "半年度报告", "中期报告", "interimreport", "interim report"]),
    ("q1_report", ["一季报", "第一季度报告", "1季度报告", "q1report", "q1 report"]),
    ("q3_report", ["三季报", "第三季度报告", "3季度报告", "q3report", "q3 report"]),
    ("quarterly_report", ["季报", "季度报告", "quarterlyreport", "quarterly report"]),
]

AUXILIARY_PATTERNS = [
    ("conference_call_transcript", ["电话会议", "conferencecall", "conference call", "transcript", "纪要"]),
    ("earnings_presentation", ["业绩简报", "presentation", "业绩演示"]),
    ("investor_presentation", ["投资者演示", "investorpresentation", "investor presentation"]),
    ("earnings_release", ["业绩新闻稿", "业绩发布", "earningsrelease", "earnings release"]),
    ("earnings_announcement", ["业绩公告", "resultsannouncement", "results announcement"]),
    ("other_announcement", ["公告", "announcement"]),
]


def detect_document_role_from_filename(pdf_name: str) -> DocumentRoleAssessment:
    return _detect_from_text(pdf_name, pdf_name=pdf_name, document_id="", source="filename")


def detect_document_role_from_summary_or_pages(
    summary: dict[str, Any],
    pages_sample: list[dict[str, Any]],
) -> DocumentRoleAssessment:
    text_parts = [json.dumps(summary, ensure_ascii=False)]
    for page in pages_sample:
        text_parts.append(str(page.get("final_text") or page.get("primary_text") or ""))
    return _detect_from_text("\n".join(text_parts), source="summary_or_pages")


def assess_document_role(document_id: str) -> DocumentRoleAssessment:
    entry = _find_registry_entry(document_id)
    if not entry:
        return DocumentRoleAssessment(
            document_id=document_id,
            document_role="unknown",
            report_type="unknown",
            expects_three_statements=False,
            expected_extraction_strategy="unknown",
            confidence=0.0,
            evidence=["registry_entry_not_found"],
            requires_review=True,
        )

    filename_assessment = detect_document_role_from_filename(entry.get("pdf_name", ""))
    if filename_assessment.document_role != "unknown":
        filename_assessment.document_id = document_id
        return filename_assessment

    summary = _load_json(entry.get("summary_path", ""))
    pages = _load_pages_sample(entry.get("pages_jsonl_path", ""))
    content_assessment = detect_document_role_from_summary_or_pages(summary, pages)
    content_assessment.document_id = document_id
    content_assessment.pdf_name = entry.get("pdf_name", "")
    return content_assessment


def _detect_from_text(text: str, pdf_name: str = "", document_id: str = "", source: str = "") -> DocumentRoleAssessment:
    normalized = _normalize(text)
    for report_type, patterns in AUXILIARY_PATTERNS:
        for pattern in patterns:
            if _normalize(pattern) in normalized:
                strategy = "transcript_or_commentary_extraction" if report_type == "conference_call_transcript" else "auxiliary_performance_extraction"
                return DocumentRoleAssessment(
                    document_id=document_id,
                    pdf_name=pdf_name,
                    document_role="auxiliary_material",
                    report_type=report_type,
                    expects_three_statements=False,
                    expected_extraction_strategy=strategy,
                    confidence=0.86,
                    evidence=[f"{source}:{pattern}"],
                    requires_review=False,
                )

    for report_type, patterns in PRIMARY_PATTERNS:
        for pattern in patterns:
            if _normalize(pattern) in normalized:
                return DocumentRoleAssessment(
                    document_id=document_id,
                    pdf_name=pdf_name,
                    document_role="primary_financial_report",
                    report_type=report_type,
                    expects_three_statements=True,
                    expected_extraction_strategy="three_statement_extraction",
                    confidence=0.88,
                    evidence=[f"{source}:{pattern}"],
                    requires_review=False,
                )

    return DocumentRoleAssessment(
        document_id=document_id,
        pdf_name=pdf_name,
        document_role="unknown",
        report_type="unknown",
        expects_three_statements=False,
        expected_extraction_strategy="unknown",
        confidence=0.0,
        evidence=[f"{source}:no_role_pattern_matched"],
        requires_review=True,
    )


def _find_registry_entry(document_id: str) -> dict[str, Any] | None:
    for entry in load_registry_entries():
        if entry.get("document_id") == document_id:
            return entry
    return None


def _load_json(path: str) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _load_pages_sample(path: str, limit: int = 3) -> list[dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    pages: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                pages.append(json.loads(line))
            if len(pages) >= limit:
                break
    return pages


def _normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())
