from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (OUTPUT_ROOT / "builder_run_summary.json").exists():
        from scripts.run_analysis_packet_builder_v2 import run_builder_v2

        run_builder_v2()


def test_packets_are_generated_from_real_phase6_data() -> None:
    ensure_outputs()
    summary = load_json(OUTPUT_ROOT / "builder_run_summary.json")
    assert summary["packet_count"] == 2
    assert summary["no_openai_api_called"] is True
    assert summary["trusted_consumption_affected"] is False

    for symbol in ["600519", "000001"]:
        root = OUTPUT_ROOT / symbol
        packet = load_json(root / "analysis_packet.json")
        manifest = load_json(root / "packet_manifest.json")
        prompt = (root / "copy_to_gpt_prompt.md").read_text(encoding="utf-8")

        assert manifest["target_symbol"] == symbol
        assert packet["target_symbol"] == symbol
        assert packet["market_daily_summary"]["status"] == "available_candidate_staging"
        assert packet["market_daily_summary"]["latest_trade_date"]
        assert packet["guardrails"]["no_openai_api_called"] is True
        assert packet["guardrails"]["candidate_data_not_trusted_facts"] is True
        assert "Candidate/staging data is not trusted final fact" in prompt
        assert "FINAL_REPORT_JSON" in prompt


def test_data_layer_markers_and_ingestion_schema() -> None:
    ensure_outputs()
    packet = load_json(OUTPUT_ROOT / "600519" / "analysis_packet.json")
    staging_statuses = {item["staging_status"] for item in packet["source_layers"]}
    assert "market_daily_candidate_staging" in staging_statuses
    assert "market_daily_secondary_candidate_staging" in staging_statuses
    assert "cross_validated_candidate" in staging_statuses
    assert "needs_review_candidate" in staging_statuses
    assert "blocked" in staging_statuses
    assert "not_used_in_current_pipeline" in staging_statuses
    assert packet["financial_report_metadata"]["status"] == "insufficient_evidence"

    validation = load_json(OUTPUT_ROOT / "sample_ingested_report_validation.json")
    assert validation["schema_valid"] is True
    parsed = validation["parsed_report"]
    for field in [
        "packet_id",
        "data_snapshot_id",
        "target_symbol",
        "as_of_date",
        "analysis_scope",
        "key_assumptions",
        "investment_view",
        "forecast_items",
        "risk_items",
        "watchlist_signals",
        "confidence",
        "next_review_date",
        "insufficient_evidence_items",
        "candidate_data_usage_note",
    ]:
        assert field in parsed


def test_cninfo_metadata_available_for_000001_only() -> None:
    ensure_outputs()
    packet_000001 = load_json(OUTPUT_ROOT / "000001" / "analysis_packet.json")
    assert packet_000001["financial_report_metadata"]["status"] == "available_metadata_only"
    assert packet_000001["financial_report_metadata"]["items"]
    assert all(item["source_id"] == "cninfo_disclosure" for item in packet_000001["financial_report_metadata"]["items"])


if __name__ == "__main__":
    test_packets_are_generated_from_real_phase6_data()
    test_data_layer_markers_and_ingestion_schema()
    test_cninfo_metadata_available_for_000001_only()
    print("analysis packet builder v2 tests passed")
