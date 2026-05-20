from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_morningstar_fund_validation import RUNTIME_ROOT, run  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def secret_token() -> str | None:
    path = PROJECT_ROOT / "config" / "local_secrets.json"
    if not path.exists():
        return None
    return read_json(path).get("morningstar", {}).get("md_auth_token")


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


def test_morningstar_fund_validation_outputs() -> None:
    summary = run()
    rules = read_json(PROJECT_ROOT / "config" / "morningstar_fund_trust_rules.json")
    global_audit = read_json(RUNTIME_ROOT / "global_fund_coverage_audit.json")
    china_audit = read_json(RUNTIME_ROOT / "china_fund_authoritative_source_audit.json")
    china_pilot = read_json(RUNTIME_ROOT / "china_fund_coverage_crosscheck_pilot.json")
    use_cases = read_json(RUNTIME_ROOT / "global_fund_flow_use_case_mapping.json")
    trust = read_json(RUNTIME_ROOT / "trust_upgrade_candidates.json")
    dashboard = read_json(PROJECT_ROOT / "runtime" / "authoritative_crawler_framework" / "dashboard_source_status.json")

    levels = {item["level"] for item in rules["trust_levels"]}
    assert "licensed_source_candidate" in levels
    assert "trusted_candidate" in levels
    assert "trusted_by_authorized_license" in levels
    assert global_audit["global_fund_coverage_audit_completed"] is True
    assert global_audit["large_download_performed"] is False
    assert global_audit["candidate_only"] is True
    assert global_audit["dataset_metadata_visible_count"] >= 1
    assert len(china_audit["sources"]) >= 5
    assert {source["trust_role"] for source in china_audit["sources"]}
    assert china_pilot["pilot_status"] == "manual_import_template_generated"
    assert Path(china_pilot["manual_review_template"]).exists()
    assert len(use_cases["items"]) >= 5
    assert use_cases["true_flow_warning"]
    assert trust["trusted_candidate_count"] == 0
    assert trust["formal_trusted_consumption"] is False

    source = next(item for item in dashboard["sources"] if item["source_id"] == "morningstar_direct")
    assert source["status"] == "fund_validation_in_progress"
    assert source["global_fund_coverage_audit_status"] == "completed"
    assert source["china_fund_coverage_pilot_status"] == "manual_import_template_generated"
    assert source["trust_upgrade_candidate_count"] == 0
    assert source["licensed_authorized_platform"] is True

    assert summary["no_auto_login"] is True
    assert summary["no_password_saved"] is True
    assert summary["token_leaked"] is False
    assert summary["large_download_performed"] is False
    assert summary["openai_api_called"] is False
    assert summary["formal_trusted_consumption_affected"] is False
    assert_no_token_leak(secret_token())


if __name__ == "__main__":
    test_morningstar_fund_validation_outputs()
    print("Morningstar fund validation tests passed.")
