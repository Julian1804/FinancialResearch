from __future__ import annotations

import json
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "frdata_connectors_phase6"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (OUTPUT_ROOT / "connector_run_results.json").exists():
        from scripts.run_frdata_connectors_phase6 import run_phase6

        run_phase6()


def test_phase6_outputs() -> None:
    ensure_outputs()
    runs = load_json(OUTPUT_ROOT / "connector_run_results.json")
    staging = load_json(OUTPUT_ROOT / "consumption_grade_staging_v2.json")
    mismatch = load_json(OUTPUT_ROOT / "a_share_daily_mismatch_review.json")
    bundle = load_json(OUTPUT_ROOT / "sample_analysis_data_bundle.json")

    assert runs["candidate_only"] is True
    assert runs["formal_trusted_consumption"] is False
    assert runs["no_openai_api_called"] is True
    assert runs["parse_lab_affected"] is False
    assert runs["trusted_consumption_affected"] is False

    source_ids = {item["source_id"] for item in runs["items"]}
    assert "baostock_daily" in source_ids
    assert "akshare_tencent_daily" in source_ids
    assert "bls_public_api" in source_ids
    assert "treasury_fiscaldata" in source_ids
    assert "sec_edgar_companyfacts" in source_ids
    assert "world_bank_pink_sheet" in source_ids
    assert "cninfo_disclosure" in source_ids

    assert all(item["candidate_only"] is True for item in staging["items"])
    assert all(item["formal_trusted_consumption"] is False for item in staging["items"])
    assert mismatch["summary"]["manual_value_edit_performed"] is False
    assert bundle["formal_trusted_consumption"] is False
    assert bundle["no_openai_api_called"] is True


def test_metadata_index() -> None:
    ensure_outputs()
    metadata_summary = load_json(OUTPUT_ROOT / "metadata_index_summary.json")
    db_path = Path(metadata_summary["metadata_db_path"])
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    try:
        for table in [
            "connector_run_log",
            "dataset_index",
            "raw_artifact_index",
            "normalized_dataset_index",
            "quality_check_log",
            "trust_status_log",
            "staging_dataset_index",
            "source_status_index",
        ]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count >= 0
        run_count = conn.execute("SELECT COUNT(*) FROM connector_run_log").fetchone()[0]
        assert run_count >= 8
    finally:
        conn.close()


if __name__ == "__main__":
    test_phase6_outputs()
    test_metadata_index()
    print("phase6 tests passed")
