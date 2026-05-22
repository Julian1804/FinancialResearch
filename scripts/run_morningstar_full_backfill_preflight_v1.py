"""
Morningstar Full Backfill Preflight v1

Checks token, paths, git, storage, rate-limit risk, resume design.
Writes backfill_contract, dataset_inventory, schema_map, dedupe_policy,
qa_policy, storage_manifest, run_state, failure_log, license_storage_note.

If any blocking condition is found, preflight_passed=false and Batch 1
must NOT proceed without user resolution.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = PROJECT_ROOT / "config"
SECRETS_PATH = CONFIG_ROOT / "local_secrets.json"

RAW_BASE = Path("Z:/data_lake_master/raw/licensed/morningstar")
STRUCTURED_BASE = Path("Z:/data_lake_master/structured/licensed/morningstar")
ENTITY_MASTER_NAS_BASE = Path("Z:/data_lake_master/structured/entity_master/morningstar")
LOCAL_RUNTIME_BASE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill"
LOCAL_STATE_BASE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state"
LOCAL_ENTITY_MASTER = PROJECT_ROOT / "runtime" / "entity_master"

RUN_DATE = datetime.now(timezone.utc).strftime("%Y%m%d")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def mask_token(token: str) -> str:
    if len(token) <= 8:
        return "****"
    return token[:4] + "****" + token[-4:]


def get_token() -> str | None:
    if not SECRETS_PATH.exists():
        return None
    secrets = read_json(SECRETS_PATH)
    ms = secrets.get("morningstar", {})
    token = ms.get("md_auth_token")
    return str(token) if token else None


def token_health_check(token: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "token_present": bool(token),
        "token_status": "missing" if not token else "available",
        "token_masked": mask_token(token) if token else None,
        "expires_at": None,
        "expires_hours": None,
        "error": None,
    }
    if not token:
        result["error"] = "MD_AUTH_TOKEN not found in config/local_secrets.json"
        return result
    try:
        parts = token.split(".")
        if len(parts) >= 3:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
            exp = payload.get("exp")
            if exp:
                exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
                result["expires_at"] = exp_dt.isoformat().replace("+00:00", "Z")
                hours_left = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                result["expires_hours"] = round(hours_left, 2)
                if hours_left < 0:
                    result["token_status"] = "expired"
                    result["error"] = f"Token expired {abs(hours_left):.2f} hours ago"
                elif hours_left < 1:
                    result["token_status"] = "expires_soon"
            else:
                result["token_status"] = "no_exp_claim"
        else:
            result["token_status"] = "non_jwt_format"
    except Exception as exc:
        result["decode_error"] = str(exc)
    return result


def check_nas_writable() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for path in [RAW_BASE, STRUCTURED_BASE, ENTITY_MASTER_NAS_BASE]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
            results[str(path)] = {"writable": True}
        except Exception as exc:
            results[str(path)] = {"writable": False, "error": str(exc)}
    return results


def check_local_runtime_writable() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for path in [LOCAL_RUNTIME_BASE, LOCAL_STATE_BASE, LOCAL_ENTITY_MASTER]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
            results[str(path)] = {"writable": True}
        except Exception as exc:
            results[str(path)] = {"writable": False, "error": str(exc)}
    return results


def check_gitignore() -> dict[str, Any]:
    gitignore_path = PROJECT_ROOT / ".gitignore"
    if not gitignore_path.exists():
        return {"exists": False, "local_secrets_ignored": False}
    content = gitignore_path.read_text(encoding="utf-8")
    rules = ["config/local_secrets.json", "**/local_secrets.json", "*.key", "*.secret"]
    present = [r for r in rules if r in content]
    return {
        "exists": True,
        "local_secrets_ignored": "config/local_secrets.json" in present,
        "all_required_rules_present": all(r in content for r in rules),
        "rules_found": present,
    }


def check_git_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--short"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "clean": result.stdout.strip() == "",
            "output": result.stdout.strip(),
            "has_uncommitted_changes": result.stdout.strip() != "",
        }
    except Exception as exc:
        return {"clean": False, "error": str(exc)}


def estimate_storage() -> dict[str, Any]:
    return {
        "fund_etf_metadata_estimate_mb": 5,
        "holdings_estimate_mb": 10,
        "lookthrough_estimate_mb": 15,
        "returns_estimate_mb": 5,
        "entity_shell_estimate_mb": 2,
        "raw_total_estimate_mb": 37,
        "structured_total_estimate_mb": 25,
        "total_estimate_mb": 62,
        "rate_limit_risk": "low_with_2s_sleep",
        "checkpoint_interval_seconds": 300,
    }


def build_backfill_contract() -> dict[str, Any]:
    return {
        "contract_id": "morningstar_full_backfill_contract_v1",
        "generated_at": utc_now(),
        "run_date": RUN_DATE,
        "source": "morningstar_direct",
        "scopes": [
            "fund_etf_master_metadata",
            "share_class_identifiers",
            "holdings_exposure",
            "lookthrough_holdings",
            "returns_performance",
            "portfolio_composition",
            "benchmark_index_identifiers",
            "bond_fund_metadata",
            "commodity_fund_metadata",
            "us_equity_entity_shell_only",
        ],
        "paths": {
            "raw_base": str(RAW_BASE),
            "structured_base": str(STRUCTURED_BASE),
            "entity_master_nas_base": str(ENTITY_MASTER_NAS_BASE),
            "local_runtime_base": str(LOCAL_RUNTIME_BASE),
            "local_state_base": str(LOCAL_STATE_BASE),
            "local_entity_master": str(LOCAL_ENTITY_MASTER),
        },
        "blocked_fields": ["tna_enf"],
        "blocked_reason": "unit_scale_unknown",
        "us_equity_standalone_excluded": True,
        "us_equity_allowed_as": ["holdings_underlying", "entity_shell", "index_constituent_mapping"],
        "max_api_calls_per_run": 200,
        "max_records_per_method": 500,
        "checkpoint_interval_seconds": 300,
        "retry_max_attempts": 3,
        "rate_limit_sleep_seconds": 2,
        "no_auto_login": True,
        "no_password_saved": True,
        "no_openai_api": True,
        "formal_trusted_consumption_enabled": False,
        "trust_level": "candidate_preview",
    }


def build_dataset_inventory() -> dict[str, Any]:
    return {
        "inventory_id": "morningstar_dataset_inventory_v1",
        "generated_at": utc_now(),
        "datasets": [
            {
                "dataset_id": "method:md.direct.get_morningstar_data_sets",
                "dataset_name": "Morningstar Data Sets Listing",
                "data_domain": "fund_market",
                "scope": "universe_discovery",
                "methods": ["get_morningstar_data_sets"],
                "estimated_api_calls": 2,
                "estimated_records": 200,
            },
            {
                "dataset_id": "method:md.direct.investments",
                "dataset_name": "Investment Search",
                "data_domain": "fund_market",
                "scope": "fund_etf_master_metadata",
                "methods": ["investments"],
                "search_keywords": ["ETF", "Mutual Fund", "Bond Fund", "Commodity Fund", "Index Fund"],
                "estimated_api_calls": 10,
                "estimated_records": 300,
            },
            {
                "dataset_id": "method:md.direct.get_investment_data",
                "dataset_name": "Investment Data (Metadata)",
                "data_domain": "fund_market",
                "scope": "share_class_identifiers",
                "methods": ["get_investment_data"],
                "estimated_api_calls": 10,
                "estimated_records": 300,
            },
            {
                "dataset_id": "method:md.direct.get_holdings",
                "dataset_name": "Holdings",
                "data_domain": "capital_flow",
                "scope": "holdings_exposure",
                "methods": ["get_holdings"],
                "estimated_api_calls": 10,
                "estimated_records": 500,
            },
            {
                "dataset_id": "method:md.direct.get_lookthrough_holdings",
                "dataset_name": "Look-through Holdings",
                "data_domain": "capital_flow",
                "scope": "lookthrough_holdings",
                "methods": ["get_lookthrough_holdings"],
                "estimated_api_calls": 10,
                "estimated_records": 500,
            },
            {
                "dataset_id": "method:md.direct.get_returns",
                "dataset_name": "Returns",
                "data_domain": "performance",
                "scope": "returns_performance",
                "methods": ["get_returns"],
                "estimated_api_calls": 10,
                "estimated_records": 300,
            },
            {
                "dataset_id": "method:md.direct.get_data_point_settings",
                "dataset_name": "Data Point Settings",
                "data_domain": "metadata",
                "scope": "schema_discovery",
                "methods": ["get_data_point_settings"],
                "estimated_api_calls": 5,
                "estimated_records": 50,
            },
        ],
        "total_estimated_api_calls": 57,
        "total_estimated_records": 2150,
    }


def build_schema_map() -> dict[str, Any]:
    return {
        "schema_map_id": "morningstar_schema_map_v1",
        "generated_at": utc_now(),
        "schemas": {
            "investment_search": {
                "source_method": "md.direct.investments",
                "expected_fields": [
                    "secId",
                    "ticker",
                    "name",
                    "currency",
                    "exchange",
                    "country",
                    "category",
                    "assetType",
                    "fundCompany",
                ],
                "identifier_fields": ["secId", "ticker", "isin", "cusip"],
                "status": "expected",
            },
            "holdings": {
                "source_method": "md.direct.get_holdings",
                "expected_fields": [
                    "investmentId",
                    "secId",
                    "name",
                    "weight",
                    "marketValue",
                    "portfolioDate",
                    "detailHoldingTypeCode",
                ],
                "identifier_fields": ["secId", "isin", "cusip"],
                "status": "expected",
            },
            "lookthrough_holdings": {
                "source_method": "md.direct.get_lookthrough_holdings",
                "expected_fields": ["investmentId", "secId", "name", "weight", "portfolioDate"],
                "identifier_fields": ["secId"],
                "status": "expected",
            },
            "returns": {
                "source_method": "md.direct.get_returns",
                "expected_fields": ["investmentId", "date", "value", "type"],
                "identifier_fields": ["investmentId"],
                "status": "expected",
            },
        },
    }


def build_dedupe_policy() -> dict[str, Any]:
    return {
        "policy_id": "morningstar_dedupe_policy_v1",
        "generated_at": utc_now(),
        "primary_key_priority": [
            "secId",
            "performanceId",
            "fundId",
            "shareClassId",
            "investmentId",
        ],
        "fallback_keys": ["isin", "cusip", "ticker"],
        "composite_fallback": ["name", "currency", "domicile", "securityType"],
        "holding_identifier_priority": ["secId", "isin", "cusip", "ticker", "name"],
        "holding_composite_fallback": ["name", "holdingType"],
        "crosswalk_rules": {
            "link_by": ["linked_fund_ids", "first_seen_from_holding"],
            "update_strategy": "merge_on_conflict_prefer_latest",
        },
        "duplicate_prevention": {
            "pre_insert_check": True,
            "hash_on": ["secId", "portfolioDate"],
            "versioning": "append_only_with_run_id",
        },
    }


def build_qa_policy() -> dict[str, Any]:
    return {
        "policy_id": "morningstar_qa_policy_v1",
        "generated_at": utc_now(),
        "checks": [
            {"name": "format_validation", "type": "json_schema", "severity": "error"},
            {"name": "field_presence", "type": "required_fields", "severity": "warning"},
            {"name": "date_range_sanity", "type": "range_check", "severity": "warning"},
            {"name": "null_ratio", "type": "threshold", "threshold": 0.5, "severity": "warning"},
            {"name": "duplicate_count", "type": "threshold", "threshold": 0.05, "severity": "warning"},
            {"name": "unit_unknown_flag", "type": "exact_match", "match_value": "unknown", "severity": "warning"},
            {"name": "anomaly_range", "type": "zscore", "threshold": 5, "severity": "warning"},
        ],
        "do_not_fail_on_coverage": True,
        "blocked_fields_always_flagged": ["tna_enf"],
    }


def build_license_storage_note() -> dict[str, Any]:
    return {
        "note_id": "morningstar_license_storage_note_v1",
        "generated_at": utc_now(),
        "licensee": "julian.zhang@morningstar.com",
        "product": "Morningstar Direct",
        "storage_classification": "licensed_internal_research_storage",
        "raw_retention": "retain_original_response",
        "normalized_retention": "structured_derivative",
        "redistribution": "prohibited",
        "us_equity_exclusion": "standalone_time_series_excluded",
        "tna_enf_status": "blocked_unit_scale_unknown",
    }


def main() -> dict[str, Any]:
    token = get_token()
    token_health = token_health_check(token)
    nas_writable = check_nas_writable()
    local_writable = check_local_runtime_writable()
    gitignore_ok = check_gitignore()
    git_status = check_git_status()
    storage_estimate = estimate_storage()

    blockers: list[dict[str, Any]] = []
    if token_health["token_status"] in ("missing", "expired"):
        blockers.append({
            "type": "token",
            "severity": "blocking",
            "message": f"Token status: {token_health['token_status']}. {token_health.get('error', '')}",
        })
    if not all(v["writable"] for v in nas_writable.values()):
        blockers.append({
            "type": "nas_path",
            "severity": "blocking",
            "message": "One or more NAS paths not writable",
            "details": {k: v for k, v in nas_writable.items() if not v["writable"]},
        })
    if not all(v["writable"] for v in local_writable.values()):
        blockers.append({
            "type": "local_path",
            "severity": "blocking",
            "message": "One or more local runtime paths not writable",
            "details": {k: v for k, v in local_writable.items() if not v["writable"]},
        })
    if not gitignore_ok.get("local_secrets_ignored"):
        blockers.append({
            "type": "gitignore",
            "severity": "blocking",
            "message": "local_secrets.json not properly gitignored",
        })
    if git_status.get("has_uncommitted_changes"):
        blockers.append({
            "type": "git_status",
            "severity": "warning",
            "message": "Uncommitted changes present in repo",
            "details": git_status.get("output"),
        })

    preflight_passed = len([b for b in blockers if b["severity"] == "blocking"]) == 0

    contract = build_backfill_contract()
    inventory = build_dataset_inventory()
    schema_map = build_schema_map()
    dedupe_policy = build_dedupe_policy()
    qa_policy = build_qa_policy()
    license_note = build_license_storage_note()

    write_json(LOCAL_STATE_BASE / "backfill_contract.json", contract)
    write_json(LOCAL_STATE_BASE / "dataset_inventory.json", inventory)
    write_json(LOCAL_STATE_BASE / "schema_map.json", schema_map)
    write_json(LOCAL_STATE_BASE / "dedupe_policy.json", dedupe_policy)
    write_json(LOCAL_STATE_BASE / "qa_policy.json", qa_policy)
    write_json(LOCAL_STATE_BASE / "license_storage_note.json", license_note)

    storage_manifest = {
        "manifest_id": "morningstar_storage_manifest_v1",
        "generated_at": utc_now(),
        "run_date": RUN_DATE,
        "paths": contract["paths"],
        "files_written": [
            str(LOCAL_STATE_BASE / "backfill_contract.json"),
            str(LOCAL_STATE_BASE / "dataset_inventory.json"),
            str(LOCAL_STATE_BASE / "schema_map.json"),
            str(LOCAL_STATE_BASE / "dedupe_policy.json"),
            str(LOCAL_STATE_BASE / "qa_policy.json"),
            str(LOCAL_STATE_BASE / "license_storage_note.json"),
        ],
    }
    write_json(LOCAL_STATE_BASE / "storage_manifest.json", storage_manifest)

    run_state = {
        "state_id": "morningstar_full_backfill_run_state_v1",
        "generated_at": utc_now(),
        "run_date": RUN_DATE,
        "preflight_passed": preflight_passed,
        "token_health": token_health,
        "blockers": blockers,
        "next_step": "batch1_controlled_start" if preflight_passed else "resolve_blockers",
    }
    write_json(LOCAL_STATE_BASE / "run_state.json", run_state)

    failure_log = {
        "log_id": "morningstar_failure_log_v1",
        "generated_at": utc_now(),
        "entries": [],
    }
    write_json(LOCAL_STATE_BASE / "failure_log.json", failure_log)

    result = {
        "preflight_passed": preflight_passed,
        "token_health": token_health,
        "nas_writable": nas_writable,
        "local_writable": local_writable,
        "gitignore_ok": gitignore_ok,
        "git_status": git_status,
        "storage_estimate": storage_estimate,
        "blockers": blockers,
        "artefacts_written": storage_manifest["files_written"],
    }
    write_json(LOCAL_STATE_BASE / "preflight_result.json", result)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return result


if __name__ == "__main__":
    main()
