from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.canonical_financial_fact_extraction_service import (
    load_trusted_canonical_facts_for_analysis,
)
from backend.app.modules.financial_report.services.text_parsing_quality_review_service import (
    RISK_LABELS,
    TEXT_QUALITY_REVIEW_OUTPUT_DIR,
    generate_text_parsing_quality_review_pack,
)


def test_text_quality_review_pack() -> dict[str, object]:
    result = generate_text_parsing_quality_review_pack()
    summary = result["summary"]
    samples = result["machine_precheck"]
    review_queue = result["review_queue"]
    assert 150 <= summary["sample_count"] <= 250
    assert 80 <= summary["human_review_queue_count"] <= 120
    assert summary["sample_count"] == len(samples)
    assert summary["human_review_queue_count"] == len(review_queue)

    categories = summary["category_distribution"]
    assert categories.get("financial_numeric", 0) > 0
    assert categories.get("financial_explanation", 0) > 0
    assert categories.get("sentiment_strategy", 0) > 0
    assert categories.get("complex_language", 0) > 0

    risks = summary["risk_label_distribution"]
    assert set(risks).issubset(set(RISK_LABELS))
    assert "low_risk" in risks
    assert "numeric_parse_risk" in risks
    assert "sentence_boundary_risk" in risks

    for sample in samples:
        assert sample["sample_id"]
        assert sample["raw_text"]
        assert sample["parsed_text"]
        assert sample["ai_summary"]
        assert sample["ai_precheck"]
        assert sample["ai_precheck"]["risk_labels"]
        assert "trusted_by_text_candidate" in sample["ai_precheck"]
        assert sample["human_review_fields"]

    for item in review_queue:
        assert item["ai_precheck_snapshot"]
        assert item["human_review"]
        assert item["ai_human_disagreement_fields"]

    html_path = TEXT_QUALITY_REVIEW_OUTPUT_DIR / "text_quality_review_index.html"
    html = html_path.read_text(encoding="utf-8")
    assert "localStorage" in html
    assert "ai_precheck_snapshot" in html
    assert "data-field" in html
    assert "text_quality_review:" in html

    production_facts = load_trusted_canonical_facts_for_analysis(mode="production")
    assert all(not fact.is_simulated for fact in production_facts)

    assert (TEXT_QUALITY_REVIEW_OUTPUT_DIR / "text_quality_machine_precheck.json").exists()
    assert (TEXT_QUALITY_REVIEW_OUTPUT_DIR / "text_quality_human_review_template.jsonl").exists()
    assert (TEXT_QUALITY_REVIEW_OUTPUT_DIR / "text_quality_sample_summary.json").exists()
    assert html_path.exists()
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
    summary = test_text_quality_review_pack()
    test_parse_lab_not_modified()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Text parsing quality review pack test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
