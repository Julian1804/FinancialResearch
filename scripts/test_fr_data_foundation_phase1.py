from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.data_connector_feasibility_service import (  # noqa: E402
    REGISTRY_OUTPUT_DIR,
)
from backend.app.modules.financial_report.services.human_in_loop_analysis_service import (  # noqa: E402
    OUTPUT_DIR as ANALYSIS_OUTPUT_DIR,
    build_sample_analysis_packet_and_ingestion,
)
from scripts.run_fr_data_foundation_phase1 import SUMMARY_PATH, main as run_phase1  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sample_packet_and_ingestion() -> None:
    result = build_sample_analysis_packet_and_ingestion()
    summary = result["summary"]
    assert summary["completed"] is True
    assert summary["schema_valid"] is True
    packet = result["packet"]["packet"]
    ingestion = result["ingestion"]
    assert packet["packet_id"] == summary["packet_id"]
    assert packet["data_snapshot_id"] == summary["data_snapshot_id"]
    assert packet["trusted_facts"]
    assert packet["candidate_only_policy"]
    assert "FINAL_REPORT_JSON" in result["packet"]["gpt_web_prompt"]
    assert ingestion["report_id"] == summary["report_id"]
    assert ingestion["schema_valid"] is True
    assert ingestion["backtest_ready_forecast_items"]
    assert ingestion["no_openai_api_called"] is True


def test_phase1_outputs_and_registry() -> None:
    exit_code = run_phase1()
    assert exit_code == 0
    summary = read_json(SUMMARY_PATH)
    assert summary["human_in_loop_skeleton_completed"] is True
    assert summary["analysis_packet_completed"] is True
    assert summary["gpt_web_prompt_completed"] is True
    assert summary["report_ingestion_completed"] is True
    assert summary["data_connector_feasibility_audit_completed"] is True
    assert summary["no_openai_api_called"] is True
    assert summary["trusted_consumption_affected"] is False
    assert summary["parse_lab_affected"] is False
    assert summary["default_v1_1_replaced"] is False
    assert summary["source_count"] >= 10
    assert summary["smoke_success_count"] >= 5

    registry = read_json(REGISTRY_OUTPUT_DIR / "source_registry.json")
    assert registry["source_count"] == summary["source_count"]
    assert registry["official_source_only_policy"]
    assert all("data_quality_checks" in item for item in registry["entries"])
    assert any(item["source_id"] == "sec_edgar_companyfacts" and item["trusted_external_eligible"] for item in registry["entries"])
    assert any(item["source_id"] == "wind_terminal" and item["requires_points_or_paid_quota"] for item in registry["entries"])

    smoke = read_json(REGISTRY_OUTPUT_DIR / "connector_smoke_results.json")
    assert smoke["no_openai_api_called"] is True
    assert smoke["no_paid_source_used"] is True
    assert smoke["no_full_crawler_started"] is True
    assert any(item["test_id"] == "cninfo_annual_report_discovery" for item in smoke["tests"])
    assert any(item["category"] == "commodity_data" and item["status"] == "success" for item in smoke["tests"])

    storage = read_json(REGISTRY_OUTPUT_DIR / "storage_estimate.json")
    assert "hot_storage_2tb_desktop" in storage
    assert "cold_storage_8tb_nas" in storage

    docs = summary["outputs"]["docs"]
    for path in docs.values():
        assert Path(path).exists()


def test_boundaries() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_sample_packet_and_ingestion()
    test_phase1_outputs_and_registry()
    test_boundaries()
    summary = read_json(SUMMARY_PATH)
    print(json.dumps({
        "status": "ok",
        "packet_id": summary["sample_packet_id"],
        "source_count": summary["source_count"],
        "smoke_success_count": summary["smoke_success_count"],
        "smoke_failed_count": summary["smoke_failed_count"],
        "smoke_skipped_count": summary["smoke_skipped_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
