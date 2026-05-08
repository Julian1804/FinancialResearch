from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.parse_contract import ParseQualityAssessment


HIGH_OCR_RATIO_THRESHOLD = 0.40
HIGH_HEAVY_RATIO_THRESHOLD = 0.60
FAILED_PAGE_RATIO_THRESHOLD = 0.01


def _count_items(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _raise_level(current: str, candidate: str) -> str:
    order = {"pass": 0, "pass_with_warnings": 1, "needs_review": 2, "failed": 3}
    return candidate if order[candidate] > order[current] else current


def assess_parse_quality(
    summary: dict[str, Any],
    quality_flags: dict[str, Any] | None,
    pages_count: int | None,
    merged_md_path: str | None = None,
) -> ParseQualityAssessment:
    quality_flags = quality_flags or {}
    total_pages = int(summary.get("total_pages") or 0)
    failed_pages_count = _count_items(summary.get("failed_pages"))
    empty_pages_count = _count_items(summary.get("empty_pages"))
    heavy_parser_ratio = float(summary.get("heavy_parser_ratio") or 0.0)
    ocr_ratio = float(summary.get("ocr_ratio") or 0.0)
    visual_pages_count = _count_items(summary.get("visual_table_route_pages"))
    cross_page_count = int(summary.get("cross_page_table_candidate_count") or 0)
    merged_table_count = int(summary.get("merged_table_count") or 0)
    flag_counts = quality_flags.get("flag_counts") if isinstance(quality_flags, dict) else {}
    flag_counts = flag_counts if isinstance(flag_counts, dict) else {}

    reasons: list[str] = []
    level = "pass"

    if not summary:
        reasons.append("summary is missing")
        level = "failed"
    if total_pages <= 0:
        reasons.append("summary.total_pages is missing or zero")
        level = "failed"
    if pages_count is not None and total_pages and pages_count != total_pages:
        reasons.append(f"pages.jsonl row count {pages_count} does not equal total_pages {total_pages}")
        level = "failed"
    if pages_count is None:
        reasons.append("pages.jsonl row count is unavailable")
        level = "failed"
    if merged_md_path:
        merged_path = Path(merged_md_path)
        if not merged_path.exists():
            reasons.append("merged.md is missing")
            level = "failed"
        elif not merged_path.read_text(encoding="utf-8", errors="ignore").strip():
            reasons.append("merged.md is empty")
            level = "failed"

    if failed_pages_count:
        failed_ratio = failed_pages_count / max(total_pages, 1)
        reasons.append(f"failed_pages_count={failed_pages_count}")
        level = _raise_level(level, "needs_review" if failed_ratio > FAILED_PAGE_RATIO_THRESHOLD else "pass_with_warnings")
    if empty_pages_count:
        reasons.append(f"empty_pages_count={empty_pages_count}")
        level = _raise_level(level, "needs_review")
    if visual_pages_count:
        reasons.append(f"visual_table_route_pages_count={visual_pages_count}")
        level = _raise_level(level, "pass_with_warnings")
    if cross_page_count:
        reasons.append(f"cross_page_table_candidate_count={cross_page_count}")
        level = _raise_level(level, "pass_with_warnings")
    if ocr_ratio >= HIGH_OCR_RATIO_THRESHOLD:
        reasons.append(f"ocr_ratio={ocr_ratio:.4f} is high")
        level = _raise_level(level, "needs_review")
    if heavy_parser_ratio >= HIGH_HEAVY_RATIO_THRESHOLD:
        reasons.append(f"heavy_parser_ratio={heavy_parser_ratio:.4f} is high")
        level = _raise_level(level, "needs_review")
    if any(count for count in flag_counts.values() if isinstance(count, int) and count > 0):
        reasons.append("quality_flags contains flagged pages")
        level = _raise_level(level, "pass_with_warnings")

    if not reasons and level == "pass":
        reasons.append("parse outputs passed baseline quality checks")

    return ParseQualityAssessment(
        parse_quality_level=level,  # type: ignore[arg-type]
        parse_quality_reasons=reasons,
        failed_pages_count=failed_pages_count,
        empty_pages_count=empty_pages_count,
        total_pages=total_pages,
        heavy_parser_ratio=heavy_parser_ratio,
        ocr_ratio=ocr_ratio,
        visual_table_route_pages_count=visual_pages_count,
        cross_page_table_candidate_count=cross_page_count,
        merged_table_count=merged_table_count,
    )
