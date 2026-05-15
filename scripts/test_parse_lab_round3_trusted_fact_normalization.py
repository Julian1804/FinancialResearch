from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.trust_resolution_service import TRUSTED_STATUSES
from backend.app.modules.financial_report.services.trusted_fact_normalization_service import (
    NORMALIZED_TRUSTED_FACT_OUTPUT_DIR,
    normalize_parse_lab_round3_trusted_facts,
    summarize_normalization_result,
)


def test_trusted_fact_normalization() -> dict[str, object]:
    result = normalize_parse_lab_round3_trusted_facts()
    summary = summarize_normalization_result(result)
    assert summary["input_trusted_fact_count"] == 82
    assert summary["candidate_input_count"] == 0
    assert summary["normalized_success_count"] > 0
    assert summary["insufficient_evidence_count"] > 0
    assert summary["normalized_success_count"] + summary["insufficient_evidence_count"] == 82
    assert not summary["errors"]

    for fact in result.normalized_facts:
        assert fact.trusted is True
        assert fact.candidate_only is False
        assert fact.trust_status in TRUSTED_STATUSES
        assert fact.value_original is not None
        assert fact.unit_original is not None
        assert fact.currency_original is not None
        assert fact.period_original is not None
        assert fact.period_normalized or fact.normalization_status == "insufficient_evidence"
        assert fact.normalization_status in {"normalized", "insufficient_evidence"}
        assert fact.provenance

    for fact in result.normalized_facts:
        if fact.normalization_status == "normalized":
            assert fact.period_normalized
            assert fact.fiscal_year
            assert fact.fiscal_period_type
            assert fact.currency_normalized
            assert fact.unit_normalized
            assert fact.value_normalized is not None

    gap_report = result.gap_report
    assert gap_report.missing_currency_count > 0
    assert gap_report.missing_unit_count > 0
    assert gap_report.missing_currency_count == len(gap_report.missing_currency_fact_ids)
    assert gap_report.missing_unit_count == len(gap_report.missing_unit_fact_ids)

    assert (NORMALIZED_TRUSTED_FACT_OUTPUT_DIR / "normalized_trusted_facts.json").exists()
    assert (NORMALIZED_TRUSTED_FACT_OUTPUT_DIR / "normalized_trusted_facts.csv").exists()
    assert (NORMALIZED_TRUSTED_FACT_OUTPUT_DIR / "normalization_summary.json").exists()
    assert (NORMALIZED_TRUSTED_FACT_OUTPUT_DIR / "normalization_gap_report.json").exists()
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
    summary = test_trusted_fact_normalization()
    test_parse_lab_not_modified()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Parse Lab Round3 trusted fact normalization test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
