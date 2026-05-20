from __future__ import annotations

import importlib
import importlib.metadata as metadata
import json
import os
import subprocess
import sys
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = PROJECT_ROOT / "config"
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "authoritative_crawler_framework"
DOCS_ROOT = PROJECT_ROOT / "docs"
LOCAL_SECRETS = CONFIG_ROOT / "local_secrets.json"
GITIGNORE = PROJECT_ROOT / ".gitignore"
TOKEN_STATE_PATH = RUNTIME_ROOT / "morningstar_token_state.json"
DEFAULT_TOKEN_EXPIRES_HOURS = 24

REQUIRED_GITIGNORE_RULES = [
    "config/local_secrets.json",
    "**/local_secrets.json",
    "*.key",
    "*.secret",
    ".env.local",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def mask_token(token: str | None) -> str | None:
    if not token:
        return None
    suffix = token[-4:] if len(token) >= 4 else token
    return f"****{suffix}"


def token_fingerprint(token: str | None) -> str | None:
    if not token:
        return None
    return sha256(token.encode("utf-8")).hexdigest()


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def update_token_state(token: str | None, expires_hours: int = DEFAULT_TOKEN_EXPIRES_HOURS) -> dict[str, Any]:
    """Persist token lifecycle metadata without storing the token itself.

    The local secret intentionally remains minimal. A new token is detected by
    sha256 fingerprint change, then the first_seen/expires_at window resets.
    File mtimes are stored for diagnostics only and never used as the sole
    expiry source.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    now_text = now.isoformat().replace("+00:00", "Z")
    existing = read_json(TOKEN_STATE_PATH, default={})
    fingerprint = token_fingerprint(token)
    masked = mask_token(token)

    if not token:
        state = {
            "generated_at": now_text,
            "token_present": False,
            "token_status": "missing",
            "masked_token": None,
            "fingerprint_sha256": None,
            "fingerprint_changed": False,
            "first_seen_at": None,
            "last_seen_at": None,
            "expires_at": None,
            "expires_hours": expires_hours,
            "expiry_source": "fingerprint_state_default_24h",
            "local_secrets_mtime_recorded_for_diagnostics": iso_from_timestamp(LOCAL_SECRETS.stat().st_mtime) if LOCAL_SECRETS.exists() else None,
            "local_secrets_mtime_used_as_expiry_source": False,
            "token_leaked": False,
        }
        write_json(TOKEN_STATE_PATH, state)
        return state

    fingerprint_changed = existing.get("fingerprint_sha256") != fingerprint
    if fingerprint_changed:
        first_seen_at = now_text
        expires_at_dt = now.replace(microsecond=0)
        expires_at = datetime.fromtimestamp(expires_at_dt.timestamp() + expires_hours * 3600, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    else:
        first_seen_at = existing.get("first_seen_at") or now_text
        expires_at = existing.get("expires_at")
        if not expires_at:
            first_dt = parse_utc(first_seen_at) or now
            expires_at = datetime.fromtimestamp(first_dt.timestamp() + expires_hours * 3600, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    expires_dt = parse_utc(expires_at)
    token_status = "expired" if expires_dt and now > expires_dt else "available"
    state = {
        "generated_at": now_text,
        "token_present": True,
        "token_status": token_status,
        "masked_token": masked,
        "fingerprint_sha256": fingerprint,
        "fingerprint_changed": fingerprint_changed,
        "first_seen_at": first_seen_at,
        "last_seen_at": now_text,
        "expires_at": expires_at,
        "expires_hours": expires_hours,
        "expiry_source": "fingerprint_state_default_24h",
        "local_secrets_mtime_recorded_for_diagnostics": iso_from_timestamp(LOCAL_SECRETS.stat().st_mtime) if LOCAL_SECRETS.exists() else None,
        "local_secrets_mtime_used_as_expiry_source": False,
        "token_leaked": False,
    }
    write_json(TOKEN_STATE_PATH, state)
    return state


def sanitize_error(error: BaseException | str, token: str | None) -> str:
    message = str(error)
    if token:
        message = message.replace(token, "[REDACTED_MD_AUTH_TOKEN]")
    return message[:1200]


def run_git_ls_files(path: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", path],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def check_gitignore() -> dict[str, Any]:
    content = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    rules_present = {rule: rule in content for rule in REQUIRED_GITIGNORE_RULES}
    return {
        "gitignore_path": str(GITIGNORE),
        "required_rules_present": rules_present,
        "all_required_rules_present": all(rules_present.values()),
    }


def parse_created_at(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def secret_check() -> dict[str, Any]:
    gitignore = check_gitignore()
    tracked = run_git_ls_files("config/local_secrets.json")
    exists = LOCAL_SECRETS.exists()
    parse_ok = False
    token = None
    json_shape: dict[str, Any] = {}
    error_message = None

    if exists:
        try:
            data = read_json(LOCAL_SECRETS)
            parse_ok = True
            morningstar = data.get("morningstar", {}) if isinstance(data, dict) else {}
            if isinstance(morningstar, dict):
                token = morningstar.get("md_auth_token")
                json_shape = {
                    "morningstar": {
                        "md_auth_token": "present" if token else "missing",
                        "account_hint": "present" if morningstar.get("account_hint") else "missing",
                        "token_created_at": "optional_legacy_present" if morningstar.get("token_created_at") else "optional_not_required",
                        "token_expires_hours": "optional_legacy_present" if morningstar.get("token_expires_hours") else "default_24_not_required",
                    }
                }
        except Exception as exc:  # noqa: BLE001 - this is a diagnostic script
            error_message = sanitize_error(exc, None)

    token_state = update_token_state(token, DEFAULT_TOKEN_EXPIRES_HOURS)
    token_status = token_state.get("token_status", "missing")
    expires_dt = parse_utc(token_state.get("expires_at"))
    token_age_hours = None
    if token_state.get("first_seen_at"):
        first_dt = parse_utc(token_state.get("first_seen_at"))
        if first_dt:
            token_age_hours = round((datetime.now(timezone.utc) - first_dt).total_seconds() / 3600, 2)
    expiry_check = "expired" if token_status == "expired" else "within_expiry_window" if token else "missing"

    result = {
        "generated_at": utc_now(),
        "local_secrets_path": str(LOCAL_SECRETS),
        "local_secrets_exists": exists,
        "local_secrets_parse_ok": parse_ok,
        "local_secrets_git_tracked": bool(tracked),
        "tracked_paths": tracked,
        "gitignore": gitignore,
        "morningstar_field_shape": json_shape,
        "token_present": bool(token),
        "token_status": token_status,
        "masked_token": mask_token(token),
        "local_secrets_minimal_format_supported": True,
        "token_created_at_required": False,
        "token_expires_hours_required": False,
        "token_age_hours": token_age_hours,
        "token_expires_hours": DEFAULT_TOKEN_EXPIRES_HOURS,
        "expiry_check": expiry_check,
        "expires_at": token_state.get("expires_at"),
        "first_seen_at": token_state.get("first_seen_at"),
        "last_seen_at": token_state.get("last_seen_at"),
        "fingerprint_sha256": token_state.get("fingerprint_sha256"),
        "fingerprint_changed": token_state.get("fingerprint_changed"),
        "token_state_path": str(TOKEN_STATE_PATH),
        "expiry_source": token_state.get("expiry_source"),
        "local_secrets_mtime_used_as_expiry_source": False,
        "safe_to_attempt_smoke": bool(token) and token_status == "available" and not tracked,
        "user_action_required": (
            "paste_morningstar_md_auth_token"
            if not token
            else "refresh_expired_token"
            if token_status == "expired"
            else None
        ),
        "no_password_read": True,
        "no_auto_login": True,
        "no_browser_automation": True,
        "token_leaked": False,
        "error_message": error_message,
    }
    write_json(RUNTIME_ROOT / "morningstar_secret_check.json", result)
    return result


def package_check() -> dict[str, Any]:
    install_result = {
        "generated_at": utc_now(),
        "target_python": sys.executable,
        "package_name": "morningstar-data",
        "installed": False,
        "version": None,
        "import_ok": False,
        "error_message": None,
    }
    try:
        install_result["version"] = metadata.version("morningstar-data")
        install_result["installed"] = True
        importlib.import_module("morningstar_data")
        install_result["import_ok"] = True
    except Exception as exc:  # noqa: BLE001
        install_result["error_message"] = sanitize_error(exc, None)
    write_json(RUNTIME_ROOT / "morningstar_package_install_result.json", install_result)
    return install_result


def safe_sample_payload(value: Any, max_items: int = 5) -> Any:
    try:
        if hasattr(value, "head"):
            head = value.head(max_items)
            return {
                "type": type(value).__name__,
                "rows_sampled": len(head),
                "columns": [str(col) for col in list(getattr(head, "columns", []))[:20]],
            }
        if isinstance(value, list):
            return {"type": "list", "count_sampled": min(len(value), max_items), "total_if_known": len(value)}
        if isinstance(value, dict):
            return {"type": "dict", "keys_sampled": list(value.keys())[:20]}
        return {"type": type(value).__name__, "repr_sample": repr(value)[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"type": type(value).__name__, "sample_error": sanitize_error(exc, None)}


def run_smoke(secret: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    data = read_json(LOCAL_SECRETS)
    token = data.get("morningstar", {}).get("md_auth_token") if isinstance(data, dict) else None
    result = {
        "generated_at": utc_now(),
        "smoke_attempted": False,
        "smoke_status": "skipped",
        "skip_reason": None,
        "package_import_ok": package.get("import_ok"),
        "dataset_list": {"attempted": False, "status": "not_attempted"},
        "user_investment_lists": {"attempted": False, "status": "not_attempted"},
        "entitlement_permission_initial_assessment": "not_checked",
        "no_token_persisted": True,
        "token_leaked": False,
        "error_message": None,
    }
    if not package.get("import_ok"):
        result["skip_reason"] = "morningstar_data_import_failed"
        write_json(RUNTIME_ROOT / "morningstar_smoke_test_result.json", result)
        return result
    if not secret.get("safe_to_attempt_smoke"):
        result["skip_reason"] = secret.get("user_action_required") or "token_missing_or_expired_or_tracked"
        write_json(RUNTIME_ROOT / "morningstar_smoke_test_result.json", result)
        return result

    previous = os.environ.get("MD_AUTH_TOKEN")
    os.environ["MD_AUTH_TOKEN"] = token
    result["smoke_attempted"] = True
    try:
        import morningstar_data as md  # type: ignore

        try:
            value = md.direct.get_morningstar_data_sets()
            result["dataset_list"] = {
                "attempted": True,
                "status": "success",
                "sample": safe_sample_payload(value),
            }
        except Exception as exc:  # noqa: BLE001
            message = sanitize_error(exc, token)
            result["dataset_list"] = {
                "attempted": True,
                "status": "failed",
                "error_message": message,
            }

        user_items = getattr(getattr(md, "direct", None), "user_items", None)
        if user_items and hasattr(user_items, "get_investment_lists"):
            try:
                value = user_items.get_investment_lists()
                result["user_investment_lists"] = {
                    "attempted": True,
                    "status": "success",
                    "sample": safe_sample_payload(value),
                }
            except Exception as exc:  # noqa: BLE001
                result["user_investment_lists"] = {
                    "attempted": True,
                    "status": "failed",
                    "error_message": sanitize_error(exc, token),
                }
        else:
            result["user_investment_lists"] = {
                "attempted": False,
                "status": "api_method_unavailable",
            }

        statuses = {result["dataset_list"]["status"], result["user_investment_lists"]["status"]}
        if "success" in statuses:
            result["smoke_status"] = "partial_success" if "failed" in statuses else "success"
            result["entitlement_permission_initial_assessment"] = "at_least_one_small_request_authorized"
        elif any("entitlement" in str(item).lower() or "permission" in str(item).lower() or "unauthor" in str(item).lower() for item in json.dumps(result).split()):
            result["smoke_status"] = "entitlement_error"
            result["entitlement_permission_initial_assessment"] = "entitlement_or_permission_error"
        else:
            result["smoke_status"] = "failed"
            result["entitlement_permission_initial_assessment"] = "request_failed_before_entitlement_confirmed"
    except Exception as exc:  # noqa: BLE001
        result["smoke_status"] = "failed"
        result["error_message"] = sanitize_error(exc, token)
    finally:
        if previous is None:
            os.environ.pop("MD_AUTH_TOKEN", None)
        else:
            os.environ["MD_AUTH_TOKEN"] = previous
    write_json(RUNTIME_ROOT / "morningstar_smoke_test_result.json", result)
    return result


def morningstar_policy(secret: dict[str, Any], package: dict[str, Any], smoke: dict[str, Any]) -> dict[str, Any]:
    token_status = secret.get("token_status", "missing")
    return {
        "source_id": "morningstar_direct",
        "source_name": "Morningstar Direct / Analytics Lab",
        "source_type": "licensed_authorized_platform",
        "access_method": "morningstar_data_python / direct_web_services / api_center",
        "provider_type": "licensed_financial_data_platform",
        "official_source": False,
        "authorized_platform": True,
        "cost_status": "existing_user_account_entitlement_needs_check",
        "crawler_allowed": False,
        "api_allowed": "manual_token_required",
        "token_expiry": "24h",
        "token_status": token_status,
        "redistribution_status": "needs_review",
        "raw_storage_allowed": "needs_user_confirmation",
        "full_backfill_allowed": "no_until_entitlement_review",
        "trust_status": "licensed_source_candidate",
        "consumption_eligibility": "not_formal_trusted_consumption",
        "dashboard_status": {
            "source_gap_status": "manual_token_required" if token_status == "missing" else "entitlement_check_needed",
            "token_status": token_status,
            "last_smoke_test_result": smoke.get("smoke_status"),
            "authorized_source_warning": "Licensed source; do not treat as public free source and do not redistribute without entitlement review.",
        },
        "security_controls": {
            "no_auto_login": True,
            "no_password_saved": True,
            "no_browser_automation": True,
            "manual_copy_authentication_token": True,
            "token_not_logged": True,
        },
        "package": {
            "installed": package.get("installed"),
            "version": package.get("version"),
            "import_ok": package.get("import_ok"),
        },
        "smoke": {
            "attempted": smoke.get("smoke_attempted"),
            "status": smoke.get("smoke_status"),
            "entitlement_assessment": smoke.get("entitlement_permission_initial_assessment"),
        },
    }


def update_policy_file(path: Path, policy: dict[str, Any], policy_type: str) -> dict[str, Any]:
    existing = read_json(path, default={})
    if not existing:
        existing = {"version": "v1", "updated_at": utc_now(), "sources": []}
    sources = existing.get("sources")
    if isinstance(sources, dict):
        sources["morningstar_direct"] = policy
    else:
        if not isinstance(sources, list):
            sources = []
        sources = [item for item in sources if item.get("source_id") != "morningstar_direct"]
        sources.append(policy)
        existing["sources"] = sorted(sources, key=lambda item: item.get("source_id", ""))
    existing["updated_at"] = utc_now()
    existing["policy_type"] = existing.get("policy_type", policy_type)
    write_json(path, existing)
    return existing


def write_policies_and_docs(secret: dict[str, Any], package: dict[str, Any], smoke: dict[str, Any]) -> dict[str, Any]:
    policy = morningstar_policy(secret, package, smoke)
    source_policy = update_policy_file(CONFIG_ROOT / "source_acquisition_policy.json", policy, "source_acquisition")
    third_party_policy = update_policy_file(CONFIG_ROOT / "third_party_source_policy.json", policy, "third_party_source")
    feasibility = {
        "generated_at": utc_now(),
        "morningstar_direct": policy,
        "local_secrets_check_path": str(RUNTIME_ROOT / "morningstar_secret_check.json"),
        "package_install_result_path": str(RUNTIME_ROOT / "morningstar_package_install_result.json"),
        "smoke_test_result_path": str(RUNTIME_ROOT / "morningstar_smoke_test_result.json"),
        "formal_trusted_consumption_affected": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
    }
    write_json(RUNTIME_ROOT / "morningstar_direct_feasibility_audit.json", feasibility)
    write_json(
        RUNTIME_ROOT / "dashboard_source_status.json",
        {
            "generated_at": utc_now(),
            "sources": [
                {
                    "source_id": "morningstar_direct",
                    "display_name": "Morningstar Direct",
                    "status": policy["dashboard_status"]["source_gap_status"],
                    "token_status": policy["dashboard_status"]["token_status"],
                    "last_smoke_test_result": policy["dashboard_status"]["last_smoke_test_result"],
                    "warning": policy["dashboard_status"]["authorized_source_warning"],
                    "licensed_authorized_platform": True,
                }
            ],
        },
    )
    write_morningstar_docs(policy, secret, package, smoke)
    return {
        "source_acquisition_policy": str(CONFIG_ROOT / "source_acquisition_policy.json"),
        "third_party_source_policy": str(CONFIG_ROOT / "third_party_source_policy.json"),
        "source_policy_source_count": len(source_policy.get("sources", [])) if isinstance(source_policy.get("sources"), list) else len(source_policy.get("sources", {})),
        "third_party_policy_source_count": len(third_party_policy.get("sources", [])) if isinstance(third_party_policy.get("sources"), list) else len(third_party_policy.get("sources", {})),
        "feasibility_audit": str(RUNTIME_ROOT / "morningstar_direct_feasibility_audit.json"),
        "dashboard_source_status": str(RUNTIME_ROOT / "dashboard_source_status.json"),
    }


def write_morningstar_docs(policy: dict[str, Any], secret: dict[str, Any], package: dict[str, Any], smoke: dict[str, Any]) -> None:
    audit = f"""# Morningstar Direct Feasibility Audit

Generated at: {utc_now()}

## Scope

Morningstar Direct / Analytics Lab is treated as a licensed authorized platform, not a public free source. This audit validates safe local integration with a user-copied 24-hour authentication token only.

## Security Boundary

- Auto login: no.
- Password storage: no.
- Browser automation: no.
- MFA/SSO bypass: no.
- Token logging: no; only masked token status is recorded.
- Full backfill: no until entitlement and redistribution review.
- Formal trusted consumption: not affected.

## Current Status

- Token status: {secret.get('token_status')}.
- Masked token: {secret.get('masked_token') or 'missing'}.
- Package installed: {package.get('installed')} ({package.get('version') or 'unknown'}).
- Import OK: {package.get('import_ok')}.
- Smoke status: {smoke.get('smoke_status')}.
- Entitlement assessment: {smoke.get('entitlement_permission_initial_assessment')}.

## Source Policy

- source_id: {policy['source_id']}
- source_type: {policy['source_type']}
- access_method: {policy['access_method']}
- api_allowed: {policy['api_allowed']}
- crawler_allowed: {policy['crawler_allowed']}
- token_expiry: {policy['token_expiry']}
- redistribution_status: {policy['redistribution_status']}
- raw_storage_allowed: {policy['raw_storage_allowed']}
- trust_status: {policy['trust_status']}

## Next Gate

Before any raw data storage or larger retrieval, confirm Morningstar entitlement, redistribution limits, and whether local raw storage is allowed for the intended dataset.
"""
    checklist = """# Morningstar User Action Checklist

1. Manually log in to Morningstar Direct or Analytics Lab.
2. Use Morningstar's UI to Copy Authentication Token.
3. Paste the token into `config/local_secrets.json` under `morningstar.md_auth_token`.
4. Optionally keep `morningstar.account_hint` for human context; do not store passwords.
5. Run the Morningstar safe access smoke test from the FinancialResearch backend environment.
6. Token timing is tracked by `runtime/authoritative_crawler_framework/morningstar_token_state.json`.
7. Refresh the token after it expires, normally after 24 hours.
8. Do not write a Morningstar password into any config file.
9. Do not upload `config/local_secrets.json` or token-bearing files to git.
10. Review entitlement and redistribution terms before any large request or raw storage workflow.
"""
    write_text(DOCS_ROOT / "MORNINGSTAR_DIRECT_FEASIBILITY_AUDIT.md", audit)
    write_text(DOCS_ROOT / "MORNINGSTAR_USER_ACTION_CHECKLIST.md", checklist)


def run() -> dict[str, Any]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    secret = secret_check()
    if secret.get("local_secrets_git_tracked"):
        package = package_check()
        smoke = {
            "generated_at": utc_now(),
            "smoke_attempted": False,
            "smoke_status": "blocked",
            "skip_reason": "local_secrets_json_is_git_tracked",
            "entitlement_permission_initial_assessment": "not_checked",
        }
        write_json(RUNTIME_ROOT / "morningstar_smoke_test_result.json", smoke)
    else:
        package = package_check()
        smoke = run_smoke(secret, package)
    policy_outputs = write_policies_and_docs(secret, package, smoke)
    summary = {
        "generated_at": utc_now(),
        "morningstar_safe_access_validation_completed": True,
        "local_secrets_ignored": secret.get("gitignore", {}).get("all_required_rules_present"),
        "local_secrets_untracked": not secret.get("local_secrets_git_tracked"),
        "token_status": secret.get("token_status"),
        "masked_token": secret.get("masked_token"),
        "package": package,
        "smoke": {
            "status": smoke.get("smoke_status"),
            "attempted": smoke.get("smoke_attempted"),
            "entitlement_assessment": smoke.get("entitlement_permission_initial_assessment"),
        },
        "source_policy_updated": True,
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
        "outputs": {
            "secret_check": str(RUNTIME_ROOT / "morningstar_secret_check.json"),
            "package_install_result": str(RUNTIME_ROOT / "morningstar_package_install_result.json"),
            "smoke_test_result": str(RUNTIME_ROOT / "morningstar_smoke_test_result.json"),
            **policy_outputs,
            "docs": [
                str(DOCS_ROOT / "MORNINGSTAR_DIRECT_FEASIBILITY_AUDIT.md"),
                str(DOCS_ROOT / "MORNINGSTAR_USER_ACTION_CHECKLIST.md"),
            ],
        },
    }
    write_json(RUNTIME_ROOT / "morningstar_safe_access_summary.json", summary)
    return summary


if __name__ == "__main__":
    result = run()
    printable = {
        "completed": result["morningstar_safe_access_validation_completed"],
        "token_status": result["token_status"],
        "masked_token": result["masked_token"],
        "package_version": result["package"].get("version"),
        "smoke_status": result["smoke"]["status"],
        "outputs_root": str(RUNTIME_ROOT),
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
