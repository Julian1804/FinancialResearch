from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.trust_resolution_service import (
    TRUSTED_STATUSES,
    TRUST_RESOLUTION_OUTPUT_DIR,
    is_core_financial_field,
    load_trusted_facts_for_analysis,
    resolve_parse_lab_round3_trust,
    summarize_trust_resolution,
)


REQUIRED_PROVENANCE_FIELDS = {
    "field_name",
    "value",
    "unit",
    "currency",
    "period",
    "source_pdf",
    "source_page",
    "source_type",
    "evidence_text",
    "table_id",
    "engine_name",
    "validation_status",
    "confidence",
}


def test_trust_resolution() -> dict[str, object]:
    result = resolve_parse_lab_round3_trust()
    summary = summarize_trust_resolution(result)
    assert summary["total_input_fact_count"] == 273
    assert summary["trusted_fact_count"] == (
        summary["trusted_by_text_count"] + summary["trusted_by_external_count"]
    )
    assert summary["trusted_fact_count"] > 0
    assert summary["candidate_only_count"] >= 0
    assert summary["needs_human_review_count"] >= 0
    assert not summary["errors"]

    trusted_ids = {fact.fact_id for fact in result.trusted_facts}
    candidate_ids = {fact.fact_id for fact in result.validated_candidates + result.candidate_only_facts}
    review_ids = {fact.fact_id for fact in result.needs_human_review}
    rejected_ids = {fact.fact_id for fact in result.rejected_facts}
    assert not trusted_ids & candidate_ids
    assert not trusted_ids & review_ids
    assert not trusted_ids & rejected_ids

    for fact in result.trusted_facts:
        assert fact.trust_status in TRUSTED_STATUSES
        assert fact.trusted is True
        assert fact.candidate_only is False
        assert _has_required_provenance(fact)

    for fact in result.validated_candidates + result.candidate_only_facts:
        assert fact.trusted is False
        assert fact.candidate_only is True
        assert fact.trust_status in {"validated_candidate", "candidate_only"}
        assert _has_required_provenance(fact)

    for fact in result.needs_human_review:
        assert fact.trusted is False
        assert fact.candidate_only is True
        assert fact.trust_status == "needs_human_review"
        assert fact.is_core_field is True
        assert is_core_financial_field(fact)
        assert _has_required_provenance(fact)

    analysis_facts = load_trusted_facts_for_analysis()
    assert len(analysis_facts) == len(result.trusted_facts)
    assert all(fact.trust_status in TRUSTED_STATUSES for fact in analysis_facts)
    assert all(fact.trusted is True for fact in analysis_facts)
    assert all(fact.candidate_only is False for fact in analysis_facts)

    assert (TRUST_RESOLUTION_OUTPUT_DIR / "trusted_facts.json").exists()
    assert (TRUST_RESOLUTION_OUTPUT_DIR / "validated_candidates.json").exists()
    assert (TRUST_RESOLUTION_OUTPUT_DIR / "candidate_only_facts.json").exists()
    assert (TRUST_RESOLUTION_OUTPUT_DIR / "needs_human_review.json").exists()
    assert (TRUST_RESOLUTION_OUTPUT_DIR / "analysis_consumption_trusted_facts.json").exists()
    assert (TRUST_RESOLUTION_OUTPUT_DIR / "trust_resolution_summary.json").exists()
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
    summary = test_trust_resolution()
    test_parse_lab_not_modified()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Parse Lab Round3 trust resolution test passed")
    return 0


def _has_required_provenance(fact) -> bool:
    raw = _model_dump(fact)
    return REQUIRED_PROVENANCE_FIELDS.issubset(raw) and bool(fact.provenance)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())


if __name__ == "__main__":
    raise SystemExit(main())
