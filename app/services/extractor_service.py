from typing import Dict, List

from config.settings import SCHEMA_VERSION
from services.period_service import build_period_metadata
from services.research_utils import now_iso, truncate_text


def _extract_title_candidates(full_text: str, source_file: str) -> List[str]:
    candidates = []
    if source_file:
        candidates.append(source_file)
    lines = [line.strip() for line in (full_text or "").splitlines() if line.strip()]
    for line in lines[:20]:
        if len(line) <= 120:
            candidates.append(line)
    dedup, seen = [], set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            dedup.append(item)
    return dedup[:10]


def _find_section_snippet(full_text: str, keywords: List[str], max_chars: int = 1500) -> str:
    text = full_text or ""
    lower_text = text.lower()
    best_pos = -1
    for keyword in keywords:
        pos = lower_text.find(keyword.lower())
        if pos >= 0 and (best_pos == -1 or pos < best_pos):
            best_pos = pos
    if best_pos == -1:
        return ""
    return truncate_text(text[best_pos: best_pos + max_chars], max_chars)


def _build_key_sections(full_text: str) -> Dict[str, str]:
    return {
        "管理层讨论与分析片段": _find_section_snippet(full_text, ["management discussion", "management’s discussion", "管理层讨论", "管理层讨论与分析", "管理層討論", "管理層討論與分析", "业务回顾", "業務回顧", "经营回顾", "經營回顧"], 1800),
        "风险因素片段": _find_section_snippet(full_text, ["risk factors", "principal risks", "主要风险", "主要風險", "风险因素", "風險因素", "风险", "風險"], 1500),
        "财务摘要片段": _find_section_snippet(full_text, ["financial highlights", "financial summary", "results highlights", "财务摘要", "財務摘要", "财务概览", "財務概覽", "业绩摘要", "業績摘要", "财务亮点", "財務亮點"], 1500),
        "前瞻指引片段": _find_section_snippet(full_text, ["outlook", "guidance", "future prospects", "未来展望", "未來展望", "业务展望", "業務展望", "前景展望", "指引"], 1500),
    }


def build_extracted_output(parsed_data: dict) -> dict:
    company_name = parsed_data.get("company_name", "")
    source_file = parsed_data.get("source_file", "")
    full_text = parsed_data.get("full_text", "")
    pages = parsed_data.get("pages", [])
    page_count = parsed_data.get("page_count", 0)
    dominant_language = parsed_data.get("dominant_language", "")
    generated_at = now_iso()

    period_meta = build_period_metadata(source_file, full_text)
    key_sections = _build_key_sections(full_text)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "company_name": company_name,
        "source_file": source_file,
        "page_count": page_count,
        "dominant_language": dominant_language,
        "title_candidates": _extract_title_candidates(full_text, source_file),
        "key_sections": key_sections,
        "fiscal_year": period_meta.get("fiscal_year"),
        "report_type": period_meta.get("report_type", "UNKNOWN"),
        "period_key": period_meta.get("period_key", ""),
        "related_primary_period_key": period_meta.get("related_primary_period_key", ""),
        "document_type": period_meta.get("document_type", "other_disclosure"),
        "timeline_bucket": period_meta.get("timeline_bucket", "auxiliary"),
        "report_date": period_meta.get("report_date", ""),
        "material_timestamp": period_meta.get("material_timestamp", ""),
        "material_timestamp_precision": period_meta.get("material_timestamp_precision", "unknown"),
        "is_annual_final": period_meta.get("is_annual_final", False),
        "is_primary_financial_report": period_meta.get("is_primary_financial_report", False),
        "can_adjust_forecast": period_meta.get("can_adjust_forecast", False),
        "forecast_as_of_period": period_meta.get("forecast_as_of_period", ""),
        "forecast_target_period": period_meta.get("forecast_target_period", ""),
        "summary_preview": truncate_text(full_text, 2000),
        "pages_meta": [
            {
                "page_number": page.get("page_number", 0),
                "char_count": len(page.get("text", "") or page.get("page_text", "") or ""),
                "page_type": page.get("page_type", ""),
                "engine_used": page.get("engine", page.get("engine_used", "")),
                "ai_called": page.get("ai_called", False),
            }
            for page in pages
        ],
    }
