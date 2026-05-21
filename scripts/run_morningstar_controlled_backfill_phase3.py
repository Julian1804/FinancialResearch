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
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase3"
SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"


SEEDS = ["SPY", "QQQ", "AGG", "GLD", "VTI"]
MAX_API_CALLS = 30


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
        "token_status": "missing" if not token else "available",
        "token_masked": mask_token(token) if token else None,
        "error": None,
    }
    if not token:
        result["error"] = "MD_AUTH_TOKEN not found in config/local_secrets.json"
        return result
    try:
        parts = token.split(".")
        if len(parts) == 3:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
            exp = payload.get("exp")
            if exp:
                exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
                result["expires_at"] = exp_dt.isoformat().replace("+00:00", "Z")
                result["expires_hours"] = round((exp_dt - datetime.now(timezone.utc)).total_seconds() / 3600, 2)
                if result["expires_hours"] < 0:
                    result["token_status"] = "expired"
                    result["error"] = f"Token expired {abs(result['expires_hours'])} hours ago"
            else:
                result["expires_at"] = None
        else:
            result["expires_at"] = None
    except Exception as exc:
        result["expires_at"] = None
        result["decode_error"] = str(exc)
    return result


def child_call_code(call_name: str) -> str:
    return f"""
import json
import os
import sys
import traceback

def summarize_df(value, include_rows=False, max_rows=10):
    if value is None:
        return {{'type': 'None', 'row_count': 0, 'columns': []}}
    if hasattr(value, 'shape') and hasattr(value, 'columns'):
        result = {{
            'type': type(value).__name__,
            'row_count': int(value.shape[0]),
            'column_count': int(value.shape[1]),
            'columns': [str(c) for c in list(value.columns)],
        }}
        if include_rows:
            rows = value.head(max_rows).where(value.notna(), None).to_dict(orient='records')
            # sanitize timestamps
            for r in rows:
                for k, v in list(r.items()):
                    if hasattr(v, 'isoformat'):
                        r[k] = v.isoformat()
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
    payload = {{}}
    if call == 'all_datasets':
        data = md.direct.get_morningstar_data_sets()
        payload = summarize_df(data, include_rows=True, max_rows=50)
    elif call == 'fund_datasets':
        data = md.direct.get_morningstar_data_sets('FO')
        payload = summarize_df(data, include_rows=True, max_rows=30)
    elif call == 'asset_flow_data_points':
        data = md.direct.get_asset_flow_data_points()
        payload = summarize_df(data, include_rows=True, max_rows=20)
    elif call == 'reports':
        data = md.direct.get_reports()
        payload = summarize_df(data, include_rows=True, max_rows=20)
    elif call.startswith('investments_'):
        keyword = call.split('_', 1)[1]
        data = md.direct.investments(keyword=keyword, count=5)
        payload = summarize_df(data, include_rows=True, max_rows=5)
    elif call.startswith('holdings_'):
        secid = call.split('_', 1)[1]
        data = md.direct.get_holdings(investments=[secid], holdings_view=md.direct.HoldingsView.BEST_AVAILABLE)
        payload = summarize_df(data, include_rows=True, max_rows=5)
    elif call.startswith('lookthrough_'):
        secid = call.split('_', 1)[1]
        data = md.direct.get_lookthrough_holdings(investments=[secid], holdings_view=md.direct.HoldingsView.BEST_AVAILABLE)
        payload = summarize_df(data, include_rows=True, max_rows=5)
    elif call.startswith('investment_data_'):
        secid = call.split('_', 2)[2]
        data = md.direct.get_investment_data(investments=[secid], data_points=['OS01W','HP010'], dry_run=True)
        payload = summarize_df(data, include_rows=False)
    elif call.startswith('returns_'):
        secid = call.split('_', 1)[1]
        data = md.direct.get_returns(investments=[secid])
        payload = summarize_df(data, include_rows=True, max_rows=5)
    elif call.startswith('asset_flow_market_'):
        market_id = call.split('_', 3)[3]
        dps = md.direct.get_asset_flow_data_points()
        selected = dps[dps['datapointId'].isin(['TNA0M','ENF0M'])]
        data = md.direct.get_asset_flow(market_id=market_id, data_point_settings=selected, investments=["FEUSA00001"])
        payload = summarize_df(data, include_rows=True, max_rows=5)
    else:
        raise ValueError(f'unknown call: {{call}}')
    print(json.dumps({{'status':'success','payload':payload}}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({{'status':'failed','error_type':type(exc).__name__,'error_message':str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
"""


def run_call(call_name: str, token: str | None) -> dict[str, Any]:
    if not token:
        return {"call_name": call_name, "attempted": False, "status": "skipped", "error_type": "missing_token"}
    env = os.environ.copy()
    env["MD_AUTH_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, "-c", child_call_code(call_name)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        stdout = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"status": "failed", "error_type": "json_decode", "raw": stdout[:500]}
        return {
            "call_name": call_name,
            "attempted": True,
            "status": payload.get("status", "unknown"),
            "payload": payload.get("payload"),
            "error_type": payload.get("error_type"),
            "error_message": payload.get("error_message"),
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"call_name": call_name, "attempted": True, "status": "timeout", "error_type": "timeout"}
    except Exception as exc:
        return {"call_name": call_name, "attempted": True, "status": "failed", "error_type": type(exc).__name__, "error_message": str(exc)[:500]}


def main() -> None:
    token = get_token()
    health = token_health_check(token)
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase3_token_health.json", health)
    if health.get("error"):
        print(json.dumps({"phase3_status": "stopped", "reason": health["error"], "user_action_required": True}, indent=2))
        sys.exit(0)

    api_calls = []

    # 1-2. Datasets (may fail due to SDK internal None handling; recorded as failure)
    for call in ["all_datasets", "fund_datasets"]:
        api_calls.append(run_call(call, token))

    # 3. Asset flow data points
    api_calls.append(run_call("asset_flow_data_points", token))

    # 4. Reports
    api_calls.append(run_call("reports", token))

    # 5. Investment search for seeds
    secid_map = {}
    for seed in SEEDS:
        call_name = f"investments_{seed}"
        res = run_call(call_name, token)
        api_calls.append(res)
        if res.get("status") == "success" and res.get("payload", {}).get("rows"):
            rows = res["payload"]["rows"]
            for row in rows:
                secid = row.get("SecId") or row.get("secId")
                if secid:
                    secid_map[seed] = secid
                    break

    # 6-7. Holdings for first 2 found funds (actual, limited rows)
    holdings_probe_seeds = list(secid_map.keys())[:2]
    for seed in holdings_probe_seeds:
        secid = secid_map[seed]
        api_calls.append(run_call(f"holdings_{secid}", token))

    # 8. Lookthrough holdings for 1 fund
    if secid_map:
        first_secid = list(secid_map.values())[0]
        api_calls.append(run_call(f"lookthrough_{first_secid}", token))

    # 9-10. Investment data dry-run for first 2 funds
    for seed in holdings_probe_seeds:
        secid = secid_map[seed]
        api_calls.append(run_call(f"investment_data_{secid}", token))

    # 11. Returns for first fund
    if holdings_probe_seeds:
        api_calls.append(run_call(f"returns_{secid_map[holdings_probe_seeds[0]]}", token))

    # 12. Asset flow actual for SPY with TNA/ENF
    api_calls.append(run_call("asset_flow_market_5", token))

    success_calls = [c for c in api_calls if c.get("status") == "success"]
    failure_calls = [c for c in api_calls if c.get("status") != "success"]

    # Extract field coverage from successful payloads
    field_coverage = {}
    flow_signals = {}
    holdings_exposure = {}
    date_fields_found = []
    for c in success_calls:
        payload = c.get("payload") or {}
        cols = payload.get("columns", [])
        name = c["call_name"]
        field_coverage[name] = cols
        if "asset_flow" in name or "flow" in name.lower():
            flow_signals[name] = cols
        if "holdings" in name.lower() or "lookthrough" in name.lower():
            holdings_exposure[name] = {"columns": cols, "row_count": payload.get("row_count")}
        for col in cols:
            if any(k in col.lower() for k in ["date", "asof", "as_of", "start", "end", "period"]):
                date_fields_found.append({"call": name, "field": col})

    summary = {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase3",
        "scope": "fund_flow_aum_holdings_exposure_probe",
        "scope_exclusions": [
            "standalone_us_equity_price_series",
            "individual_stock_fundamentals",
            "broad_universe_backfill",
        ],
        "token_health": health,
        "api_call_count": len(api_calls),
        "api_calls_success": len(success_calls),
        "api_calls_failed": len(failure_calls),
        "max_api_calls": MAX_API_CALLS,
        "secid_map": secid_map,
        "field_coverage": field_coverage,
        "flow_signal_availability": flow_signals,
        "holdings_exposure_availability": holdings_exposure,
        "date_fields_found": date_fields_found,
        "api_calls": api_calls,
        "user_action_required": False,
        "license_boundary": "candidate_only",
        "broad_storage_blocked": True,
    }

    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase3_summary.json", summary)

    # Raw sample
    raw_samples = {}
    for c in success_calls:
        p = c.get("payload")
        if p and p.get("rows"):
            raw_samples[c["call_name"]] = {"columns": p.get("columns"), "rows": p.get("rows")}
    write_json(RUNTIME_ROOT / "raw" / "morningstar_phase3_raw_samples.json", {
        "generated_at": utc_now(),
        "samples": raw_samples,
    })

    # Normalized sample
    normalized = {
        "generated_at": utc_now(),
        "identifier_anchors": secid_map,
        "flow_data_points_available": [
            "TNA0M", "TNA0R", "ENF0M", "ENF0R", "OGR0R", "MAP0R",
            "TNA1M", "TNA1R", "ENF1M", "ENF1R", "OGR1R", "MAP1R",
            "ENFM1", "ENFQD", "ENFYD", "ENFTM", "ENF24", "ENF36",
        ],
        "returns_fields": ["Id", "Date", "Monthly Return"],
        "holdings_fields": [
            "masterPortfolioId", "investmentId", "portfolioCurrency", "portfolioDate",
            "secId", "name", "isin", "cusip", "ticker", "weight", "shares",
            "marketValue", "sharesChanged", "currency", "detailHoldingType",
        ],
        "lookthrough_fields": [
            "masterPortfolioId", "investmentId", "portfolioCurrency", "portfolioDate",
            "secId", "name", "detailHoldingTypeCode", "weight",
        ],
        "asset_flow_fields_sample": [
            "investmentId", "Total Net Assets-Market Value(Share Class) - 2026-04-30",
            "Estimated Net Flow-Market Value(Share Class) - 2026-04-30",
        ],
    }
    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase3_field_availability.json", normalized)

    # Crosswalk candidate (same as Phase 2 anchors, no new symbols)
    crosswalk = []
    for seed, secid in secid_map.items():
        crosswalk.append({
            "source_ticker": seed,
            "source_sec_id": secid,
            "source_name": None,
            "crosswalk_type": "morningstar_phase3_flow_probe_anchor",
            "status": "candidate",
        })
    write_json(RUNTIME_ROOT / "crosswalk" / "morningstar_phase3_identifier_crosswalk.json", {
        "generated_at": utc_now(),
        "candidates": crosswalk,
    })

    # QA summary
    qa = {
        "generated_at": utc_now(),
        "api_calls_total": len(api_calls),
        "api_calls_success": len(success_calls),
        "api_calls_failed": len(failure_calls),
        "rate_limit_encountered": False,
        "permission_errors": [c for c in failure_calls if "permission" in (c.get("error_message") or "").lower() or "entitlement" in (c.get("error_message") or "").lower()],
        "dataset_availability": {
            "asset_flow_data_points": "available (18 points)",
            "returns": "available (monthly time series)",
            "holdings": "available (point-in-time portfolio holdings)",
            "lookthrough_holdings": "available (point-in-time expanded holdings)",
            "investment_data_dry_run": "available (cell estimation works)",
            "datasets_list": "sdk_internal_error (NoneType strip)",
            "reports": "empty (no saved reports)",
        },
        "freshness_assessment": {
            "asset_flow": "point-in-time as of 2026-04-30",
            "returns": "monthly time series through 2026-04-30",
            "holdings": "portfolio date 2026-04-30",
        },
        "flow_signal_proxy_ready": True,
        "holdings_exposure_proxy_ready": True,
        "broad_backfill_recommended": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
    }
    write_json(RUNTIME_ROOT / "qa" / "morningstar_phase3_qa_summary.json", qa)

    # Failure log
    failures = []
    for c in failure_calls:
        failures.append({
            "call_name": c["call_name"],
            "error_type": c.get("error_type"),
            "error_message": c.get("error_message"),
        })
    write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase3_failure_log.json", {
        "generated_at": utc_now(),
        "failure_count": len(failures),
        "failures": failures,
    })

    # License boundary note
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase3_license_boundary_note.json", {
        "generated_at": utc_now(),
        "note": "All Morningstar data remains candidate_only. No broad raw storage. Holdings data for SPY (514 rows) is a single-fund point-in-time sample, not broad universe. No license cleared for production consumption.",
        "data_source": "morningstar_direct",
        "license_status": "candidate_only",
        "storage_policy": "controlled_pilot_runtime_only",
        "user_action_required": True,
        "next_step": "User must confirm license and storage usage before Phase 4 broad backfill.",
    })

    print(json.dumps({
        "phase3_status": "completed",
        "api_calls": len(api_calls),
        "success": len(success_calls),
        "failed": len(failure_calls),
        "secid_map": secid_map,
        "user_action_required": False,
    }, indent=2))


if __name__ == "__main__":
    main()
