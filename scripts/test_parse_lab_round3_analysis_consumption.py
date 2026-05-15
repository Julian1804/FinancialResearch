from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.trusted_fact_analysis_consumption_service import (
    ANALYSIS_CONSUMPTION_OUTPUT_DIR,
    build_parse_lab_round3_trusted_analysis_consumption,
    summarize_analysis_consumption,
)
from backend.app.modules.financial_report.services.trust_resolution_service import TRUSTED_STATUSES


def test_trusted_analysis_consumption() -> dict[str, object]:
    result = build_parse_lab_round3_trusted_analysis_consumption()
    digest = summarize_analysis_consumption(result)
    assert digest["trusted_fact_count"] == 82
    assert digest["field_group_count"] > 0
    assert digest["trust_status_distribution"] == {"trusted_by_text": 80, "trusted_by_external": 2}
    assert digest["insufficient_trusted_evidence"]

    for fact in result.consumption_payload:
        assert fact.trusted is True
        assert fact.candidate_only is False
        assert fact.trust_status in TRUSTED_STATUSES
        assert fact.trust_status not in {"validated_candidate", "candidate_only", "needs_human_review"}
        assert fact.provenance

    for group in result.grouped_summary:
        assert group.source_pdf
        assert group.source_page > 0
        assert group.field_name
        assert group.trust_status in TRUSTED_STATUSES
        assert group.fact_count == len(group.values)
        assert group.provenance
        assert all(item["trust_status"] in TRUSTED_STATUSES for item in group.provenance)

    assert (ANALYSIS_CONSUMPTION_OUTPUT_DIR / "trusted_facts_consumption_payload.json").exists()
    assert (ANALYSIS_CONSUMPTION_OUTPUT_DIR / "trusted_facts_grouped_summary.json").exists()
    assert (ANALYSIS_CONSUMPTION_OUTPUT_DIR / "trusted_facts_digest.json").exists()
    return digest


def test_parse_lab_not_modified() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    digest = test_trusted_analysis_consumption()
    test_parse_lab_not_modified()
    print(json.dumps(digest, ensure_ascii=False, indent=2))
    print("Parse Lab Round3 trusted analysis consumption test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
