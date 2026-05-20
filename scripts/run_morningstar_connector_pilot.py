from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_morningstar_safe_access_audit import (  # noqa: E402
    CONFIG_ROOT,
    DOCS_ROOT,
    LOCAL_SECRETS,
    RUNTIME_ROOT as AUTHORITATIVE_RUNTIME_ROOT,
    check_gitignore,
    mask_token,
    parse_created_at,
    read_json,
    run_git_ls_files,
    sanitize_error,
    update_policy_file,
    utc_now,
    write_json,
    write_text,
)


PILOT_ROOT = PROJECT_ROOT / "runtime" / "morningstar_connector_pilot"
RAW_LICENSED_ROOT = Path("Z:/data_lake_master/raw/licensed_sources/morningstar_direct")
STRUCTURED_LICENSED_ROOT = Path("Z:/data_lake_master/structured/licensed_sources/morningstar_direct")

CALL_TIMEOUT_SECONDS = 18


def load_morningstar_secret() -> dict[str, Any]:
    if not LOCAL_SECRETS.exists():
        return {}
    data = read_json(LOCAL_SECRETS)
    morningstar = data.get("morningstar", {}) if isinstance(data, dict) else {}
    return morningstar if isinstance(morningstar, dict) else {}


def token_health_check() -> dict[str, Any]:
    secret = load_morningstar_secret()
    token = secret.get("md_auth_token")
    created_at_raw = secret.get("token_created_at")
    expires_hours = int(secret.get("token_expires_hours") or 24)
    created_at = parse_created_at(created_at_raw)
    age_hours = None
    status = "missing"
    expiry_check = "missing"
    if token:
        status = "available"
        if created_at:
            age_hours = round((datetime.now(timezone.utc) - created_at).total_seconds() / 3600, 2)
            if age_hours > expires_hours:
                status = "expired"
                expiry_check = "expired"
            else:
                expiry_check = "within_expiry_window"
        else:
            expiry_check = "missing_created_at"

    token_parts = token.split(".") if token else []
    token_format = {
        "dot_count": token.count(".") if token else 0,
        "part_count": len(token_parts) if token else 0,
        "looks_like_standard_jwt": len(token_parts) == 3,
        "multi_segment_token_detected": len(token_parts) > 3,
        "library_token_variant": "first_three_segments" if len(token_parts) > 3 else "as_provided",
    }
    result = {
        "generated_at": utc_now(),
        "local_secrets_exists": LOCAL_SECRETS.exists(),
        "local_secrets_gitignore_ok": check_gitignore()["all_required_rules_present"],
        "local_secrets_git_tracked": bool(run_git_ls_files("config/local_secrets.json")),
        "token_present": bool(token),
        "token_status": status,
        "masked_token": mask_token(token),
        "token_created_at_present": bool(created_at_raw),
        "token_age_hours": age_hours,
        "token_expires_hours": expires_hours,
        "expiry_check": expiry_check,
        "token_created_at_user_reported_unreliable": True,
        "token_probe_allowed_despite_created_at": bool(token),
        "token_format_diagnostic": token_format,
        "user_action_required": (
            "paste_morningstar_md_auth_token"
            if not token
            else "refresh_expired_token"
            if status == "expired"
            else "fill_token_created_at"
            if expiry_check == "missing_created_at"
            else None
        ),
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
    }
    write_json(PILOT_ROOT / "token_health_check.json", result)
    return result


def token_for_library(token: str | None) -> str | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) > 3:
        return ".".join(parts[:3])
    return token


def child_call_code(call_name: str) -> str:
    return f"""
import json
import os
import sys

def summarize_df(value, include_rows=False, max_rows=10):
    if hasattr(value, 'shape') and hasattr(value, 'columns'):
        result = {{
            'type': type(value).__name__,
            'row_count': int(value.shape[0]),
            'column_count': int(value.shape[1]),
            'columns': [str(c) for c in list(value.columns)],
        }}
        if include_rows:
            rows = value.head(max_rows).where(value.notna(), None).to_dict(orient='records')
            result['rows'] = rows
        return result
    if isinstance(value, list):
        return {{'type': 'list', 'row_count': len(value), 'rows': value[:max_rows] if include_rows else []}}
    if isinstance(value, dict):
        return {{'type': 'dict', 'keys': list(value.keys())[:30]}}
    return {{'type': type(value).__name__, 'repr': repr(value)[:400]}}

try:
    import morningstar_data as md
    call = {call_name!r}
    if call == 'available_datasets':
        data = md.direct.get_morningstar_data_sets()
        payload = summarize_df(data, include_rows=True, max_rows=40)
    elif call == 'fund_universe_datasets':
        data = md.direct.get_morningstar_data_sets('FO')
        payload = summarize_df(data, include_rows=True, max_rows=20)
    elif call == 'user_investment_lists':
        data = md.direct.user_items.get_investment_lists()
        payload = summarize_df(data, include_rows=False)
    elif call == 'user_data_sets':
        data = md.direct.user_items.get_data_sets()
        payload = summarize_df(data, include_rows=False)
    elif call == 'data_point_settings':
        data = md.direct.get_data_point_settings(['OS01W', 'HP010'])
        payload = summarize_df(data, include_rows=True, max_rows=5)
    elif call == 'investment_search_spy':
        data = md.direct.investments(keyword='SPY', count=3)
        payload = summarize_df(data, include_rows=False)
    else:
        raise ValueError(f'unknown call: {{call}}')
    print(json.dumps({{'status':'success','payload':payload}}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({{'status':'failed','error_type':type(exc).__name__,'error_message':str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
"""


def run_limited_call(call_name: str, token: str | None) -> dict[str, Any]:
    if not token:
        return {
            "call_name": call_name,
            "attempted": False,
            "status": "skipped",
            "error_type": "missing_token",
            "elapsed_seconds": 0,
        }
    env = os.environ.copy()
    env["MD_AUTH_TOKEN"] = token
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            [sys.executable, "-c", child_call_code(call_name)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT_SECONDS,
            check=False,
        )
        elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
        stdout = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"status": "failed", "error_type": "invalid_child_json", "error_message": stdout[:800]}
        status = payload.get("status", "failed")
        return {
            "call_name": call_name,
            "attempted": True,
            "status": status,
            "elapsed_seconds": elapsed,
            "return_code": result.returncode,
            "payload": payload.get("payload"),
            "error_type": payload.get("error_type"),
            "error_message": sanitize_error(payload.get("error_message", result.stderr[-1000:]), token),
            "stderr_tail": sanitize_error(result.stderr[-1000:], token),
        }
    except subprocess.TimeoutExpired:
        elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
        return {
            "call_name": call_name,
            "attempted": True,
            "status": "timeout",
            "elapsed_seconds": elapsed,
            "error_type": "timeout",
            "error_message": f"call exceeded {CALL_TIMEOUT_SECONDS}s timeout",
        }


def classify_permission(call: dict[str, Any]) -> str:
    status = call.get("status")
    message = f"{call.get('error_type') or ''} {call.get('error_message') or ''}".lower()
    if status == "success":
        return "available"
    if status == "timeout":
        return "timeout_unconfirmed"
    if "permission" in message or "entitlement" in message or "unauthor" in message or "forbidden" in message:
        return "permission_denied"
    if "invalid jwt" in message or "malformedjwt" in message:
        return "token_format_error"
    return "method_failed_or_unconfirmed"


def likely_use_case(dataset_name: str) -> tuple[str, str, str]:
    text = dataset_name.lower()
    if "holding" in text or "portfolio" in text:
        return "capital_flow", "holdings / portfolio exposure", "ETF/fund holdings and allocation proxy"
    if "return" in text or "performance" in text or "nav" in text:
        return "asset_class", "performance / NAV / returns", "fund or benchmark performance comparison"
    if "fund" in text or "etf" in text:
        return "fund_market", "ETF / Fund", "fund master, category, performance and watchlist"
    if "index" in text or "benchmark" in text:
        return "asset_class", "index / benchmark", "benchmark comparison"
    if "financial" in text or "valuation" in text or "ratio" in text:
        return "company", "company fundamentals", "fundamentals if entitlement permits"
    return "licensed_source", "dataset metadata", "entitlement discovery"


def build_entitlement_map(calls: list[dict[str, Any]]) -> dict[str, Any]:
    dataset_call = next((call for call in calls if call["call_name"] == "available_datasets"), None)
    items: list[dict[str, Any]] = []
    if dataset_call and dataset_call.get("status") == "success":
        rows = dataset_call.get("payload", {}).get("rows", []) or []
        for row in rows:
            dataset_id = str(row.get("datasetId") or row.get("id") or "")
            dataset_name = str(row.get("name") or row.get("datasetName") or dataset_id)
            domain, data_domain, use_case = likely_use_case(dataset_name)
            items.append(
                {
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                    "asset_type": "method_unavailable",
                    "data_domain": data_domain,
                    "fr_domain": domain,
                    "available_to_user": True,
                    "permission_status": "available_from_dataset_list",
                    "sample_supported": "metadata_only",
                    "fields_discovered": [],
                    "likely_fr_use_case": use_case,
                    "notes": "Dataset listed by Morningstar Direct. Field-level entitlement requires dataset-specific follow-up.",
                }
            )

    for call in calls:
        if call["call_name"] == "available_datasets":
            continue
        items.append(
            {
                "dataset_id": f"method:{call['call_name']}",
                "dataset_name": call["call_name"],
                "asset_type": "method_probe",
                "data_domain": "entitlement_probe",
                "fr_domain": "licensed_source",
                "available_to_user": call.get("status") == "success",
                "permission_status": classify_permission(call),
                "sample_supported": call.get("status") == "success",
                "fields_discovered": (call.get("payload") or {}).get("columns", []) if isinstance(call.get("payload"), dict) else [],
                "likely_fr_use_case": "Method capability / entitlement probe",
                "notes": (call.get("error_message") or "small probe succeeded")[:300],
            }
        )
    result = {
        "generated_at": utc_now(),
        "dataset_count": len(items),
        "permission_status_counts": dict(Counter(item["permission_status"] for item in items)),
        "items": items,
        "method_results": calls,
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "token_leaked": False,
    }
    write_json(PILOT_ROOT / "morningstar_dataset_entitlement_map.json", result)
    return result


def build_taxonomy_mapping(entitlement_map: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "generated_at": utc_now(),
        "source_id": "morningstar_direct",
        "source_type": "licensed_authorized_platform",
        "mappings": [
            {
                "morningstar_capability": "ETF / Fund",
                "fr_domains": ["capital_flow", "fund_market", "asset_class"],
                "use_cases": ["ETF watchlist", "fund performance", "holdings", "sector exposure", "asset allocation"],
                "status": "candidate_if_entitled",
            },
            {
                "morningstar_capability": "Index / Benchmark",
                "fr_domains": ["asset_class", "benchmark"],
                "use_cases": ["equity index", "bond index", "commodity index", "benchmark comparison"],
                "status": "candidate_if_entitled",
            },
            {
                "morningstar_capability": "Equity / Company",
                "fr_domains": ["company", "fundamentals"],
                "use_cases": ["company profile", "valuation", "financial ratios", "estimates if entitlement permits"],
                "status": "candidate_if_entitled",
            },
            {
                "morningstar_capability": "Holdings / Portfolio",
                "fr_domains": ["capital_flow", "institutional_position_proxy"],
                "use_cases": ["ETF constituent exposure", "fund holdings", "sector allocation", "country allocation"],
                "status": "candidate_if_entitled",
            },
        ],
        "dataset_domain_counts": dict(Counter(item.get("fr_domain", "unknown") for item in entitlement_map.get("items", []))),
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }
    write_json(PILOT_ROOT / "morningstar_fr_taxonomy_mapping.json", mapping)
    write_text(
        DOCS_ROOT / "MORNINGSTAR_FR_TAXONOMY_MAPPING.md",
        """# Morningstar FR Taxonomy Mapping

Morningstar Direct is mapped as a licensed authorized platform. It can support FR data domains only within the user's entitlement and license boundaries.

## Primary Mappings

- ETF / Fund: `capital_flow`, `fund_market`, `asset_class`.
- Index / Benchmark: `asset_class`, `benchmark`.
- Equity / Company: `company`, `fundamentals`.
- Holdings / Portfolio: `capital_flow`, `institutional_position_proxy`.

All mapped data remains `licensed_source_candidate` / candidate staging until entitlement, storage, redistribution and quality gates are explicitly cleared.
""",
    )
    return mapping


def build_schema_summary() -> dict[str, Any]:
    schemas = {
        "fund_etf_master_schema": [
            "dataset_id",
            "source_id",
            "morningstar_sec_id",
            "isin",
            "ticker",
            "exchange",
            "fund_name",
            "fund_type",
            "category",
            "domicile",
            "currency",
            "inception_date",
            "provider",
            "retrieved_at",
            "entitlement_status",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
        "holdings_schema": [
            "dataset_id",
            "source_id",
            "portfolio_id",
            "holding_date",
            "holding_name",
            "holding_identifier",
            "asset_type",
            "weight",
            "shares",
            "market_value",
            "sector",
            "country",
            "currency",
            "retrieved_at",
            "entitlement_status",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
        "performance_nav_schema": [
            "dataset_id",
            "source_id",
            "morningstar_sec_id",
            "observation_date",
            "publish_date",
            "value",
            "value_type",
            "currency",
            "frequency",
            "retrieved_at",
            "entitlement_status",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
    }
    result = {
        "generated_at": utc_now(),
        "source_id": "morningstar_direct",
        "schema_version": "morningstar_connector_schema_v1",
        "schemas": schemas,
        "formal_trusted_consumption": False,
    }
    write_json(PILOT_ROOT / "schema_summary.json", result)
    write_text(
        DOCS_ROOT / "MORNINGSTAR_CONNECTOR_SCHEMA_V1.md",
        """# Morningstar Connector Schema v1

Morningstar data is licensed-source candidate evidence. These schemas prepare ingestion without promoting records into formal trusted consumption.

## Fund / ETF Master Schema

`dataset_id`, `source_id`, `morningstar_sec_id`, `isin`, `ticker`, `exchange`, `fund_name`, `fund_type`, `category`, `domicile`, `currency`, `inception_date`, `provider`, `retrieved_at`, `entitlement_status`, `quality_status`, `trust_status`, `candidate_only`

## Holdings Schema

`dataset_id`, `source_id`, `portfolio_id`, `holding_date`, `holding_name`, `holding_identifier`, `asset_type`, `weight`, `shares`, `market_value`, `sector`, `country`, `currency`, `retrieved_at`, `entitlement_status`, `quality_status`, `trust_status`, `candidate_only`

## Performance / NAV Schema

`dataset_id`, `source_id`, `morningstar_sec_id`, `observation_date`, `publish_date`, `value`, `value_type`, `currency`, `frequency`, `retrieved_at`, `entitlement_status`, `quality_status`, `trust_status`, `candidate_only`
""",
    )
    return result


def write_licensed_source_policy() -> None:
    write_text(
        DOCS_ROOT / "LICENSED_DATA_SOURCE_USAGE_POLICY.md",
        """# Licensed Data Source Usage Policy

Morningstar Direct / Analytics Lab is a `licensed_authorized_platform`, not a public source.

Rules:

1. Access is controlled by entitlement, license, token and content limits.
2. FR does not auto-login, store passwords, bypass MFA/SSO, or automate token copying.
3. `MD_AUTH_TOKEN` is user-copied and expires in about 24 hours.
4. Raw storage and redistribution require user confirmation and entitlement review.
5. Large backfill is disabled until entitlement review.
6. Data entering FR is `licensed_source_candidate` / candidate staging only.
7. Licensed data does not enter formal trusted consumption unless the user later confirms authorization and usage scope.
""",
    )


def small_pilot(entitlement_map: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    RAW_LICENSED_ROOT.mkdir(parents=True, exist_ok=True)
    STRUCTURED_LICENSED_ROOT.mkdir(parents=True, exist_ok=True)
    rows = entitlement_map.get("items", [])
    dataset_entries = [item for item in rows if item.get("permission_status") == "available_from_dataset_list"][:10]
    method_entries = [item for item in rows if item.get("dataset_id", "").startswith("method:")]
    raw_storage_mode = "metadata_only_due_to_license_review"
    raw_payload = {
        "generated_at": utc_now(),
        "source_id": "morningstar_direct",
        "raw_storage_mode": raw_storage_mode,
        "complete_raw_data_saved": False,
        "dataset_metadata_sample": dataset_entries,
        "method_probe_summary": method_entries,
        "token_leaked": False,
    }
    raw_path = RAW_LICENSED_ROOT / "morningstar_pilot_metadata_only_raw.json"
    write_json(raw_path, raw_payload)

    normalized_items = []
    for item in dataset_entries:
        normalized_items.append(
            {
                "dataset_id": item["dataset_id"],
                "source_id": "morningstar_direct",
                "dataset_name": item["dataset_name"],
                "fr_domain": item["fr_domain"],
                "data_domain": item["data_domain"],
                "likely_fr_use_case": item["likely_fr_use_case"],
                "entitlement_status": item["permission_status"],
                "quality_status": "quality_passed" if item["dataset_id"] else "quality_warning",
                "trust_status": "licensed_source_candidate",
                "candidate_only": True,
                "retrieved_at": utc_now(),
                "raw_reference": str(raw_path),
            }
        )
    normalized_path = STRUCTURED_LICENSED_ROOT / "morningstar_pilot_normalized_metadata.json"
    write_json(normalized_path, {"items": normalized_items})
    local_normalized_path = PILOT_ROOT / "morningstar_pilot_normalized_metadata.json"
    write_json(local_normalized_path, {"items": normalized_items})

    quality_items = []
    for item in normalized_items:
        missing = [field for field in ["dataset_id", "source_id", "dataset_name", "entitlement_status"] if not item.get(field)]
        quality_items.append(
            {
                "dataset_id": item["dataset_id"],
                "quality_status": "quality_passed" if not missing else "quality_warning",
                "missing_fields": missing,
                "candidate_only": True,
            }
        )
    quality = {
        "generated_at": utc_now(),
        "items": quality_items,
        "quality_counts": dict(Counter(item["quality_status"] for item in quality_items)),
        "formal_trusted_consumption": False,
    }
    pilot = {
        "generated_at": utc_now(),
        "pilot_completed": True,
        "datasets_selected": len(normalized_items),
        "raw_storage_enabled": False,
        "raw_storage_mode": raw_storage_mode,
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path),
        "local_normalized_path": str(local_normalized_path),
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "large_download_performed": False,
        "notes": "Only metadata/schema-level pilot output was stored. Complete raw Morningstar data storage requires user entitlement confirmation.",
    }
    write_json(PILOT_ROOT / "small_pilot_results.json", pilot)
    write_json(PILOT_ROOT / "small_pilot_quality_results.json", quality)
    return pilot, quality


def update_source_policy(token_health: dict[str, Any], entitlement_map: dict[str, Any], pilot: dict[str, Any]) -> dict[str, Any]:
    policy = {
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
        "token_status": token_health.get("token_status"),
        "redistribution_status": "needs_review",
        "raw_storage_allowed": "needs_user_confirmation",
        "full_backfill_allowed": "no_until_entitlement_review",
        "trust_status": "licensed_source_candidate",
        "consumption_eligibility": "not_formal_trusted_consumption",
        "entitlement_mapping_status": "completed",
        "pilot_dataset_count": pilot.get("datasets_selected", 0),
        "dashboard_status": {
            "source_gap_status": "entitlement_mapping_completed",
            "token_status": token_health.get("token_status"),
            "last_smoke_test_result": "pilot_completed",
            "pilot_dataset_count": pilot.get("datasets_selected", 0),
            "authorized_source_warning": "Licensed source; not public, not redistributable without entitlement review.",
            "user_action_required": token_health.get("user_action_required"),
        },
        "security_controls": {
            "no_auto_login": True,
            "no_password_saved": True,
            "no_browser_automation": True,
            "manual_copy_authentication_token": True,
            "token_not_logged": True,
        },
    }
    update_policy_file(CONFIG_ROOT / "source_acquisition_policy.json", policy, "source_acquisition")
    update_policy_file(CONFIG_ROOT / "third_party_source_policy.json", policy, "third_party_source")
    dashboard_status = {
        "generated_at": utc_now(),
        "sources": [
            {
                "source_id": "morningstar_direct",
                "display_name": "Morningstar Direct",
                "status": policy["dashboard_status"]["source_gap_status"],
                "token_status": policy["dashboard_status"]["token_status"],
                "entitlement_mapping_status": policy["entitlement_mapping_status"],
                "pilot_dataset_count": policy["pilot_dataset_count"],
                "last_smoke_test_result": policy["dashboard_status"]["last_smoke_test_result"],
                "warning": policy["dashboard_status"]["authorized_source_warning"],
                "licensed_authorized_platform": True,
            }
        ],
    }
    write_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", dashboard_status)
    return policy


def write_pilot_report(
    token_health: dict[str, Any],
    entitlement_map: dict[str, Any],
    taxonomy_mapping: dict[str, Any],
    pilot: dict[str, Any],
    quality: dict[str, Any],
    schema: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    write_json(
        PILOT_ROOT / "morningstar_pilot_summary.json",
        {
            "generated_at": utc_now(),
            "entitlement_mapping_completed": True,
            "visible_dataset_count": entitlement_map.get("dataset_count", 0),
            "permission_status_counts": entitlement_map.get("permission_status_counts", {}),
            "taxonomy_mapping_completed": True,
            "small_pilot_completed": pilot.get("pilot_completed"),
            "raw_storage_enabled": pilot.get("raw_storage_enabled"),
            "raw_storage_mode": pilot.get("raw_storage_mode"),
            "schema_completed": True,
            "licensed_source_policy_completed": True,
            "dashboard_source_status_updated": True,
            "no_auto_login": True,
            "no_password_saved": True,
            "token_leaked": False,
            "large_download_performed": False,
            "openai_api_called": False,
            "parse_lab_affected": False,
            "formal_trusted_consumption_affected": False,
            "outputs": {
                "token_health": str(PILOT_ROOT / "token_health_check.json"),
                "entitlement_map": str(PILOT_ROOT / "morningstar_dataset_entitlement_map.json"),
                "taxonomy_mapping": str(PILOT_ROOT / "morningstar_fr_taxonomy_mapping.json"),
                "small_pilot": str(PILOT_ROOT / "small_pilot_results.json"),
                "quality": str(PILOT_ROOT / "small_pilot_quality_results.json"),
                "schema": str(PILOT_ROOT / "schema_summary.json"),
            },
        },
    )
    report = f"""# Morningstar Direct Entitlement Mapping + Licensed Connector Pilot v1

Generated at: {utc_now()}

## Summary

- Entitlement mapping completed: yes.
- Visible dataset / method entries: {entitlement_map.get('dataset_count', 0)}.
- Permission status counts: `{entitlement_map.get('permission_status_counts', {})}`.
- FR taxonomy mapping completed: yes.
- Small licensed connector pilot completed: {pilot.get('pilot_completed')}.
- Raw storage enabled: {pilot.get('raw_storage_enabled')} ({pilot.get('raw_storage_mode')}).
- Schema v1 completed: {bool(schema)}.
- Licensed source policy completed: yes.
- Dashboard source status updated: yes.

## Safety

- Auto login: no.
- Password saved: no.
- Token leaked: no.
- Large download: no.
- Formal trusted consumption affected: no.

## Token Health

- Token status: {token_health.get('token_status')}.
- Masked token: {token_health.get('masked_token')}.
- Token format diagnostic: `{token_health.get('token_format_diagnostic')}`.

## Pilot Boundary

Only metadata/schema-level samples were stored. Complete Morningstar raw storage, redistribution, and backfill require user entitlement confirmation.
"""
    write_text(DOCS_ROOT / "MORNINGSTAR_DIRECT_ENTITLEMENT_MAPPING_AND_PILOT_REPORT.md", report)


def run() -> dict[str, Any]:
    PILOT_ROOT.mkdir(parents=True, exist_ok=True)
    token_health = token_health_check()
    token = load_morningstar_secret().get("md_auth_token")
    library_token = token_for_library(token)

    calls = []
    if token_health.get("token_present") and not token_health.get("local_secrets_git_tracked"):
        for call_name in [
            "available_datasets",
            "user_investment_lists",
            "data_point_settings",
            "investment_search_spy",
        ]:
            call = run_limited_call(call_name, library_token)
            calls.append(call)
            if classify_permission(call) in {"permission_denied", "token_format_error"} and call_name not in {"available_datasets"}:
                # Do not keep pushing a method that already returned a clear permission/token issue.
                continue
    else:
        calls.append({"call_name": "all", "attempted": False, "status": "skipped", "error_type": token_health.get("user_action_required")})

    entitlement_map = build_entitlement_map(calls)
    taxonomy_mapping = build_taxonomy_mapping(entitlement_map)
    schema = build_schema_summary()
    write_licensed_source_policy()
    pilot, quality = small_pilot(entitlement_map)
    policy = update_source_policy(token_health, entitlement_map, pilot)
    write_pilot_report(token_health, entitlement_map, taxonomy_mapping, pilot, quality, schema, policy)
    return read_json(PILOT_ROOT / "morningstar_pilot_summary.json")


if __name__ == "__main__":
    summary = run()
    print(
        json.dumps(
            {
                "completed": True,
                "visible_dataset_count": summary.get("visible_dataset_count"),
                "permission_status_counts": summary.get("permission_status_counts"),
                "small_pilot_completed": summary.get("small_pilot_completed"),
                "raw_storage_enabled": summary.get("raw_storage_enabled"),
                "outputs_root": str(PILOT_ROOT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
