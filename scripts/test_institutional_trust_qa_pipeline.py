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


def test_policy_and_states() -> None:
    policy = read_json(PROJECT_ROOT / "config" / "institutional_data_source_trust_policy.json")
    assert_true("institutional_database" in policy["source_type_taxonomy"], "institutional_database source type missing")
    assert_true(policy["morningstar_treatment"]["source_type"] == "licensed_institutional_source", "Morningstar treatment not licensed institutional")

    promotion = read_json(PROJECT_ROOT / "config" / "candidate_promotion_rules.json")
    states = {item["status"] for item in promotion["states"]}
    for status in [
        "institutional_high_confidence_candidate",
        "licensed_high_confidence_candidate",
        "production_candidate",
        "media_event_candidate",
        "anomaly_flagged_candidate",
    ]:
        assert_true(status in states, f"candidate state missing: {status}")

    strategy = read_json(PROJECT_ROOT / "config" / "automated_source_strategy.json")
    source_types = {item["source_id"]: item["source_type"] for item in strategy["sources"]}
    assert_true(source_types["morningstar_direct"] == "licensed_institutional_source", "Morningstar source type not updated")
    assert_true(source_types["baostock"] == "open_source_api_wrapper", "Baostock source type not updated")
    assert_true(source_types["akshare_tencent"] == "open_source_api_wrapper", "AKShare Tencent source type not updated")
    assert_true(source_types["wind_terminal"] == "licensed_institutional_source", "Wind placeholder source missing")


def test_qa_proof() -> None:
    root = PROJECT_ROOT / "runtime" / "automated_ingestion_system" / "institutional_trust_qa_pipeline"
    summary = read_json(root / "institutional_trust_qa_pipeline_summary.json")
    assert_true(summary["institutional_policy_adjustment_completed"] is True, "summary completion missing")
    assert_true(summary["formal_trusted_consumption_affected"] is False, "trusted consumption must stay untouched")
    assert_true(summary["no_auto_login_morningstar"] is True, "Morningstar auto login must be false")
    assert_true(summary["token_leaked"] is False, "token leaked flag must be false")

    proof = read_json(root / "controlled_proof_run_results.json")
    sources = set(proof["source_summaries"].keys())
    for source_id in ["morningstar_direct", "baostock_daily", "akshare_tencent_daily", "fred_public_api"]:
        assert_true(source_id in sources, f"proof source missing: {source_id}")
    assert_true(proof["qa_summary"]["failed_count"] == 0, "controlled proof should not have failed QA")
    assert_true(proof["candidate_status_summary"].get("production_candidate", 0) >= 1, "production_candidate not assigned")
    assert_true(proof["candidate_status_summary"].get("licensed_high_confidence_candidate", 0) >= 1, "licensed high confidence status not assigned")

    serialized = json.dumps(proof, ensure_ascii=False).lower()
    for forbidden in ["md_auth_token", "pwqa"]:
        assert_true(forbidden not in serialized, f"token marker leaked: {forbidden}")


def test_dashboard_markers() -> None:
    html = (PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "Institutional Data Source Trust Policy",
        "Automated QA Pipeline",
        "Production Candidate Backfill",
        "Institutional High Confidence Candidate",
        "Media Event Candidate",
        "Anomaly Flagged Candidate",
    ]:
        assert_true(marker in html, f"dashboard marker missing: {marker}")


def test_repo_guards() -> None:
    parse_status = subprocess.check_output(["git", "-C", str(PROJECT_ROOT.parent / "parse_lab"), "status", "--short"], text=True)
    assert_true(parse_status.strip() == "", "parse_lab worktree changed")


def main() -> None:
    test_policy_and_states()
    test_qa_proof()
    test_dashboard_markers()
    test_repo_guards()
    print("institutional_trust_qa_pipeline_tests_passed")


if __name__ == "__main__":
    main()
