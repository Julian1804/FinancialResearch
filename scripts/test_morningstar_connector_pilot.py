from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_morningstar_connector_pilot import PILOT_ROOT  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def secret_token() -> str | None:
    path = PROJECT_ROOT / "config" / "local_secrets.json"
    if not path.exists():
        return None
    data = read_json(path)
    return data.get("morningstar", {}).get("md_auth_token")


def policy_has_morningstar(path: Path) -> bool:
    data = read_json(path)
    sources = data.get("sources", [])
    if isinstance(sources, dict):
        item = sources.get("morningstar_direct")
    else:
        item = next((source for source in sources if source.get("source_id") == "morningstar_direct"), None)
    return bool(
        item
        and item.get("source_type") == "licensed_authorized_platform"
        and item.get("crawler_allowed") is False
        and item.get("api_allowed") == "manual_token_required"
        and item.get("trust_status") == "licensed_source_candidate"
    )


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
        assert token not in text, f"full token leaked in tracked file {rel}"


def test_morningstar_connector_pilot() -> None:
    summary_path = PILOT_ROOT / "morningstar_pilot_summary.json"
    assert summary_path.exists(), "Run scripts/run_morningstar_connector_pilot.py before this artifact test."
    summary = read_json(summary_path)
    token_health = read_json(PILOT_ROOT / "token_health_check.json")
    entitlement = read_json(PILOT_ROOT / "morningstar_dataset_entitlement_map.json")
    taxonomy = read_json(PILOT_ROOT / "morningstar_fr_taxonomy_mapping.json")
    pilot = read_json(PILOT_ROOT / "small_pilot_results.json")
    quality = read_json(PILOT_ROOT / "small_pilot_quality_results.json")
    schema = read_json(PILOT_ROOT / "schema_summary.json")

    assert summary["entitlement_mapping_completed"] is True
    assert token_health["local_secrets_gitignore_ok"] is True
    assert token_health["local_secrets_git_tracked"] is False
    assert token_health["token_present"] is True
    assert token_health["no_auto_login"] is True
    assert token_health["no_password_saved"] is True
    assert token_health["token_leaked"] is False
    assert entitlement["candidate_only"] is True
    assert entitlement["formal_trusted_consumption"] is False
    assert "items" in entitlement
    assert taxonomy["formal_trusted_consumption"] is False
    assert pilot["pilot_completed"] is True
    assert pilot["large_download_performed"] is False
    assert pilot["formal_trusted_consumption"] is False
    assert "items" in quality
    assert "fund_etf_master_schema" in schema["schemas"]
    assert "holdings_schema" in schema["schemas"]
    assert "performance_nav_schema" in schema["schemas"]
    assert policy_has_morningstar(PROJECT_ROOT / "config" / "source_acquisition_policy.json")
    assert policy_has_morningstar(PROJECT_ROOT / "config" / "third_party_source_policy.json")
    assert (PROJECT_ROOT / "docs" / "MORNINGSTAR_DIRECT_ENTITLEMENT_MAPPING_AND_PILOT_REPORT.md").exists()
    assert (PROJECT_ROOT / "docs" / "MORNINGSTAR_CONNECTOR_SCHEMA_V1.md").exists()
    assert (PROJECT_ROOT / "docs" / "LICENSED_DATA_SOURCE_USAGE_POLICY.md").exists()
    assert_no_token_leak(secret_token())


if __name__ == "__main__":
    test_morningstar_connector_pilot()
    print("Morningstar connector pilot tests passed.")
