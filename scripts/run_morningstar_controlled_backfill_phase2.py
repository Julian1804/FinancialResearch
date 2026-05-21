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
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase2"
SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    if not token:
        return None
    return str(token)


def token_health_check(token: str | None) -> dict[str, Any]:
    result = {
        "token_present": token is not None and len(token) > 0,
        "token_masked": mask_token(token) if token else "N/A",
        "expired": False,
        "expires_at": None,
        "expiry_seconds_remaining": None,
        "error": None,
    }
    if not token:
        result["expired"] = True
        result["error"] = "token_missing"
        return result
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("token does not look like JWT")
        payload_b64 = parts[1]
        # pad base64url
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        exp_ts = payload.get("exp")
        if exp_ts:
            exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
            result["expires_at"] = exp_dt.isoformat().replace("+00:00", "Z")
            now = datetime.now(timezone.utc)
            remaining = int((exp_dt - now).total_seconds())
            result["expiry_seconds_remaining"] = remaining
            if remaining <= 0:
                result["expired"] = True
                result["error"] = "token_expired"
            elif remaining < 600:
                result["error"] = "token_expires_soon"
        else:
            result["error"] = "no_exp_claim"
    except Exception as exc:
        result["error"] = f"token_parse_failed: {exc}"
    return result


def build_seed_list() -> list[str]:
    """Fund/ETF/Bond/Commodity/Asset-Class focused seeds. No standalone US equity tickers."""
    return [
        "SPY", "QQQ", "VTI", "AGG", "BND", "TLT", "IEF", "LQD", "HYG",
        "GLD", "IAU", "SLV", "DBC", "USO", "UNG", "VNQ", "VEA", "VWO",
        "EEM", "ACWI", "VT",
    ]


def run_subprocess_calls(token: str, seeds: list[str]) -> dict[str, Any]:
    child_code = f"""
import json, os, sys
try:
    import morningstar_data as md
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":"import_error","error":str(exc)[:800]}}))
    sys.exit(2)

token = os.environ.get("MD_AUTH_TOKEN")
if not token:
    print(json.dumps({{"status":"failed","error_type":"missing_token"}}))
    sys.exit(2)

seeds = {seeds!r}
max_per_seed = 5
results = {{}}

for seed in seeds:
    try:
        df = md.direct.investments(keyword=seed, count=max_per_seed)
        rows = df.head(max_per_seed).where(df.notna(), None).to_dict(orient='records')
        results[seed] = {{
            "status": "success",
            "row_count": int(len(df)),
            "columns": [str(c) for c in list(df.columns)],
            "sample": rows,
        }}
    except Exception as exc:
        results[seed] = {{"status": "failed", "error": str(exc)[:500]}}

extra = {{}}
# Fund/ETF universe datasets metadata
try:
    df = md.direct.get_morningstar_data_sets('FO')
    extra["fund_universe_datasets"] = {{
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(5).where(df.notna(), None).to_dict(orient='records'),
    }}
except Exception as exc:
    extra["fund_universe_datasets"] = {{"status": "failed", "error": str(exc)[:500]}}

# User investment lists
try:
    df = md.direct.user_items.get_investment_lists()
    extra["user_investment_lists"] = {{
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(5).where(df.notna(), None).to_dict(orient='records'),
    }}
except Exception as exc:
    extra["user_investment_lists"] = {{"status": "failed", "error": str(exc)[:500]}}

print(json.dumps({{"status": "success", "results": results, "extra": extra}}, ensure_ascii=False))
"""
    env = os.environ.copy()
    env["MD_AUTH_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            return {
                "subprocess_status": "failed",
                "stdout": completed.stdout[:1000],
                "stderr": completed.stderr[:1000],
            }
        return json.loads(completed.stdout)
    except subprocess.TimeoutExpired:
        return {"subprocess_status": "timeout", "error": "subprocess timed out after 120s"}
    except Exception as exc:
        return {"subprocess_status": "exception", "error": str(exc)[:800]}


def normalize_identifier_anchor(api_results: dict[str, Any]) -> dict[str, Any]:
    anchor_items = []
    seen_keys = set()
    results = api_results.get("results", {})
    for seed, call_res in results.items():
        if call_res.get("status") != "success":
            continue
        for row in call_res.get("sample", []):
            sec_id = row.get("SecId") or row.get("secId") or ""
            isin = row.get("ISIN") or row.get("isin") or ""
            key = (sec_id, isin) if (sec_id or isin) else json.dumps(row, sort_keys=True)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            anchor_items.append({
                "source": "morningstar_direct",
                "search_seed": seed,
                "name": row.get("Name") or row.get("name") or "",
                "sec_id": sec_id,
                "ticker": row.get("Ticker") or row.get("ticker") or "",
                "isin": isin,
                "cusip": row.get("CUSIP") or row.get("cusip") or "",
                "currency": row.get("Base Currency") or row.get("baseCurrency") or "",
                "exchange": row.get("Exchange") or row.get("exchange") or "",
                "country": row.get("Country") or row.get("country") or "",
                "security_type": row.get("Security Type") or row.get("securityType") or "",
                "fund_id": row.get("Fund Id") or row.get("fundId") or "",
                "performance_id": row.get("Performance Id") or row.get("performanceId") or "",
            })
    return {
        "generated_at": utc_now(),
        "record_count": len(anchor_items),
        "unique_by_secid_isin": len(seen_keys),
        "anchor_items": anchor_items,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def build_entity_master_crosswalk(normalized: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for item in normalized.get("anchor_items", []):
        candidates.append({
            "source_id": "morningstar_direct",
            "source_sec_id": item.get("sec_id"),
            "source_isin": item.get("isin"),
            "source_ticker": item.get("ticker"),
            "source_name": item.get("name"),
            "source_exchange": item.get("exchange"),
            "source_country": item.get("country"),
            "source_currency": item.get("currency"),
            "source_security_type": item.get("security_type"),
            "source_fund_id": item.get("fund_id"),
            "source_performance_id": item.get("performance_id"),
            "crosswalk_status": "candidate",
            "validation_needed": ["isin_checksum", "ticker_exchange_match", "sec_id_uniqueness"],
        })
    return {
        "generated_at": utc_now(),
        "record_count": len(candidates),
        "source": "morningstar_direct",
        "crosswalk_candidates": candidates,
        "candidate_only": True,
    }


def build_qa(api_results: dict[str, Any], normalized: dict[str, Any], token_health: dict[str, Any]) -> dict[str, Any]:
    qa = {
        "generated_at": utc_now(),
        "token_health": token_health,
        "api_calls_attempted": 0,
        "api_calls_succeeded": 0,
        "api_calls_failed": 0,
        "total_records_sampled": 0,
        "fund_etf_records": 0,
        "bond_records": 0,
        "commodity_records": 0,
        "asset_class_records": 0,
        "field_coverage": {},
        "identifier_anchor_coverage": {},
        "freshness_notes": [],
        "license_boundary_notes": [],
        "rate_limit_notes": [],
        "blockers": [],
    }

    # Investment search results
    results = api_results.get("results", {})
    for seed, call_res in results.items():
        qa["api_calls_attempted"] += 1
        if call_res.get("status") == "success":
            qa["api_calls_succeeded"] += 1
            row_count = call_res.get("row_count", 0)
            qa["total_records_sampled"] += min(row_count, 5)
            cols = call_res.get("columns", [])
            qa["field_coverage"][seed] = {"column_count": len(cols), "columns": cols}
            id_like = [c for c in cols if any(t in c.lower() for t in ("secid", "isin", "ticker", "symbol", "identifier", "name", "exchange", "currency", "country", "fund id", "performance id"))]
            qa["identifier_anchor_coverage"][seed] = id_like
            # Classify by seed domain (approximate)
            seed_upper = seed.upper()
            if seed_upper in ("SPY", "QQQ", "VTI", "VT", "ACWI", "EEM", "VEA", "VWO"):
                qa["fund_etf_records"] += min(row_count, 5)
            elif seed_upper in ("AGG", "BND", "TLT", "IEF", "LQD", "HYG"):
                qa["bond_records"] += min(row_count, 5)
            elif seed_upper in ("GLD", "IAU", "SLV", "DBC", "USO", "UNG"):
                qa["commodity_records"] += min(row_count, 5)
            elif seed_upper in ("VNQ",):
                qa["asset_class_records"] += min(row_count, 5)
        else:
            qa["api_calls_failed"] += 1
            err = call_res.get("error", "")
            if any(t in err.lower() for t in ("entitlement", "unauthor", "forbidden", "license")):
                qa["license_boundary_notes"].append(f"{seed}: entitlement/license error")
            if any(t in err.lower() for t in ("rate", "throttle", "limit", "too many")):
                qa["rate_limit_notes"].append(f"{seed}: rate limit indication")

    # Extra calls
    extra = api_results.get("extra", {})
    for call_name, call_res in extra.items():
        qa["api_calls_attempted"] += 1
        if call_res.get("status") == "success":
            qa["api_calls_succeeded"] += 1
            cols = call_res.get("columns", [])
            qa["field_coverage"][call_name] = {"column_count": len(cols), "columns": cols}
        else:
            qa["api_calls_failed"] += 1

    qa["freshness_notes"].append("Freshness requires dated time-series samples; 5-row investment search does not provide observation dates.")
    qa["license_boundary_notes"].append("All storage remains candidate_only; broad raw dataset storage blocked pending explicit user license/storage review.")

    if token_health.get("expired"):
        qa["blockers"].append("token_expired")
    if token_health.get("error") and token_health["error"] != "token_expires_soon":
        qa["blockers"].append(f"token_health: {token_health['error']}")
    if qa["api_calls_succeeded"] == 0 and qa["api_calls_attempted"] > 0:
        qa["blockers"].append("all_api_calls_failed")

    return qa


def build_failure_log(api_results: dict[str, Any]) -> dict[str, Any]:
    failures = {}
    for section in ("results", "extra"):
        for call_name, call_res in api_results.get(section, {}).items():
            if call_res.get("status") != "success":
                failures[call_name] = call_res.get("error", "unknown")
    return {
        "generated_at": utc_now(),
        "failures": failures,
    }


def build_license_note() -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "license_boundary": "needs_user_license_storage_usage_review",
        "raw_storage_mode": "small_sample_and_metadata_only",
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "large_download_performed": False,
        "note": "Phase 2 does not store broad raw Morningstar datasets. Full licensed storage requires explicit user confirmation of entitlement and data-lake path.",
    }


def main() -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    token = get_token()
    token_health = token_health_check(token)
    token_masked = token_health["token_masked"]

    # Plan manifest (always written)
    plan = {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase2",
        "objective": "Expand identifier anchor library for fund/ETF/bond/commodity/asset-class. No standalone US equity data.",
        "scope_exclusions": ["standalone_us_equity_price_series", "individual_stock_fundamentals", "broad_universe_backfill"],
        "token_available": token_health["token_present"],
        "token_masked": token_masked,
        "seed_list": build_seed_list(),
        "max_per_seed": 5,
        "max_total_api_calls": 25,
        "no_auto_login": True,
        "no_password_saved": True,
        "output_paths": {
            "raw": str(RUNTIME_ROOT / "raw"),
            "normalized": str(RUNTIME_ROOT / "normalized"),
            "crosswalk": str(RUNTIME_ROOT / "crosswalk"),
            "manifest": str(RUNTIME_ROOT / "manifest"),
            "qa": str(RUNTIME_ROOT / "qa"),
            "failure_log": str(RUNTIME_ROOT / "failure_log"),
        },
    }
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_controlled_backfill_phase2_plan.json", plan)

    # Token expiry blocker
    if token_health.get("expired"):
        summary = {
            "generated_at": utc_now(),
            "phase": "morningstar_controlled_backfill_phase2",
            "token_available": token_health["token_present"],
            "token_masked": token_masked,
            "dry_run_completed": True,
            "small_sample_attempted": False,
            "small_sample_status": "skipped_token_expired",
            "api_calls_succeeded": 0,
            "api_calls_failed": 0,
            "blockers": ["token_expired_user_action_required"],
            "next_action": "user_action_required",
            "outputs": plan["output_paths"],
            "no_auto_login": True,
            "no_password_saved": True,
            "token_leaked": False,
            "openai_api_called": False,
            "parse_lab_affected": False,
            "formal_trusted_consumption_affected": False,
        }
        write_json(RUNTIME_ROOT / "manifest" / "morningstar_controlled_backfill_phase2_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # Run API calls
    seeds = plan["seed_list"]
    api_results = run_subprocess_calls(token, seeds)
    write_json(RUNTIME_ROOT / "raw" / "morningstar_phase2_raw_samples.json", api_results)

    # Normalize
    normalized = normalize_identifier_anchor(api_results)
    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase2_identifier_anchor.json", normalized)

    # Crosswalk
    crosswalk = build_entity_master_crosswalk(normalized)
    write_json(RUNTIME_ROOT / "crosswalk" / "morningstar_phase2_entity_master_crosswalk_candidate.json", crosswalk)

    # QA
    qa = build_qa(api_results, normalized, token_health)
    write_json(RUNTIME_ROOT / "qa" / "morningstar_phase2_qa_summary.json", qa)

    # Failure log
    failure_log = build_failure_log(api_results)
    write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase2_failure_log.json", failure_log)

    # License note
    license_note = build_license_note()
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase2_license_boundary_note.json", license_note)

    # Summary manifest
    summary = {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase2",
        "token_available": token_health["token_present"],
        "token_masked": token_masked,
        "dry_run_completed": True,
        "small_sample_attempted": True,
        "small_sample_status": api_results.get("status"),
        "api_calls_succeeded": qa["api_calls_succeeded"],
        "api_calls_failed": qa["api_calls_failed"],
        "total_records_sampled": qa["total_records_sampled"],
        "unique_identifier_anchors": normalized.get("unique_by_secid_isin", 0),
        "blockers": qa["blockers"],
        "outputs": {
            "plan": str(RUNTIME_ROOT / "manifest" / "morningstar_controlled_backfill_phase2_plan.json"),
            "license_note": str(RUNTIME_ROOT / "manifest" / "morningstar_phase2_license_boundary_note.json"),
            "qa_summary": str(RUNTIME_ROOT / "qa" / "morningstar_phase2_qa_summary.json"),
            "failure_log": str(RUNTIME_ROOT / "failure_log" / "morningstar_phase2_failure_log.json"),
            "crosswalk": str(RUNTIME_ROOT / "crosswalk" / "morningstar_phase2_entity_master_crosswalk_candidate.json"),
            "normalized": str(RUNTIME_ROOT / "normalized" / "morningstar_phase2_identifier_anchor.json"),
            "raw": str(RUNTIME_ROOT / "raw" / "morningstar_phase2_raw_samples.json"),
        },
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
    }
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_controlled_backfill_phase2_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
