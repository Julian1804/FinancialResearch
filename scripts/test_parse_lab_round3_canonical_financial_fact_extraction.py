from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.canonical_financial_fact_extraction_service import (
    CANONICAL_EXTRACTION_OUTPUT_DIR,
    canonical_field_for_name,
    extract_parse_lab_round3_canonical_financial_facts,
    load_trusted_canonical_facts_for_analysis,
    summarize_canonical_extraction_result,
)


def test_canonical_financial_fact_extraction() -> dict[str, object]:
    result = extract_parse_lab_round3_canonical_financial_facts()
    summary = summarize_canonical_extraction_result(result)
    assert summary["canonical_field_count"] == 12
    assert summary["trusted_canonical_fact_count"] > 0
    assert summary["trusted_by_text_count"] > 0
    assert summary["trusted_by_external_count"] > 0
    assert summary["candidate_only_count"] > 0
    assert summary["needs_human_review_count"] > 0
    assert summary["excluded_note_header_or_time_bucket_count"] > 0
    assert not summary["errors"]

    trusted = load_trusted_canonical_facts_for_analysis()
    assert len(trusted) == summary["trusted_canonical_fact_count"]
    canonical_fields = {field.canonical_field for field in result.canonical_fields}
    for fact in trusted:
        assert fact.canonical_field in canonical_fields
        assert fact.trust_status in {"trusted_by_text", "trusted_by_external"}
        assert fact.sufficient_for_analysis is True
        assert fact.value_normalized is not None
        assert fact.unit
        assert fact.currency
        assert fact.period
        assert fact.source_pdf
        assert fact.source_text
        original = fact.original_field_name.lower()
        assert "note" not in original
        assert "1 year" not in original
        assert "years" not in original
        assert "附註" not in fact.original_field_name
        assert "附注" not in fact.original_field_name

    assert canonical_field_for_name("Note<br>附註") == ""
    assert canonical_field_for_name("1 year") == ""
    assert canonical_field_for_name("table header") == ""
    assert canonical_field_for_name("Relevant Participant") == ""
    assert canonical_field_for_name("营业收入") == "revenue"
    assert canonical_field_for_name("profit for the period") == "net_profit"
    assert canonical_field_for_name("归母净利润") == "net_profit_attributable_to_parent"
    assert canonical_field_for_name("总资产") == "total_assets"
    assert canonical_field_for_name("负债合计") == "total_liabilities"

    for item in result.candidate_only:
        assert item.trusted is False
        assert item.candidate_only is True

    assert (CANONICAL_EXTRACTION_OUTPUT_DIR / "canonical_field_mapping.json").exists()
    assert (CANONICAL_EXTRACTION_OUTPUT_DIR / "trusted_canonical_facts.json").exists()
    assert (CANONICAL_EXTRACTION_OUTPUT_DIR / "trusted_canonical_facts.csv").exists()
    assert (CANONICAL_EXTRACTION_OUTPUT_DIR / "needs_human_review.json").exists()
    assert (CANONICAL_EXTRACTION_OUTPUT_DIR / "candidate_only.json").exists()
    assert (CANONICAL_EXTRACTION_OUTPUT_DIR / "canonical_extraction_summary.json").exists()
    return summary


def test_parse_lab_not_modified() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    summary = test_canonical_financial_fact_extraction()
    test_parse_lab_not_modified()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Parse Lab Round3 canonical financial fact extraction test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
