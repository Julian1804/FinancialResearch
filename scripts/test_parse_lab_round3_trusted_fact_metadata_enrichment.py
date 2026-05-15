from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.trust_resolution_service import TRUSTED_STATUSES
from backend.app.modules.financial_report.services.trusted_fact_metadata_enrichment_service import (
    ENRICHED_TRUSTED_FACT_OUTPUT_DIR,
    enrich_parse_lab_round3_trusted_fact_metadata,
    summarize_enrichment_result,
)


def test_trusted_fact_metadata_enrichment() -> dict[str, object]:
    result = enrich_parse_lab_round3_trusted_fact_metadata()
    summary = summarize_enrichment_result(result)
    assert summary["input_trusted_fact_count"] == 82
    assert summary["candidate_input_count"] == 0
    assert summary["enriched_success_count"] > 6
    assert summary["period_enriched_count"] == 82
    assert summary["insufficient_evidence_count"] > 0
    assert "filename" in summary["enrichment_source_distribution"]
    assert not summary["errors"]

    for fact in result.enriched_facts:
        assert fact.trusted is True
        assert fact.candidate_only is False
        assert fact.trust_status in TRUSTED_STATUSES
        assert fact.value_original is not None
        assert fact.unit_original is not None
        assert fact.currency_original is not None
        assert fact.period_original is not None
        assert fact.metadata_status
        assert fact.provenance
        if fact.period_enriched:
            period_sources = [source for source in fact.enrichment_sources if source.get("field") == "period"]
            assert period_sources
            assert any(source.get("inference_source") == "filename" for source in period_sources)
            assert all("confidence" in source for source in period_sources)
            assert all(source.get("matched_text") for source in period_sources)
        for source in fact.enrichment_sources:
            assert source.get("inference_source")
            assert source.get("confidence") is not None
            if source.get("inference_source") == "evidence_text":
                assert source.get("matched_text")
            if source.get("inference_source") == "table_context_metadata":
                assert source.get("source_text")

    gap_report = result.gap_report
    assert gap_report.missing_period_count == 0
    assert gap_report.missing_currency_count > 0
    assert gap_report.missing_unit_count > 0
    assert gap_report.missing_value_enrichment_count > 0

    assert (ENRICHED_TRUSTED_FACT_OUTPUT_DIR / "enriched_trusted_facts.json").exists()
    assert (ENRICHED_TRUSTED_FACT_OUTPUT_DIR / "enriched_trusted_facts.csv").exists()
    assert (ENRICHED_TRUSTED_FACT_OUTPUT_DIR / "enrichment_summary.json").exists()
    assert (ENRICHED_TRUSTED_FACT_OUTPUT_DIR / "enrichment_gap_report.json").exists()
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
    summary = test_trusted_fact_metadata_enrichment()
    test_parse_lab_not_modified()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Parse Lab Round3 trusted fact metadata enrichment test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
