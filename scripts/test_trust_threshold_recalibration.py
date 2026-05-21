from __future__ import annotations

import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_policy_and_interface_classification() -> None:
    policy = read_json(PROJECT_ROOT / "config" / "institutional_data_source_trust_policy.json")
    assert_true("institutional_proxy_source" in policy["source_type_taxonomy"], "institutional proxy source type missing")
    assert_true("institutional_proxy_high_confidence_candidate" in policy["candidate_state_policy"], "proxy status missing")

    rules = read_json(PROJECT_ROOT / "config" / "candidate_promotion_rules.json")
    states = {item["status"] for item in rules["states"]}
    assert_true("institutional_proxy_high_confidence_candidate" in states, "candidate promotion proxy status missing")
    assert_true(rules["trusted_threshold_recalibration"]["coverage_100_percent_not_required"] is True, "trusted threshold not recalibrated")

    interface = read_json(PROJECT_ROOT / "config" / "akshare_interface_trust_classification.json")
    items = {item["interface_id"]: item for item in interface["interfaces"]}
    assert_true(items["akshare_tencent_daily"]["trust_status"] == "institutional_proxy_high_confidence_candidate", "Tencent interface not upgraded")
    assert_true(items["akshare_eastmoney_stock_zh_a_hist"]["trust_status"] == "deferred", "Eastmoney-backed interface must remain deferred")
    assert_true(items["akshare_unknown_or_unclassified"]["trust_status"] == "candidate_only", "unknown AKShare interface must stay candidate")


def test_a_share_recalibration() -> None:
    result = read_json(PROJECT_ROOT / "runtime" / "automated_ingestion_system" / "trust_threshold_recalibration" / "a_share_etf_trust_recalibration_result.json")
    summary = result["summary"]
    assert_true(summary["input_common_records"] == 1216, "unexpected common record count")
    assert_true(summary["mismatch_count"] == 0, "mismatch count must be zero")
    assert_true(summary["trusted_candidate_assigned"] is True, "OHLC trusted candidate not assigned")
    assert_true(summary["ready_for_trusted_candidate_assigned"] is True, "ready_for_trusted candidate not assigned")
    assert_true(summary["formal_trusted_consumption"] is False, "formal trusted consumption must remain off")


def test_dashboard_markers_and_guards() -> None:
    html = (PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "Trust Threshold Recalibration",
        "Institutional Proxy Source",
        "Institutional Proxy High Confidence Candidate",
        "AKShare Tencent Trusted Candidate",
        "Eastmoney-backed Deferred",
    ]:
        assert_true(marker in html, f"dashboard marker missing: {marker}")
    parse_status = subprocess.check_output(["git", "-C", str(PROJECT_ROOT.parent / "parse_lab"), "status", "--short"], text=True)
    assert_true(parse_status.strip() == "", "parse_lab changed")


def main() -> None:
    test_policy_and_interface_classification()
    test_a_share_recalibration()
    test_dashboard_markers_and_guards()
    print("trust_threshold_recalibration_tests_passed")


if __name__ == "__main__":
    main()
