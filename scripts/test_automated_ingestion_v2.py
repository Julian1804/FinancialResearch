from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_automated_ingestion_v2 import V2_ROOT, run_automated_ingestion_v2  # noqa: E402
from scripts.run_dashboard_v1 import FRONTEND_ROOT, run_dashboard_v1  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> dict:
    path = V2_ROOT / "automated_ingestion_v2_summary.json"
    if path.exists():
        return read_json(path)
    return run_automated_ingestion_v2()


def test_entity_resolution_v2() -> None:
    summary = ensure_outputs()
    entity = read_json(V2_ROOT / "entity_resolution_v2_results.json")
    assert entity["unresolved_before"] >= entity["unresolved_after"]
    assert entity["source_specific_unresolved_count"] >= 0
    assert entity["duplicate_risk_count"] == 0
    assert summary["entity_resolution"]["crosswalk_increment"] >= 0


def test_cross_source_validation_v2() -> None:
    ensure_outputs()
    validation = read_json(V2_ROOT / "cross_source_validation_v2_results.json")
    assert validation["a_share"]["summary"]["status"] == "cross_validated_candidate"
    assert validation["a_share"]["summary"]["trusted_consumption"] is False
    assert validation["macro_rates"]["summary"]["status"] == "freshness_validated_candidate"
    assert validation["commodity"]["summary"]["benchmark_spot_futures_guard"] is True


def test_morningstar_and_schedule_guards() -> None:
    ensure_outputs()
    morningstar = read_json(V2_ROOT / "morningstar_controlled_validation_v2_results.json")
    scheduled = read_json(V2_ROOT / "scheduled_run_simulation_v2.json")
    assert morningstar["no_auto_login"] is True
    assert morningstar["no_password_saved"] is True
    assert morningstar["token_leaked"] is False
    assert morningstar["summary"]["large_download_performed"] is False
    assert scheduled["summary"]["daily_group_executed"] is True
    assert scheduled["summary"]["quarterly_group_dry_run"] is True


def test_data_lake_and_trust_progression() -> None:
    ensure_outputs()
    data_lake = read_json(V2_ROOT / "data_lake_organization_check.json")
    trust = read_json(V2_ROOT / "trust_progression_v2.json")
    assert data_lake["summary"]["metadata_db_exists"] is True
    assert data_lake["summary"]["crosswalk_v2_exists"] is True
    assert trust["summary"]["cross_validated"] >= 1
    assert trust["summary"]["trusted_candidate"] == 0


def test_dashboard_v2_markers() -> None:
    ensure_outputs()
    run_dashboard_v1()
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    for marker in [
        "Automated Ingestion v2",
        "Entity Resolution v2",
        "Cross-source Validation v2",
        "Scheduled Run Simulation",
        "Candidate Status Upgrade",
    ]:
        assert marker in html
    assert "Streamlit" not in html


def test_token_value_not_in_tracked_files() -> None:
    secrets_path = PROJECT_ROOT / "config" / "local_secrets.json"
    token = ""
    if secrets_path.exists():
        token = ((read_json(secrets_path).get("morningstar") or {}).get("md_auth_token") or "")
    result = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    if not token:
        return
    for rel in result.stdout.splitlines():
        path = PROJECT_ROOT / rel
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert token not in text, f"Morningstar token leaked in tracked file {rel}"


def run_all() -> None:
    test_entity_resolution_v2()
    test_cross_source_validation_v2()
    test_morningstar_and_schedule_guards()
    test_data_lake_and_trust_progression()
    test_dashboard_v2_markers()
    test_token_value_not_in_tracked_files()


if __name__ == "__main__":
    run_all()
    print("automated_ingestion_v2 tests passed")
