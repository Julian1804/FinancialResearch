from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "field_level_trusted_preview"
DASHBOARD_ROOT = PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1"


def main() -> None:
    contract = read_json(RUNTIME_ROOT / "field_level_trust_contract.json")
    selector = read_json(RUNTIME_ROOT / "trusted_candidate_preview_selector_results.json")
    limited = read_json(RUNTIME_ROOT / "a_share_etf_limited_field_review.json")
    packet_input = read_json(RUNTIME_ROOT / "analysis_packet_trusted_preview_input.json")
    statistical_input = read_json(RUNTIME_ROOT / "statistical_report_trusted_preview_input.json")
    dashboard_summary = read_json(RUNTIME_ROOT / "dashboard_field_trust_summary.json")
    dashboard_data = read_json(DASHBOARD_ROOT / "dashboard_v1_sample_data.json")
    html = (DASHBOARD_ROOT / "index.html").read_text(encoding="utf-8")
    packet_600519 = read_json(PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2" / "600519" / "analysis_packet.json")
    latest_report_manifest = read_json(PROJECT_ROOT / "runtime" / "dashboard_v1" / "statistical_reports" / "latest_statistical_report_manifest.json")
    report_json = read_json(Path(latest_report_manifest["paths"]["statistical_report_json"]))

    assert contract["preview_layer_policy"]["formal_trusted_consumption"] is False
    assert set(contract["field_level_trust"].keys()) >= {"open", "high", "low", "close", "amount", "turnover_rate", "pct_change", "preclose"}
    for field in ["open", "high", "low", "close"]:
        assert contract["field_level_trust"][field]["trust_status"] == "trusted_candidate"
        assert contract["field_level_trust"][field]["consumption_preview_allowed"] is True
    for field in ["amount", "turnover_rate", "pct_change", "preclose"]:
        assert limited["limited_fields"][field]["current_status"] == "ready_for_trusted_candidate_limited"
        assert contract["field_level_trust"][field]["consumption_preview_allowed"] is False

    assert selector["included_records"] > 0
    assert selector["formal_trusted_consumption"] is False
    assert packet_input["can_consume_trusted_candidate_fields"] is True
    assert statistical_input["field_level_trusted_candidate_preview_available"] is True
    assert dashboard_summary["formal_trusted_consumption"] is False

    assert dashboard_data["field_level_trusted_preview"]["preview_record_count"] == selector["included_records"]
    for marker in [
        "Field-Level Trusted Candidate Preview",
        "Trusted Candidate Preview Selector",
        "OHLC Trusted Candidate Fields",
        "Limited Field Review",
        "Formal Trusted Consumption Off",
    ]:
        assert marker in html

    packet_preview = packet_600519["market_daily_summary"]["field_level_trusted_candidate_preview"]
    assert packet_preview["status"] == "available_trusted_candidate_preview"
    assert packet_preview["formal_trusted_consumption"] is False
    assert set(packet_preview["trusted_candidate_fields"]) == {"open", "high", "low", "close"}

    report_preview = report_json["field_level_trusted_candidate_preview"]
    assert report_preview["field_level_trusted_candidate_preview_available"] is True
    assert report_preview["formal_trusted_consumption"] is False

    parse_lab_status = git_status(PROJECT_ROOT.parent / "parse_lab")
    assert parse_lab_status == "", f"parse_lab changed unexpectedly: {parse_lab_status}"

    result = {
        "field_level_trusted_preview_tests_passed": True,
        "selector_included_records": selector["included_records"],
        "trusted_candidate_fields": packet_preview["trusted_candidate_fields"],
        "formal_trusted_consumption": False,
        "parse_lab_unchanged": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AssertionError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def git_status(path: Path) -> str:
    if not path.exists():
        return ""
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=path,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    main()
