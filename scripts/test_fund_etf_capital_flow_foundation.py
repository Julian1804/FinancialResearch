from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_fund_etf_capital_flow_foundation import RUNTIME_ROOT, TEMPLATE_ROOT, run  # noqa: E402
from scripts.run_fund_etf_manual_import import validate_import  # noqa: E402


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


def test_fund_etf_capital_flow_foundation() -> None:
    summary = run()
    taxonomy = read_json(PROJECT_ROOT / "config" / "fund_etf_taxonomy.json")
    schema = read_json(RUNTIME_ROOT / "fund_etf_schema_summary.json")
    matching = read_json(RUNTIME_ROOT / "morningstar_matching_framework.json")
    coverage = read_json(RUNTIME_ROOT / "fund_coverage_validation_results.json")
    shortlist = read_json(RUNTIME_ROOT / "morningstar_priority_dataset_shortlist.json")
    trust_queue = read_json(RUNTIME_ROOT / "trust_upgrade_queue.json")
    dashboard = read_json(PROJECT_ROOT / "runtime" / "authoritative_crawler_framework" / "dashboard_source_status.json")

    assert summary["fund_etf_capital_flow_foundation_completed"] is True
    assert summary["manual_import_framework_completed"] is True
    assert summary["trusted_candidate_count"] == 0
    assert summary["large_download_performed"] is False
    assert summary["openai_api_called"] is False
    assert summary["formal_trusted_consumption_affected"] is False
    assert {"volume", "amount", "aum_change", "holdings_change"}.issubset(set(taxonomy["flow_proxy_types"]))
    assert "fund_master" in schema["schemas"]
    assert "flow_proxy" in schema["schemas"]
    for name in summary["import_templates"]:
        assert (TEMPLATE_ROOT / name).exists()

    validation = validate_import(TEMPLATE_ROOT / "china_public_fund_official_list_template.csv", "china_public_fund_official_list_template.csv")
    assert validation["row_count"] == 1
    assert validation["quality_status"] == "quality_failed"
    assert matching["sample_mode"] == "schema_test_only_until_official_import_available"
    assert coverage["trust_upgrade_status"] == "not_eligible_no_official_import"
    assert coverage["coverage_ratio"] is None
    assert len(shortlist["items"]) >= 1
    assert trust_queue["trusted_candidate_count"] == 0
    assert all(item["can_upgrade_to_trusted_candidate"] is False for item in trust_queue["queue"])
    status = next(item for item in dashboard["sources"] if item["source_id"] == "fund_etf_capital_flow_foundation")
    assert status["status"] == "manual_import_ready"
    assert status["candidate_only"] is True
    assert_no_token_leak(secret_token())


if __name__ == "__main__":
    test_fund_etf_capital_flow_foundation()
    print("fund ETF capital flow foundation tests passed.")
