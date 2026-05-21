from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase1"
SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"

# existing candidate registry for reference
CONTROLLED_CANDIDATES_PATH = (
    PROJECT_ROOT / "runtime" / "automated_ingestion_system" / "morningstar_controlled_ingestion_candidates.json"
)


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


def run_subprocess_calls(token: str) -> dict[str, Any]:
    """Run a small number of low-frequency Morningstar API calls in an isolated subprocess."""
    child_code = r"""
import json, os, sys
try:
    import morningstar_data as md
except Exception as exc:
    print(json.dumps({"status":"failed","error_type":"import_error","error":str(exc)[:800]}))
    sys.exit(2)

token = os.environ.get("MD_AUTH_TOKEN")
if not token:
    print(json.dumps({"status":"failed","error_type":"missing_token"}))
    sys.exit(2)

results = {}

# Call 1: ETF identifier anchor (SPY)
try:
    df = md.direct.investments(keyword='SPY', count=5)
    results["spy_search"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(5).where(df.notna(), None).to_dict(orient='records'),
    }
except Exception as exc:
    results["spy_search"] = {"status": "failed", "error": str(exc)[:500]}

# Call 2: Equity identifier anchor (AAPL)
try:
    df = md.direct.investments(keyword='AAPL', count=5)
    results["aapl_search"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(5).where(df.notna(), None).to_dict(orient='records'),
    }
except Exception as exc:
    results["aapl_search"] = {"status": "failed", "error": str(exc)[:500]}

# Call 3: data-point settings probe (fund metadata fields)
try:
    df = md.direct.get_data_point_settings(['OS01W', 'HP010', 'MHPAA', 'MHPAB'])
    results["data_point_settings"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(5).where(df.notna(), None).to_dict(orient='records'),
    }
except Exception as exc:
    results["data_point_settings"] = {"status": "failed", "error": str(exc)[:500]}

print(json.dumps({"status": "success", "results": results}, ensure_ascii=False))
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
            timeout=60,
        )
        if completed.returncode != 0:
            return {
                "subprocess_status": "failed",
                "stdout": completed.stdout[:1000],
                "stderr": completed.stderr[:1000],
            }
        return json.loads(completed.stdout)
    except subprocess.TimeoutExpired:
        return {"subprocess_status": "timeout", "error": "subprocess timed out after 60s"}
    except Exception as exc:
        return {"subprocess_status": "exception", "error": str(exc)[:800]}


def build_dry_run_plan(token_available: bool, token_masked: str) -> dict[str, Any]:
    candidates = []
    if CONTROLLED_CANDIDATES_PATH.exists():
        candidates = read_json(CONTROLLED_CANDIDATES_PATH).get("candidates", [])

    # Select Phase 1 priority datasets based on metadata/identifier-anchor suitability
    priority_dataset_ids = {
        "morningstar_symbol_search_us_etf_sample",
        "0218-1215",  # Share Class Analysis
        "0218-0034",  # Operations
        "0218-0045",  # Morningstar Ratings and Grades
        "0218-0576",  # Morningstar Medalist Rating Input Data
    }

    plan_items = []
    for c in candidates:
        ds_id = c.get("dataset_id", "")
        if ds_id in priority_dataset_ids:
            plan_items.append(
                {
                    "dataset_id": ds_id,
                    "dataset_name": c.get("dataset_name"),
                    "domain": c.get("domain"),
                    "entity_type": c.get("entity_type"),
                    "phase1_plan": "controlled_sample",
                    "max_records": 50,
                    "max_pages": 1,
                    "identifier_fields": c.get("identifier_fields", []),
                    "date_fields": c.get("date_fields", []),
                    "license_boundary": c.get("license_boundary"),
                    "raw_storage_status": c.get("raw_storage_status"),
                    "automation_status": c.get("automation_status"),
                }
            )

    return {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase1",
        "token_available": token_available,
        "token_masked": token_masked,
        "no_auto_login": True,
        "no_password_saved": True,
        "objective": "Validate coverage, freshness, field completeness, identifier mapping, license/storage boundary, rate limit, failure retry, and local storage structure before any broad backfill.",
        "priority": "metadata / identifier anchor",
        "allowed_actions": [
            "small_batch_controlled_backfill",
            "metadata_and_identifier_anchor_first",
            "sample_size_or_page_limit_per_dataset",
            "dry_run_manifest",
            "token_availability_check",
        ],
        "forbidden_actions": [
            "broad_backfill",
            "auto_login",
            "password_persistence",
            "full_token_print",
            "high_frequency_requests",
            "authorization_circumvention",
            "openai_api_call",
            "formal_trusted_consumption_enable",
            "parse_lab_impact",
        ],
        "plan_items": plan_items,
        "output_paths": {
            "raw": str(RUNTIME_ROOT / "raw"),
            "normalized": str(RUNTIME_ROOT / "normalized"),
            "crosswalk": str(RUNTIME_ROOT / "crosswalk"),
            "manifest": str(RUNTIME_ROOT / "manifest"),
            "qa": str(RUNTIME_ROOT / "qa"),
            "failure_log": str(RUNTIME_ROOT / "failure_log"),
        },
    }


def run_qa_on_results(api_results: dict[str, Any]) -> dict[str, Any]:
    qa = {
        "generated_at": utc_now(),
        "token_import_ok": api_results.get("status") == "success",
        "api_calls_attempted": 0,
        "api_calls_succeeded": 0,
        "api_calls_failed": 0,
        "field_coverage": {},
        "identifier_anchor_coverage": {},
        "freshness_notes": [],
        "license_boundary_notes": [],
        "rate_limit_notes": [],
        "blockers": [],
    }

    results = api_results.get("results", {})
    for call_name, call_res in results.items():
        qa["api_calls_attempted"] += 1
        if call_res.get("status") == "success":
            qa["api_calls_succeeded"] += 1
            cols = call_res.get("columns", [])
            qa["field_coverage"][call_name] = {
                "column_count": len(cols),
                "columns": cols,
            }
            # Map likely identifier fields
            id_like = [c for c in cols if any(term in c.lower() for term in ("secid", "isin", "ticker", "symbol", "identifier", "name", "exchange", "currency", "country"))]
            qa["identifier_anchor_coverage"][call_name] = id_like
        else:
            qa["api_calls_failed"] += 1
            err = call_res.get("error", "")
            qa["failure_log"][call_name] = err  # type: ignore[index]
            if any(term in err.lower() for term in ("entitlement", "unauthor", "forbidden", "license")):
                qa["license_boundary_notes"].append(f"{call_name}: entitlement/license error")
            if any(term in err.lower() for term in ("rate", "throttle", "limit", "too many")):
                qa["rate_limit_notes"].append(f"{call_name}: rate limit indication")

    if not qa["token_import_ok"]:
        qa["blockers"].append("morningstar_data import or token setup failed")
    if qa["api_calls_succeeded"] == 0 and qa["api_calls_attempted"] > 0:
        qa["blockers"].append("all API calls failed")

    # Freshness: we cannot assess true data freshness from a 5-row sample; note it.
    qa["freshness_notes"].append("Freshness assessment requires a dated time-series sample; not available from 5-row investment search.")
    qa["license_boundary_notes"].append("All storage remains candidate_only; raw full-dataset storage blocked pending explicit user license/storage review.")

    return qa


def main() -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    token = get_token()
    token_available = token is not None and len(token) > 0
    token_masked = mask_token(token) if token else "N/A"

    # 1. Build dry-run plan
    plan = build_dry_run_plan(token_available, token_masked)
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_controlled_backfill_phase1_plan.json", plan)

    # 2. Token / small-sample probe (only if token looks present)
    api_results: dict[str, Any] = {"status": "skipped", "reason": "token_not_available"}
    if token_available:
        api_results = run_subprocess_calls(token)
        write_json(RUNTIME_ROOT / "raw" / "morningstar_phase1_small_sample_raw.json", api_results)

    # 3. QA / field coverage / freshness summary
    qa = run_qa_on_results(api_results)
    write_json(RUNTIME_ROOT / "qa" / "morningstar_phase1_qa_summary.json", qa)

    # 4. Failure log (if any)
    failures = {}
    if api_results.get("status") == "success":
        for call_name, call_res in api_results.get("results", {}).items():
            if call_res.get("status") != "success":
                failures[call_name] = call_res.get("error", "unknown")
    elif api_results.get("status") != "skipped":
        failures["subprocess"] = api_results.get("error", api_results.get("stderr", "unknown"))
    write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase1_failure_log.json", {
        "generated_at": utc_now(),
        "failures": failures,
    })

    # 5. License boundary note
    license_note = {
        "generated_at": utc_now(),
        "license_boundary": "needs_user_license_storage_usage_review",
        "raw_storage_mode": "metadata_and_small_sample_only",
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "large_download_performed": False,
        "note": "Phase 1 does not store broad raw Morningstar datasets. Full licensed storage requires explicit user confirmation of entitlement and data-lake path.",
    }
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase1_license_boundary_note.json", license_note)

    # 6. Crosswalk placeholder (identifier mapping summary from samples)
    crosswalk = {
        "generated_at": utc_now(),
        "identifier_crosswalk_candidate": True,
        "source": "morningstar_direct",
        "mapped_fields": {},
        "notes": "Crosswalk requires a larger controlled sample to confirm ticker/ISIN/SecId coverage against exchange/CNINFO/SEC sources.",
    }
    if api_results.get("status") == "success":
        for call_name, call_res in api_results.get("results", {}).items():
            if call_res.get("status") == "success":
                cols = call_res.get("columns", [])
                id_cols = [c for c in cols if any(term in c.lower() for term in ("secid", "isin", "ticker", "symbol", "identifier", "name", "exchange", "currency", "country"))]
                if id_cols:
                    crosswalk["mapped_fields"][call_name] = id_cols
    write_json(RUNTIME_ROOT / "crosswalk" / "morningstar_phase1_identifier_crosswalk.json", crosswalk)

    # 7. Summary stdout
    summary = {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase1",
        "token_available": token_available,
        "token_masked": token_masked,
        "dry_run_completed": True,
        "small_sample_attempted": token_available,
        "small_sample_status": api_results.get("status"),
        "api_calls_succeeded": qa["api_calls_succeeded"],
        "api_calls_failed": qa["api_calls_failed"],
        "blockers": qa["blockers"],
        "outputs": {
            "plan": str(RUNTIME_ROOT / "manifest" / "morningstar_controlled_backfill_phase1_plan.json"),
            "license_note": str(RUNTIME_ROOT / "manifest" / "morningstar_phase1_license_boundary_note.json"),
            "qa_summary": str(RUNTIME_ROOT / "qa" / "morningstar_phase1_qa_summary.json"),
            "failure_log": str(RUNTIME_ROOT / "failure_log" / "morningstar_phase1_failure_log.json"),
            "crosswalk": str(RUNTIME_ROOT / "crosswalk" / "morningstar_phase1_identifier_crosswalk.json"),
            "raw_sample": str(RUNTIME_ROOT / "raw" / "morningstar_phase1_small_sample_raw.json") if token_available else None,
        },
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
    }
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_controlled_backfill_phase1_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
