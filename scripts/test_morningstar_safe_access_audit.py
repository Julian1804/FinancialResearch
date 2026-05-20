from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_morningstar_safe_access_audit import LOCAL_SECRETS, RUNTIME_ROOT, run  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_secret_token() -> str | None:
    if not LOCAL_SECRETS.exists():
        return None
    payload = read_json(LOCAL_SECRETS)
    morningstar = payload.get("morningstar", {})
    if isinstance(morningstar, dict):
        return morningstar.get("md_auth_token")
    return None


def assert_no_full_token_in_outputs(token: str | None) -> None:
    if not token:
        return
    for path in RUNTIME_ROOT.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert token not in text, f"full token leaked in {path}"


def test_morningstar_safe_access_audit() -> None:
    summary = run()
    secret = read_json(RUNTIME_ROOT / "morningstar_secret_check.json")
    package = read_json(RUNTIME_ROOT / "morningstar_package_install_result.json")
    smoke = read_json(RUNTIME_ROOT / "morningstar_smoke_test_result.json")
    feasibility = read_json(RUNTIME_ROOT / "morningstar_direct_feasibility_audit.json")
    source_policy = read_json(PROJECT_ROOT / "config" / "source_acquisition_policy.json")
    third_party_policy = read_json(PROJECT_ROOT / "config" / "third_party_source_policy.json")

    assert summary["morningstar_safe_access_validation_completed"] is True
    assert secret["gitignore"]["all_required_rules_present"] is True
    assert secret["local_secrets_git_tracked"] is False
    assert secret["no_auto_login"] is True
    assert secret["no_password_read"] is True
    assert secret["token_leaked"] is False
    assert package["installed"] is True
    assert package["import_ok"] is True
    assert smoke["no_token_persisted"] is True
    assert feasibility["morningstar_direct"]["source_type"] == "licensed_authorized_platform"
    assert feasibility["morningstar_direct"]["crawler_allowed"] is False
    assert feasibility["morningstar_direct"]["api_allowed"] == "manual_token_required"
    assert feasibility["formal_trusted_consumption_affected"] is False
    assert feasibility["openai_api_called"] is False
    assert feasibility["parse_lab_affected"] is False

    def has_morningstar(policy: dict) -> bool:
        sources = policy.get("sources", [])
        if isinstance(sources, dict):
            return "morningstar_direct" in sources
        return any(item.get("source_id") == "morningstar_direct" for item in sources)

    assert has_morningstar(source_policy)
    assert has_morningstar(third_party_policy)
    assert (PROJECT_ROOT / "docs" / "MORNINGSTAR_DIRECT_FEASIBILITY_AUDIT.md").exists()
    assert (PROJECT_ROOT / "docs" / "MORNINGSTAR_USER_ACTION_CHECKLIST.md").exists()
    assert_no_full_token_in_outputs(load_secret_token())


if __name__ == "__main__":
    test_morningstar_safe_access_audit()
    print("Morningstar safe access audit tests passed.")
