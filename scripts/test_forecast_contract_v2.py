from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "forecast_contract_v2"
PILOT_ROOT = PROJECT_ROOT / "runtime" / "manual_report_pilot" / "600519"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (OUTPUT_ROOT / "forecast_contract_v2_summary.json").exists():
        from scripts.run_forecast_contract_v2 import run_forecast_contract_v2

        run_forecast_contract_v2()


def test_contract_outputs_and_manual_pilot() -> None:
    ensure_outputs()
    summary = load_json(OUTPUT_ROOT / "forecast_contract_v2_summary.json")
    validation = load_json(OUTPUT_ROOT / "forecast_testability_results.json")
    pilot_manifest = load_json(PILOT_ROOT / "manual_pilot_manifest.json")
    prompt = (PILOT_ROOT / "copy_to_gpt_prompt_v2_1.md").read_text(encoding="utf-8")

    assert summary["forecast_contract_v2_completed"] is True
    assert summary["no_openai_api_called"] is True
    assert summary["trusted_consumption_affected"] is False
    assert validation["forecast_count"] >= 3
    assert validation["summary"].get("insufficient_evidence", 0) >= 1
    assert pilot_manifest["symbol"] == "600519"
    assert "forecast_type" in prompt
    assert "review_date" in prompt
    assert "Candidate/staging data cannot be written as trusted facts" in prompt


def test_validate_forecast_cli_contract() -> None:
    ensure_outputs()
    from scripts.run_forecast_contract_v2 import validate_by_report_path

    result = validate_by_report_path(PROJECT_ROOT / "runtime" / "analysis_reports" / "600519" / "packet_554b196c683dca80" / "v2" / "structured_report.json")
    assert result["forecast_count"] == 1
    assert result["summary"].get("insufficient_evidence") == 1
    item = result["items"][0]
    assert item["forecast_type"] == "insufficient_evidence"
    assert item["actual_data_lookup_status"] == "available"


def test_only_testable_backtest_is_non_destructive() -> None:
    ensure_outputs()
    from scripts.run_backtest_execution_v1 import run_backtest_execution_v1

    default_result = run_backtest_execution_v1()
    only_result = run_backtest_execution_v1(only_testable=True)
    default_after = load_json(PROJECT_ROOT / "runtime" / "backtest_execution_v1" / "backtest_results.json")
    assert default_result["result_counts"].get("manual_review_required", 0) >= 1
    assert only_result["non_destructive_output"] is True
    assert (PROJECT_ROOT / "runtime" / "backtest_execution_v1" / "backtest_results_testable_only.json").exists()
    assert default_after["items"]


if __name__ == "__main__":
    test_contract_outputs_and_manual_pilot()
    test_validate_forecast_cli_contract()
    test_only_testable_backtest_is_non_destructive()
    print("forecast contract v2 tests passed")
