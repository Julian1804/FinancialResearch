from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.trust_resolution_service import TRUSTED_STATUSES
from backend.app.modules.financial_report.services.trusted_fact_quality_audit_service import (
    TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR,
    audit_parse_lab_round3_trusted_fact_quality,
    load_revised_trusted_facts_for_analysis,
    summarize_quality_audit_result,
)


def test_trusted_fact_quality_audit() -> dict[str, object]:
    result = audit_parse_lab_round3_trusted_fact_quality()
    summary = summarize_quality_audit_result(result)
    assert summary["original_trusted_count"] == 82
    assert summary["revised_trusted_count"] < summary["original_trusted_count"]
    assert summary["downgraded_count"] == summary["original_trusted_count"] - summary["revised_trusted_count"]
    assert summary["note_or_year_excluded"] is True
    assert summary["candidate_retained"] is True
    assert "field_name_is_note_header_or_time_bucket" in summary["downgrade_reason_distribution"]
    assert "amount_missing_currency_unit_or_value_normalized" in summary["downgrade_reason_distribution"]
    assert not summary["errors"]

    revised = load_revised_trusted_facts_for_analysis()
    assert len(revised) == summary["revised_trusted_count"]
    for fact in revised:
        normalized_name = fact.field_name.lower()
        assert "note" not in normalized_name
        assert "1 year" not in normalized_name
        assert "years" not in normalized_name
        assert "附註" not in fact.field_name
        assert "附注" not in fact.field_name
        assert fact.trusted is True
        assert fact.candidate_only is False
        assert fact.trust_status in TRUSTED_STATUSES
        assert fact.currency
        assert fact.unit
        assert fact.period

    downgraded_ids = {fact.fact_id for fact in result.downgraded_facts}
    assert "parse_lab_round3_resolved_0036" in downgraded_ids
    assert "parse_lab_round3_resolved_0062" in downgraded_ids
    assert result.downgraded_facts

    assert (TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR / "trusted_fact_quality_audit.json").exists()
    assert (TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR / "trusted_fact_quality_audit.csv").exists()
    assert (TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR / "downgraded_facts.json").exists()
    assert (TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR / "revised_trusted_facts.json").exists()
    assert (TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR / "revised_analysis_consumption_trusted_facts.json").exists()
    assert (TRUSTED_FACT_QUALITY_AUDIT_OUTPUT_DIR / "trust_gate_refinement_summary.json").exists()
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
    summary = test_trusted_fact_quality_audit()
    test_parse_lab_not_modified()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Parse Lab Round3 trusted fact quality audit test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
