from __future__ import annotations

import json
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_macro_asset_outputs() -> None:
    summary = load_json(RUNTIME_ROOT / "ingestion_summary.json")
    catalog = load_json(RUNTIME_ROOT / "dataset_catalog.json")
    quality = load_json(RUNTIME_ROOT / "quality_results.json")
    dashboard = load_json(RUNTIME_ROOT / "dashboard_macro_asset_summary.json")
    raw_index = load_json(RUNTIME_ROOT / "raw_artifact_index.json")
    revision = load_json(RUNTIME_ROOT / "revision_log.json")

    assert summary["record_count"] > 0
    assert summary["series_count"] >= 10
    assert summary["source_counts"].get("fred_public_api", 0) > 0
    assert summary["source_counts"].get("treasury_fiscaldata", 0) > 0
    assert summary["source_counts"].get("world_bank_pink_sheet", 0) > 0
    assert summary["no_openai_api_called"] is True
    assert summary["trusted_consumption_affected"] is False

    assert catalog["dataset_count"] == quality["dataset_count"]
    assert dashboard["macro_series_count"] > 0
    assert dashboard["asset_commodity_series_count"] > 0
    assert dashboard["record_count"] == summary["record_count"]
    assert len(raw_index["items"]) > 0
    assert "retrieval_snapshot_id" in revision["vintage_policy"]

    for key in ["runtime_macro_latest", "runtime_commodity_latest"]:
        assert Path(catalog["normalized_paths"][key]).exists()


def test_metadata_index() -> None:
    db_path = RUNTIME_ROOT / "macro_asset_metadata.sqlite"
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()
        }
        assert {"ingestion_runs", "dataset_catalog", "quality_results", "revision_log", "raw_artifacts"}.issubset(tables)
        dataset_count = conn.execute("select count(*) from dataset_catalog").fetchone()[0]
        assert dataset_count > 0


if __name__ == "__main__":
    test_macro_asset_outputs()
    test_metadata_index()
    print("macro/asset historical ingestion tests passed")
