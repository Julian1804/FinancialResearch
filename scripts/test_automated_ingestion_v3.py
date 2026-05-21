from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_automated_ingestion_v3 import V3_ROOT, run_automated_ingestion_v3  # noqa: E402
from scripts.run_dashboard_v1 import FRONTEND_ROOT, run_dashboard_v1  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> dict:
    path = V3_ROOT / "automated_ingestion_v3_summary.json"
    if path.exists():
        return read_json(path)
    return run_automated_ingestion_v3()


def test_candidate_promotion_rules() -> None:
    ensure_outputs()
    rules = read_json(PROJECT_ROOT / "config" / "candidate_promotion_rules.json")
    statuses = {item["status"] for item in rules["states"]}
    assert {
        "candidate",
        "schema_validated_candidate",
        "cross_validated_candidate",
        "freshness_validated_candidate",
        "field_validated_candidate",
        "ready_for_trusted_candidate",
        "trusted_candidate",
        "blocked",
    }.issubset(statuses)


def test_a_share_expansion_and_cross_validation() -> None:
    ensure_outputs()
    result = read_json(V3_ROOT / "a_share_etf_controlled_expansion_results.json")
    assert result["summary"]["symbol_count"] == 10
    assert result["summary"]["common_records"] == 300
    assert result["summary"]["dataset_status"] == "cross_validated_candidate"
    assert result["summary"]["formal_trusted_consumption"] is False


def test_macro_incremental_and_morningstar_depth() -> None:
    ensure_outputs()
    macro = read_json(V3_ROOT / "macro_rates_fx_commodity_incremental_results.json")
    morningstar = read_json(V3_ROOT / "morningstar_field_depth_validation_results.json")
    assert macro["summary"]["datasets_checked"] >= 30
    assert macro["summary"]["repeated_full_backfill_performed"] is False
    assert morningstar["summary"]["selected_dataset_count"] == 5
    assert morningstar["summary"]["large_download_performed"] is False
    assert morningstar["no_auto_login"] is True
    assert morningstar["no_password_saved"] is True
    assert morningstar["token_leaked"] is False


def test_entity_schedule_datalake() -> None:
    ensure_outputs()
    entity = read_json(V3_ROOT / "entity_resolution_v3_results.json")
    schedule = read_json(V3_ROOT / "scheduled_run_v2_results.json")
    lake = read_json(V3_ROOT / "data_lake_metadata_crosswalk_check.json")
    assert entity["summary"]["rejected_fuzzy_match_count"] == entity["summary"]["probable_match_count"]
    assert schedule["summary"]["failed"] == 0
    assert schedule["summary"]["on_hold"] >= 1
    assert lake["summary"]["metadata_db_exists"] is True
    assert lake["summary"]["crosswalk_v2_exists"] is True


def test_dashboard_v3_markers_and_no_streamlit() -> None:
    ensure_outputs()
    run_dashboard_v1()
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    for marker in [
        "Automated Ingestion v3",
        "Operational Data Filling",
        "Candidate Promotion Summary",
        "A-share / ETF Controlled Expansion",
        "Macro Rates FX Commodity Incremental",
        "Morningstar Field Depth",
        "Scheduled Run v2",
    ]:
        assert marker in html
    assert "Streamlit" not in html


def test_token_value_not_in_tracked_files() -> None:
    secrets_path = PROJECT_ROOT / "config" / "local_secrets.json"
    token = ""
    if secrets_path.exists():
        token = ((read_json(secrets_path).get("morningstar") or {}).get("md_auth_token") or "")
    if not token:
        return
    result = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    for rel in result.stdout.splitlines():
        path = PROJECT_ROOT / rel
        if not path.exists() or path.is_dir():
            continue
        assert token not in path.read_text(encoding="utf-8", errors="ignore"), f"token leaked in {rel}"


def run_all() -> None:
    test_candidate_promotion_rules()
    test_a_share_expansion_and_cross_validation()
    test_macro_incremental_and_morningstar_depth()
    test_entity_schedule_datalake()
    test_dashboard_v3_markers_and_no_streamlit()
    test_token_value_not_in_tracked_files()


if __name__ == "__main__":
    run_all()
    print("automated_ingestion_v3 tests passed")
