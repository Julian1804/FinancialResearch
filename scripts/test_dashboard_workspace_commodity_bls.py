from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_bls_resilient_outputs() -> None:
    root = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion" / "bls_resilient_ingestion"
    diagnosis = load_json(root / "bls_failure_diagnosis.json")
    retry = load_json(root / "bls_retry_plan.json")
    queue = load_json(root / "bls_deferred_retry_queue.json")
    fallback = load_json(root / "bls_fallback_source_audit.json")
    result = load_json(root / "bls_resilient_ingestion_results.json")

    assert result["bls_resilient_ingestion_completed"] is True
    assert diagnosis["items"]
    assert "daily_threshold_reached" in {item["failure_classification"] for item in diagnosis["items"]}
    assert retry["retry_items"]
    assert queue["queue_count"] >= 1
    assert fallback["items"]
    assert result["formal_trusted_consumption"] is False


def test_commodity_taxonomy_and_dashboard_data() -> None:
    taxonomy = load_json(PROJECT_ROOT / "config" / "commodity_taxonomy.json")
    upgrade = load_json(PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion" / "commodity_schema_upgrade_summary.json")
    audit = load_json(PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion" / "commodity_source_feasibility_audit.json")
    dashboard = load_json(PROJECT_ROOT / "runtime" / "commodity_exchange_sample_ingestion" / "commodity_dashboard_v1_data.json")

    assert {"spot", "futures", "benchmark"}.issubset(set(taxonomy["price_types"]))
    assert {"COMEX", "LME", "SHFE", "World Bank", "FRED"}.issubset(set(taxonomy["exchanges"]))
    assert {"energy", "precious_metals", "base_metals", "agriculture", "chemicals"}.issubset(set(taxonomy["commodity_categories"]))
    assert upgrade["commodity_schema_upgrade_completed"] is True
    assert upgrade["price_type_counts"].get("benchmark", 0) > 0
    assert upgrade["exchange_counts"].get("World Bank", 0) > 0
    assert audit["items"]
    assert dashboard["overview_cards"]["commodity_series_count"] > 0
    assert dashboard["chart_builder"]["chart_types"] == ["line", "bar", "pie"]
    assert dashboard["candidate_only"] is True


if __name__ == "__main__":
    test_bls_resilient_outputs()
    test_commodity_taxonomy_and_dashboard_data()
    print("dashboard workspace/commodity/BLS tests passed")
