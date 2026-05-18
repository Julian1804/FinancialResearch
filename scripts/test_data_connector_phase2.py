from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.data_connector_phase2_service import (  # noqa: E402
    METADATA_DB_PATH,
    OUTPUT_ROOT,
)
from scripts.run_data_connector_phase2 import main as run_phase2  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase2_run_outputs() -> None:
    assert run_phase2() == 0
    for path in [
        OUTPUT_ROOT / "connector_run_results.json",
        OUTPUT_ROOT / "quality_check_results.json",
        OUTPUT_ROOT / "trust_resolution_results.json",
        OUTPUT_ROOT / "storage_estimate_refresh.json",
        OUTPUT_ROOT / "phase2_summary.json",
        METADATA_DB_PATH,
    ]:
        assert path.exists(), f"missing output: {path}"
    runs = read_json(OUTPUT_ROOT / "connector_run_results.json")
    assert runs["success_count"] >= 5
    assert runs["no_full_download"] is True
    assert runs["no_openai_api_called"] is True
    assert runs["trusted_consumption_affected"] is False
    assert runs["parse_lab_affected"] is False
    assert runs["default_v1_1_replaced"] is False


def test_source_coverage_and_outputs() -> None:
    runs = read_json(OUTPUT_ROOT / "connector_run_results.json")
    items = runs["items"]
    success = [item for item in items if item["status"] == "success"]
    categories = {item["source_id"] for item in success}
    assert "baostock_daily" in categories
    assert "cninfo_disclosure" in categories
    assert "treasury_fiscaldata" in categories
    assert "world_bank_pink_sheet" in categories

    for item in success:
        assert item["record_count"] > 0
        assert item["raw_output_path"]
        assert item["normalized_output_path"]
        assert Path(item["raw_output_path"]).exists()
        assert Path(item["normalized_output_path"]).exists()
        assert item["candidate_only"] is True
        assert item["consumption_eligible"] is False

    failed = [item for item in items if item["status"] == "failed"]
    assert any(item["source_id"] == "akshare_traceable_official" for item in failed)
    assert any(item["source_id"] == "fred_public_csv" for item in failed)


def test_quality_and_trust_results() -> None:
    quality = read_json(OUTPUT_ROOT / "quality_check_results.json")["items"]
    trust = read_json(OUTPUT_ROOT / "trust_resolution_results.json")["items"]
    assert quality
    assert trust
    assert any(item["status"] == "quality_passed" for item in quality)
    assert all(item["status"] in {"quality_passed", "quality_warning", "quality_failed"} for item in quality)
    assert any(item["trust_status"] == "trusted_by_real_external_candidate" for item in trust)
    assert any(item["trust_status"] == "candidate_external_data" for item in trust)
    assert any(item["trust_status"] == "trusted_source_but_quality_failed" for item in trust)
    assert all(item["candidate_only"] is True for item in trust)
    assert all(item["consumption_eligible"] is False for item in trust)


def test_metadata_index() -> None:
    with sqlite3.connect(METADATA_DB_PATH) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"source_registry_index", "connector_run_log", "normalized_dataset_index", "quality_check_log"}.issubset(tables)
        run_count = conn.execute("SELECT COUNT(*) FROM connector_run_log").fetchone()[0]
        dataset_count = conn.execute("SELECT COUNT(*) FROM normalized_dataset_index").fetchone()[0]
        assert run_count >= 5
        assert dataset_count >= 5


def test_boundaries() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_phase2_run_outputs()
    test_source_coverage_and_outputs()
    test_quality_and_trust_results()
    test_metadata_index()
    test_boundaries()
    summary = read_json(OUTPUT_ROOT / "phase2_summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
