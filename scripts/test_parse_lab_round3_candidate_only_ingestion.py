from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.parse_lab_field_candidate_ingestion_service import (
    PROVISIONAL_FACT_OUTPUT_DIR,
    ingest_parse_lab_round3_field_candidates,
    summarize_ingestion_result,
)


REQUIRED_FACT_FIELDS = {
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
    "candidate_only_reason",
}


def test_candidate_only_ingestion() -> dict[str, object]:
    result = ingest_parse_lab_round3_field_candidates()
    summary = summarize_ingestion_result(result)
    assert summary["provisional_fact_count"] == 273
    assert summary["review_queue_count"] == 60
    assert summary["trusted_fact_count"] == 0
    assert summary["validation_status_distribution"] == {"matched": 257, "partially_matched": 16}
    assert summary["review_queue_status_distribution"] == {"needs_human_review": 29, "table_value_missing": 31}
    assert not summary["errors"]

    for fact in result.provisional_facts:
        raw = _model_dump(fact)
        assert REQUIRED_FACT_FIELDS.issubset(raw)
        assert fact.source_pdf
        assert fact.source_page > 0
        assert fact.validation_status in {"matched", "partially_matched"}
        assert fact.candidate_only is True
        assert fact.trusted is False
        assert fact.candidate_only_reason
        assert fact.provenance

    for item in result.review_queue:
        assert item.validation_status in {"table_value_missing", "needs_human_review", "conflict"}
        assert item.candidate_only is True
        assert item.trusted is False
        assert item.source_pdf
        assert item.source_page > 0

    assert (PROVISIONAL_FACT_OUTPUT_DIR / "provisional_facts.json").exists()
    assert (PROVISIONAL_FACT_OUTPUT_DIR / "provisional_facts.jsonl").exists()
    assert (PROVISIONAL_FACT_OUTPUT_DIR / "candidate_only_review_queue.json").exists()
    assert (PROVISIONAL_FACT_OUTPUT_DIR / "ingestion_summary.json").exists()
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
    summary = test_candidate_only_ingestion()
    test_parse_lab_not_modified()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Parse Lab Round3 candidate-only ingestion test passed")
    return 0


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())


if __name__ == "__main__":
    raise SystemExit(main())
