from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_fund_etf_capital_flow_phase3 import OUTPUT_ROOT, run  # noqa: E402


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


def test_fund_etf_capital_flow_phase3() -> None:
    summary = run()
    official = read_json(OUTPUT_ROOT / "official_universe_acquisition_results.json")
    tiny = read_json(OUTPUT_ROOT / "morningstar_tiny_sample_validation_results.json")
    equity = read_json(OUTPUT_ROOT / "morningstar_equity_stock_validation_phase3.json")
    proxy = read_json(OUTPUT_ROOT / "flow_proxy_v3_results.json")
    coverage = read_json(OUTPUT_ROOT / "coverage_validation_phase3.json")
    trust = read_json(OUTPUT_ROOT / "trust_upgrade_queue_phase3.json")
    dashboard = read_json(PROJECT_ROOT / "runtime" / "authoritative_crawler_framework" / "dashboard_source_status.json")

    assert summary["phase3_completed"] is True
    assert set(summary["official_universe_regions"]) == {"China", "US", "Europe"}
    assert official["large_download_performed"] is False
    assert official["high_frequency_requests"] is False
    assert len(official["regions"]) == 3
    assert tiny["large_morningstar_download_performed"] is False
    assert tiny["no_auto_login"] is True
    assert tiny["no_password_saved"] is True
    assert tiny["token_leaked"] is False
    assert len(tiny["items"]) >= 1
    assert len(equity["markets"]) == 4
    assert proxy["actual_flow_available"] is False
    assert all(row["not_actual_flow_warning"] for row in proxy["items"][:10])
    assert {row["region"] for row in coverage["regions"]} == {"US", "China", "Europe"}
    assert trust["trusted_candidate_count"] == 0
    assert trust["formal_trusted_consumption"] is False
    source = next(item for item in dashboard["sources"] if item["source_id"] == "fund_etf_capital_flow_phase3")
    assert source["status"] == "pilot_completed"
    assert source["candidate_only"] is True
    assert summary["large_morningstar_download_performed"] is False
    assert summary["no_auto_login"] is True
    assert summary["no_password_saved"] is True
    assert summary["token_leaked"] is False
    assert summary["openai_api_called"] is False
    assert summary["formal_trusted_consumption_affected"] is False
    assert_no_token_leak(secret_token())


if __name__ == "__main__":
    test_fund_etf_capital_flow_phase3()
    print("fund ETF capital flow phase3 tests passed.")
