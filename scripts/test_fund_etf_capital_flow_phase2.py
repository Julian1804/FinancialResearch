from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_fund_etf_capital_flow_phase2 import OUTPUT_ROOT, run  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def secret_token() -> str | None:
    secret = PROJECT_ROOT / "config" / "local_secrets.json"
    if not secret.exists():
        return None
    return read_json(secret).get("morningstar", {}).get("md_auth_token")


def assert_no_token_leak(token: str | None) -> None:
    if not token:
        return
    tracked = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    for rel in tracked:
        if rel == "config/local_secrets.json":
            continue
        path = PROJECT_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        assert token not in text, f"full Morningstar token leaked in tracked file {rel}"


def test_fund_etf_capital_flow_phase2() -> None:
    summary = run()
    audit = read_json(OUTPUT_ROOT / "official_fund_universe_source_audit.json")
    official = read_json(OUTPUT_ROOT / "official_fund_universe_ingestion_results.json")
    etf = read_json(OUTPUT_ROOT / "etf_market_data_ingestion_results.json")
    schema = read_json(OUTPUT_ROOT / "fund_flow_signal_schema_summary.json")
    classification = read_json(OUTPUT_ROOT / "morningstar_dataset_universe_classification_v2.json")
    multiregion = read_json(OUTPUT_ROOT / "morningstar_multiregion_fund_coverage_validation.json")
    equity = read_json(OUTPUT_ROOT / "morningstar_equity_stock_validation.json")
    other = read_json(OUTPUT_ROOT / "morningstar_other_dataset_validation_framework.json")
    proxy = read_json(OUTPUT_ROOT / "flow_proxy_v2_results.json")
    trust = read_json(OUTPUT_ROOT / "morningstar_multi_asset_trust_upgrade_queue.json")
    dashboard = read_json(PROJECT_ROOT / "runtime" / "authoritative_crawler_framework" / "dashboard_source_status.json")

    assert summary["phase2_completed"] is True
    assert summary["official_source_audit_completed"] is True
    assert len(audit["sources"]) >= 10
    assert official["connector_status"] == "manual_fallback_ready"
    assert etf["candidate_only"] is True
    assert etf["record_count"] >= 0
    assert "flow_proxy" in schema["schemas"]
    assert classification["classification_only_no_coverage_inference"] is True
    assert len(classification["items"]) >= 1
    assert {row["region"] for row in multiregion["regions"]} == {"US", "China", "Europe"}
    assert all(row["validation_status"] == "blocked" for row in multiregion["regions"])
    assert equity["large_download_performed"] is False
    assert len(equity["markets"]) == 4
    assert len(other["items"]) >= 5
    assert proxy["actual_flow_available"] is False
    assert trust["trusted_candidate_count"] == 0
    assert trust["formal_trusted_consumption"] is False
    source = next(item for item in dashboard["sources"] if item["source_id"] == "fund_etf_capital_flow_phase2")
    assert source["status"] == "validation_framework_ready"
    assert source["candidate_only"] is True
    assert summary["large_morningstar_download_performed"] is False
    assert summary["no_auto_login"] is True
    assert summary["no_password_saved"] is True
    assert summary["token_leaked"] is False
    assert summary["openai_api_called"] is False
    assert summary["formal_trusted_consumption_affected"] is False
    assert_no_token_leak(secret_token())


if __name__ == "__main__":
    test_fund_etf_capital_flow_phase2()
    print("fund ETF capital flow phase2 tests passed.")
