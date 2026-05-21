from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_automated_ingestion_v1 import CONFIG_ROOT, ENTITY_ROOT, RUNTIME_ROOT, run_automated_ingestion_v1  # noqa: E402
from scripts.run_dashboard_v1 import FRONTEND_ROOT, run_dashboard_v1  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> dict:
    summary_path = RUNTIME_ROOT / "automated_ingestion_summary.json"
    if summary_path.exists():
        return read_json(summary_path)
    return run_automated_ingestion_v1()


def test_entity_master_and_crosswalk() -> None:
    summary = ensure_outputs()
    assert summary["entity_master_completed"] is True
    entity_payload = read_json(ENTITY_ROOT / "entity_master_schema.json")
    crosswalk = read_json(ENTITY_ROOT / "source_identifier_crosswalk.json")
    assert entity_payload["entity_count"] >= 10
    assert crosswalk["crosswalk_count"] >= 10
    assert "equity" in entity_payload["schema"]["entity_types"]
    assert "fund_or_etf" in entity_payload["schema"]["entity_types"]
    assert isinstance(crosswalk["unresolved_entity_queue"], list)


def test_source_strategy_and_schedule() -> None:
    ensure_outputs()
    strategy = read_json(CONFIG_ROOT / "automated_source_strategy.json")
    schedule = read_json(CONFIG_ROOT / "automated_ingestion_schedule.json")
    source_types = {source["source_type"] for source in strategy["sources"]}
    assert "official_automated" in source_types
    assert "official_on_hold" in source_types
    assert "licensed_authorized_source" in source_types
    assert schedule["enabled_count"] > 0
    assert any(item["source_id"] == "morningstar_direct" for item in schedule["items"])


def test_akshare_and_morningstar_candidates() -> None:
    ensure_outputs()
    akshare = read_json(RUNTIME_ROOT / "akshare_api_audit.json")
    morningstar = read_json(RUNTIME_ROOT / "morningstar_controlled_ingestion_candidates.json")
    assert akshare["sample_success_count"] >= 1
    assert "stock_zh_a_hist_tx" in {item["function_name"] for item in akshare["items"]}
    assert morningstar["no_auto_login"] is True
    assert morningstar["no_password_saved"] is True
    assert morningstar["token_leaked"] is False
    assert morningstar["controlled_candidate_count"] >= 1
    assert "md_auth_token" not in json.dumps(morningstar)


def test_pipeline_pilot_and_dashboard_status() -> None:
    ensure_outputs()
    ingestion = read_json(RUNTIME_ROOT / "ingestion_run_results.json")
    dashboard = read_json(RUNTIME_ROOT / "dashboard_automation_status.json")
    assert ingestion["controlled_pilot_completed"] is True
    assert len(ingestion["run_records"]) >= 4
    assert dashboard["title"] == "Automated Ingestion System v1"
    assert dashboard["entity_master"]["crosswalk_count"] >= 10
    assert dashboard["data_trust_pipeline"]["trusted"] == 0
    assert dashboard["formal_trusted_consumption_affected"] is False


def test_dashboard_markers() -> None:
    ensure_outputs()
    run_dashboard_v1()
    html_text = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    for marker in [
        "Automated Ingestion System v1",
        "Entity Master Status",
        "Identifier Crosswalk",
        "Unresolved Entity Queue",
        "Ingestion Schedule",
        "Latest Ingestion Runs",
        "Data Trust Pipeline",
        "Official On-hold Sources",
    ]:
        assert marker in html_text
    assert "Streamlit" not in html_text


def test_git_tracked_token_not_leaked() -> None:
    secrets_path = CONFIG_ROOT / "local_secrets.json"
    actual_tokens: list[str] = []
    if secrets_path.exists():
        secrets = read_json(secrets_path)
        token = (secrets.get("morningstar") or {}).get("md_auth_token")
        if token:
            actual_tokens.append(token)
    result = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    tracked = [PROJECT_ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]
    for path in tracked:
        if not path.exists() or path.is_dir():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        assert not any(token and token in text for token in actual_tokens), f"sensitive token value leaked in {path}"


def run_all() -> None:
    test_entity_master_and_crosswalk()
    test_source_strategy_and_schedule()
    test_akshare_and_morningstar_candidates()
    test_pipeline_pilot_and_dashboard_status()
    test_dashboard_markers()
    test_git_tracked_token_not_leaked()


if __name__ == "__main__":
    run_all()
    print("automated_ingestion_v1 tests passed")
