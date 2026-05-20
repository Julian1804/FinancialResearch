from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_market_data_foundation_phase2 import run_market_data_foundation_phase2  # noqa: E402


ROOT = PROJECT_ROOT / "runtime" / "market_data_foundation_phase2"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (ROOT / "phase2_summary.json").exists():
        run_market_data_foundation_phase2()


def test_phase2_outputs_and_catalog_update() -> None:
    ensure_outputs()
    summary = load_json(ROOT / "phase2_summary.json")
    catalog = load_json(ROOT / "foundation_catalog_update.json")
    assert summary["phase2_market_data_foundation_completed"] is True
    assert summary["catalog_items_processed"] >= 30
    assert summary["records_normalized"] > 0
    assert summary["formal_trusted_consumption"] is False
    assert summary["no_openai_api_called"] is True
    assert catalog["summary"]["available"] >= 20
    assert catalog["summary"]["dashboard_ready"] >= 20
    metric_ids = {item["metric_id"] for item in catalog["items"] if item["current_status"] == "available"}
    assert {"us_30y_yield", "sofr", "usd_cny", "usd_jpy", "eur_usd"}.issubset(metric_ids)


def test_phase2_raw_normalized_quality_revision_metadata() -> None:
    ensure_outputs()
    raw = load_json(ROOT / "raw_artifact_index.json")
    quality = load_json(ROOT / "quality_results.json")
    revision = load_json(ROOT / "revision_log.json")
    vintage = load_json(ROOT / "vintage_summary.json")
    paths = load_json(ROOT / "normalized_paths.json")
    records_path = ROOT / "normalized_phase2_records.jsonl"

    assert raw["items"]
    assert quality["quality_counts"].get("quality_passed", 0) >= 1
    assert revision["revision_count"] >= 0
    assert vintage["dataset_count"] >= 1
    assert records_path.exists() and records_path.stat().st_size > 0
    for key in ["rates_bonds_latest", "fx_latest"]:
        assert key in paths
        assert Path(paths[key]).exists()

    db = ROOT / "market_data_foundation_metadata.sqlite"
    assert db.exists()
    conn = sqlite3.connect(db)
    try:
        for table in [
            "connector_run_log",
            "raw_artifact_index",
            "normalized_dataset_index",
            "quality_check_log",
            "revision_log",
            "foundation_catalog_update",
        ]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count >= 0
    finally:
        conn.close()


def test_dashboard_reads_phase2_summary() -> None:
    ensure_outputs()
    dashboard_data = load_json(PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1" / "dashboard_v1_sample_data.json")
    assert dashboard_data["market_data_phase2_summary"]["phase2_market_data_foundation_completed"] is True
    assert dashboard_data["macro_asset_summary"]["phase2_summary"]["available"] >= 20
    assert dashboard_data["legacy_streamlit_used"] is False


if __name__ == "__main__":
    run_market_data_foundation_phase2()
    test_phase2_outputs_and_catalog_update()
    test_phase2_raw_normalized_quality_revision_metadata()
    test_dashboard_reads_phase2_summary()
    print("market data foundation phase2 tests passed")
