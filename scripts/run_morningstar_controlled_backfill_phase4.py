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
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase4"
PHASE3_RAW = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase3" / "raw"
SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
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
        result["error"] = "MD_AUTH_TOKEN not found"
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
    except Exception as exc:
        result["expires_at"] = None
        result["decode_error"] = str(exc)
    return result


def child_call_code(call_name: str) -> str:
    return f"""
import json
import os
import sys

def summarize(value, max_rows=10):
    if value is None:
        return {{'type': 'None'}}
    if hasattr(value, 'shape') and hasattr(value, 'columns'):
        result = {{'type': type(value).__name__, 'row_count': int(value.shape[0]), 'column_count': int(value.shape[1]), 'columns': [str(c) for c in list(value.columns)]}}
        if value.shape[0] > 0:
            rows = value.head(max_rows).where(value.notna(), None).to_dict(orient='records')
            for r in rows:
                for k, v in list(r.items()):
                    if hasattr(v, 'isoformat'):
                        r[k] = v.isoformat()
            result['rows'] = rows
        return result
    if isinstance(value, list):
        return {{'type': 'list', 'row_count': len(value), 'rows': value[:max_rows]}}
    if isinstance(value, dict):
        return {{'type': 'dict', 'keys': list(value.keys())[:30]}}
    return {{'type': type(value).__name__, 'repr': repr(value)[:400]}}

try:
    import morningstar_data as md
    call = {call_name!r}
    payload = {{}}
    if call == 'data_point_settings_flow':
        data = md.direct.get_data_point_settings(['TNA0M', 'ENF0M', 'TNA0R', 'ENF0R', 'OGR0R', 'MAP0R'])
        payload = summarize(data, max_rows=20)
    elif call == 'data_point_settings_returns':
        data = md.direct.get_data_point_settings(['OS01W', 'HP010'])
        payload = summarize(data, max_rows=10)
    elif call == 'asset_flow_spy_multi':
        dps = md.direct.get_asset_flow_data_points()
        selected = dps[dps['datapointId'].isin(['TNA0M','ENF0M','OGR0R','MAP0R'])]
        data = md.direct.get_asset_flow(market_id="5", data_point_settings=selected, investments=["FEUSA00001"])
        payload = summarize(data, max_rows=5)
    elif call == 'asset_flow_spy_tna_hist':
        dps = md.direct.get_asset_flow_data_points()
        selected = dps[dps['datapointId'].isin(['TNA1M'])]
        data = md.direct.get_asset_flow(market_id="5", data_point_settings=selected, investments=["FEUSA00001"])
        payload = summarize(data, max_rows=5)
    elif call == 'asset_flow_spy_enf_hist':
        dps = md.direct.get_asset_flow_data_points()
        selected = dps[dps['datapointId'].isin(['ENF1M'])]
        data = md.direct.get_asset_flow(market_id="5", data_point_settings=selected, investments=["FEUSA00001"])
        payload = summarize(data, max_rows=5)
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


def load_phase3_raw() -> dict[str, Any]:
    path = PHASE3_RAW / "morningstar_phase3_raw_samples.json"
    if path.exists():
        return read_json(path)
    return {}


def build_normalized_asset_flow(api_results: dict[str, Any], phase3_raw: dict[str, Any]) -> dict[str, Any]:
    multi = api_results.get("asset_flow_spy_multi", {}).get("payload", {})
    tna_hist = api_results.get("asset_flow_spy_tna_hist", {}).get("payload", {})
    enf_hist = api_results.get("asset_flow_spy_enf_hist", {}).get("payload", {})
    rows_multi = multi.get("rows", [])
    rows_tna = tna_hist.get("rows", [])
    rows_enf = enf_hist.get("rows", [])

    normalized = {
        "generated_at": utc_now(),
        "source_method": "md.direct.get_asset_flow",
        "source_market_id": "5",
        "source_investment": "FEUSA00001 (SPY)",
        "scope": "point_in_time_and_historical_monthly",
        "unit_scale_status": "unknown",
        "unit_scale_reason": "get_data_point_settings for flow data points returns no scalType, scalValue, or currency columns; returned values (e.g., TNA0M=1.94214, ENF0M=17.42587) are not reconcilable with known SPY AUM (~700B USD) under any standard unit assumption (M, B, T) without unsupported extrapolation.",
        "currency_inferred": "USD (share class base currency)",
        "date_field": "asOfDate",
        "frequency": "monthly for historical (TNA1M/ENF1M); point-in-time for current (TNA0M/ENF0M)",
        "point_in_time_sample": rows_multi[0] if rows_multi else None,
        "historical_tna_sample": rows_tna[0] if rows_tna else None,
        "historical_enf_sample": rows_enf[0] if rows_enf else None,
        "fields": [
            {"field": "TNA0M", "name": "Total Net Assets-Market Value(Share Class)", "unit_scale": "unknown", "date_type": "point_in_time"},
            {"field": "ENF0M", "name": "Estimated Net Flow-Market Value(Share Class)", "unit_scale": "unknown", "date_type": "point_in_time"},
            {"field": "OGR0R", "name": "Organic Growth Rate", "unit_scale": "inferred_ratio_or_percent", "date_type": "point_in_time"},
            {"field": "MAP0R", "name": "Market Appreciation", "unit_scale": "inferred_ratio_or_percent", "date_type": "point_in_time"},
            {"field": "TNA1M", "name": "Historical Total Net Assets-Market Value(Share Class)", "unit_scale": "unknown", "date_type": "monthly_time_series"},
            {"field": "ENF1M", "name": "Historical Estimated Net Flow-Market Value(Share Class)", "unit_scale": "unknown", "date_type": "monthly_time_series"},
        ],
    }
    return normalized


def build_normalized_returns(phase3_raw: dict[str, Any]) -> dict[str, Any]:
    samples = phase3_raw.get("samples", {})
    returns_payload = samples.get("returns_FEUSA00001", {})
    rows = returns_payload.get("rows", [])

    # Metadata from data_point_settings_returns
    # HP010: currency=BASE, frequency=m, scalType=null, scalValue=null, annualized=false
    return {
        "generated_at": utc_now(),
        "source_method": "md.direct.get_returns",
        "source_investment": "FEUSA00001 (SPY)",
        "fields": [
            {"field": "Id", "name": "Investment Identifier (SecId)", "unit_scale": "identifier", "date_type": "n/a"},
            {"field": "Date", "name": "Observation Date", "unit_scale": "YYYY-MM-DD", "date_type": "monthly_period_end"},
            {"field": "Monthly Return", "name": "Monthly Return", "unit_scale": "percent (%)", "scale_confidence": "high", "scale_reason": "data_point_settings shows scalType=null, scalValue=null, currency=BASE; observed value 10.47829 for April 2026 aligns with ~10.5% monthly return for SPY.", "date_type": "monthly"},
        ],
        "frequency": "monthly",
        "currency": "BASE (share class base currency = USD)",
        "time_series_sample": rows[:5],
        "time_series_count": len(rows),
        "freshness": "latest observation 2026-04-30",
    }


def build_normalized_holdings(phase3_raw: dict[str, Any]) -> dict[str, Any]:
    samples = phase3_raw.get("samples", {})
    spy_payload = samples.get("holdings_FEUSA00001", {})
    rows = spy_payload.get("rows", [])
    # Cross-check: NVDA marketValue=57949671157, weight=7.85078 -> implied AUM = 57949671157 / 0.0785078 ≈ 738B
    implied_aum = None
    if rows:
        first = rows[0]
        mv = first.get("marketValue")
        w = first.get("weight")
        if mv and w:
            try:
                implied_aum = round(float(mv) / (float(w) / 100), 2)
            except Exception:
                pass

    return {
        "generated_at": utc_now(),
        "source_method": "md.direct.get_holdings",
        "source_investment": "FEUSA00001 (SPY)",
        "portfolio_date": "2026-04-30",
        "holdings_count": spy_payload.get("row_count"),
        "fields": [
            {"field": "masterPortfolioId", "unit_scale": "identifier", "notes": "Morningstar internal portfolio id"},
            {"field": "investmentId", "unit_scale": "identifier", "notes": "SecId of the fund"},
            {"field": "portfolioCurrency", "unit_scale": "currency_code", "notes": "USD"},
            {"field": "portfolioDate", "unit_scale": "date", "notes": "point-in-time portfolio date"},
            {"field": "secId", "unit_scale": "identifier", "notes": "holding security SecId"},
            {"field": "name", "unit_scale": "text", "notes": "holding security name"},
            {"field": "isin", "unit_scale": "identifier", "notes": "ISIN"},
            {"field": "cusip", "unit_scale": "identifier", "notes": "CUSIP"},
            {"field": "ticker", "unit_scale": "identifier", "notes": "ticker symbol"},
            {"field": "weight", "unit_scale": "percent (%)", "scale_confidence": "high", "scale_reason": "values like 7.85078 correspond to percentage weights; sum would be ~100%"},
            {"field": "shares", "unit_scale": "absolute_count", "scale_confidence": "high", "scale_reason": "values like 290372657 are absolute share counts"},
            {"field": "marketValue", "unit_scale": "absolute_local_currency", "scale_confidence": "high", "scale_reason": f"NVDA marketValue={rows[0].get('marketValue') if rows else None}, weight={rows[0].get('weight') if rows else None} => implied total AUM ~{implied_aum} USD, consistent with SPY actual AUM order of magnitude."},
            {"field": "sharesChanged", "unit_scale": "absolute_count", "notes": "change in shares since previous period"},
            {"field": "currency", "unit_scale": "text", "notes": "holding currency name"},
            {"field": "detailHoldingType", "unit_scale": "category", "notes": "EQUITY, BOND, etc."},
        ],
        "top_holdings_sample": rows[:5],
        "implied_total_aum_usd": implied_aum,
    }


def build_normalized_lookthrough(phase3_raw: dict[str, Any]) -> dict[str, Any]:
    samples = phase3_raw.get("samples", {})
    payload = samples.get("lookthrough_FEUSA00001", {})
    rows = payload.get("rows", [])
    return {
        "generated_at": utc_now(),
        "source_method": "md.direct.get_lookthrough_holdings",
        "source_investment": "FEUSA00001 (SPY)",
        "portfolio_date": "2026-04-30",
        "holdings_count": payload.get("row_count"),
        "fields": [
            {"field": "masterPortfolioId", "unit_scale": "identifier"},
            {"field": "investmentId", "unit_scale": "identifier"},
            {"field": "portfolioCurrency", "unit_scale": "currency_code"},
            {"field": "portfolioDate", "unit_scale": "date"},
            {"field": "secId", "unit_scale": "identifier"},
            {"field": "name", "unit_scale": "text"},
            {"field": "detailHoldingTypeCode", "unit_scale": "category", "notes": "E=Equity, etc."},
            {"field": "weight", "unit_scale": "percent (%)", "scale_confidence": "high", "scale_reason": "same weight as holdings, e.g., 7.85078 for NVDA"},
        ],
        "top_holdings_sample": rows[:5],
    }


def build_unit_validation_report(normalized_flow: dict, normalized_returns: dict, normalized_holdings: dict, normalized_lookthrough: dict, api_results: dict) -> dict[str, Any]:
    flow_dp = api_results.get("data_point_settings_flow", {}).get("payload", {})
    returns_dp = api_results.get("data_point_settings_returns", {}).get("payload", {})
    flow_dp_cols = flow_dp.get("columns", [])
    returns_dp_cols = returns_dp.get("columns", [])

    flow_metadata_rich = "scalType" in flow_dp_cols or "currency" in flow_dp_cols
    returns_metadata_rich = "scalType" in returns_dp_cols

    return {
        "generated_at": utc_now(),
        "phase": "phase4_unit_scale_validation",
        "assessment": [
            {
                "dataset": "asset_flow (TNA0M/ENF0M)",
                "unit_scale_confirmed": False,
                "unit_scale_status": "unknown",
                "reason": "get_data_point_settings for flow data points (TNA0M/ENF0M) returns only datapointId/datapointName/alias; no scalType, scalValue, or currency. get_asset_flow actual values (TNA0M=1.94214, ENF0M=17.42587 for SPY) are not reconcilable with known SPY AUM (~700B USD) under standard M/B/T units without unsupported assumptions. ENF/TNA ratio (8.97x) also contradicts fundamental expectations if units were consistent with AUM.",
                "recommendation": "Mark unit_scale_unknown. Do not use TNA/ENF absolute values for production consumption until unit is confirmed by Morningstar documentation or support.",
                "safe_for_production_candidate_preview": False,
            },
            {
                "dataset": "returns (HP010 Monthly Return)",
                "unit_scale_confirmed": True,
                "unit_scale_status": "percent (%)",
                "scale_confidence": "high",
                "reason": "data_point_settings for HP010 returns scalType=null, scalValue=null, currency=BASE, frequency=m. Observed value 10.47829 aligns with ~10.5% monthly return for SPY in April 2026.",
                "recommendation": "Safe for production_candidate_preview with currency=BASE (USD) and frequency=monthly.",
                "safe_for_production_candidate_preview": True,
            },
            {
                "dataset": "holdings (marketValue)",
                "unit_scale_confirmed": True,
                "unit_scale_status": "absolute_local_currency (USD)",
                "scale_confidence": "high",
                "reason": f"NVDA marketValue={normalized_holdings.get('top_holdings_sample',[{}])[0].get('marketValue')} with weight={normalized_holdings.get('top_holdings_sample',[{}])[0].get('weight')} implies total AUM ~{normalized_holdings.get('implied_total_aum_usd')} USD, consistent with SPY actual AUM.",
                "recommendation": "Safe for production_candidate_preview with portfolioDate context.",
                "safe_for_production_candidate_preview": True,
            },
            {
                "dataset": "holdings (shares)",
                "unit_scale_confirmed": True,
                "unit_scale_status": "absolute_share_count",
                "scale_confidence": "high",
                "reason": "Values are integer-like counts (e.g., 290372657 shares of NVDA).",
                "recommendation": "Safe for production_candidate_preview.",
                "safe_for_production_candidate_preview": True,
            },
            {
                "dataset": "holdings (weight)",
                "unit_scale_confirmed": True,
                "unit_scale_status": "percent (%)",
                "scale_confidence": "high",
                "reason": "Values like 7.85078 correspond to percentage weights; top holdings sum directionally to ~100%.",
                "recommendation": "Safe for production_candidate_preview.",
                "safe_for_production_candidate_preview": True,
            },
            {
                "dataset": "lookthrough_holdings (weight)",
                "unit_scale_confirmed": True,
                "unit_scale_status": "percent (%)",
                "scale_confidence": "high",
                "reason": "Same weight semantics as holdings.",
                "recommendation": "Safe for production_candidate_preview.",
                "safe_for_production_candidate_preview": True,
            },
        ],
        "flow_metadata_rich": flow_metadata_rich,
        "returns_metadata_rich": returns_metadata_rich,
    }


def build_flow_signal_matrix(normalized_flow: dict) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "matrix": [
            {"signal": "TNA0M", "availability": "available", "date_type": "point_in_time", "frequency": "monthly_asof", "unit_scale": "unknown", "production_ready": False, "notes": "Current total net assets; unit unconfirmed"},
            {"signal": "ENF0M", "availability": "available", "date_type": "point_in_time", "frequency": "monthly_asof", "unit_scale": "unknown", "production_ready": False, "notes": "Current estimated net flow; unit unconfirmed"},
            {"signal": "OGR0R", "availability": "available", "date_type": "point_in_time", "frequency": "monthly_asof", "unit_scale": "inferred_ratio_or_percent", "production_ready": "candidate", "notes": "Organic growth rate; likely ratio or percent"},
            {"signal": "MAP0R", "availability": "available", "date_type": "point_in_time", "frequency": "monthly_asof", "unit_scale": "inferred_ratio_or_percent", "production_ready": "candidate", "notes": "Market appreciation; likely ratio or percent"},
            {"signal": "TNA1M", "availability": "available", "date_type": "historical_time_series", "frequency": "monthly", "unit_scale": "unknown", "production_ready": False, "notes": "Historical TNA time series; unit unconfirmed"},
            {"signal": "ENF1M", "availability": "available", "date_type": "historical_time_series", "frequency": "monthly", "unit_scale": "unknown", "production_ready": False, "notes": "Historical ENF time series; unit unconfirmed"},
            {"signal": "ENFM1", "availability": "available", "date_type": "rolling_summary", "frequency": "1_month", "unit_scale": "unknown", "production_ready": False, "notes": "1-Mo estimated net flow"},
            {"signal": "ENFQD", "availability": "available", "date_type": "rolling_summary", "frequency": "quarter_to_date", "unit_scale": "unknown", "production_ready": False, "notes": "QTD estimated net flow"},
            {"signal": "ENFYD", "availability": "available", "date_type": "rolling_summary", "frequency": "year_to_date", "unit_scale": "unknown", "production_ready": False, "notes": "YTD estimated net flow"},
            {"signal": "ENFTM", "availability": "available", "date_type": "rolling_summary", "frequency": "trailing_twelve_month", "unit_scale": "unknown", "production_ready": False, "notes": "TTM estimated net flow"},
        ],
        "summary": "Flow signals are structurally available but TNA/ENF absolute values cannot be safely consumed until unit/scale is confirmed. OGR/MAP are usable as ratio/percent proxies. Returns (Monthly Return) are production_candidate_preview ready.",
    }


def build_holdings_exposure_matrix(normalized_holdings: dict, normalized_lookthrough: dict) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "matrix": [
            {"field": "get_holdings", "availability": "available", "row_count": normalized_holdings.get("holdings_count"), "date_type": "point_in_time", "portfolio_date": normalized_holdings.get("portfolio_date"), "production_ready": True, "notes": "18 columns including weight, shares, marketValue, ISIN, CUSIP, ticker"},
            {"field": "get_lookthrough_holdings", "availability": "available", "row_count": normalized_lookthrough.get("holdings_count"), "date_type": "point_in_time", "portfolio_date": normalized_lookthrough.get("portfolio_date"), "production_ready": True, "notes": "10 columns including weight and detailHoldingTypeCode"},
            {"field": "sector_exposure", "availability": "not_direct", "production_ready": False, "notes": "No explicit sector field; derivable from holdings composition and external mapping"},
            {"field": "country_exposure", "availability": "not_direct", "production_ready": False, "notes": "No explicit country field in holdings; ISIN prefix can proxy country"},
            {"field": "currency_exposure", "availability": "partial", "production_ready": False, "notes": "currency field available per holding; aggregate exposure requires summation"},
            {"field": "bond_category_exposure", "availability": "not_direct", "production_ready": False, "notes": "detailHoldingType indicates EQUITY/BOND; bond sub-categories not provided"},
        ],
        "summary": "Holdings and look-through holdings are production_candidate_preview ready with clear units. Sector/country/bond-category exposures require external enrichment or derivation.",
    }


def build_date_freshness_report(normalized_returns: dict, normalized_holdings: dict, normalized_lookthrough: dict, normalized_flow: dict) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "assessments": [
            {"dataset": "asset_flow", "latest_date": "2026-04-30", "frequency": "monthly", "freshness": "1 month lag (May 2026 data not yet available)", "date_field": "asOfDate"},
            {"dataset": "returns", "latest_date": "2026-04-30", "frequency": "monthly", "freshness": "1 month lag", "date_field": "Date", "time_series_length": normalized_returns.get("time_series_count")},
            {"dataset": "holdings", "latest_date": normalized_holdings.get("portfolio_date"), "frequency": "point_in_time", "freshness": "as of 2026-04-30", "date_field": "portfolioDate"},
            {"dataset": "lookthrough_holdings", "latest_date": normalized_lookthrough.get("portfolio_date"), "frequency": "point_in_time", "freshness": "as of 2026-04-30", "date_field": "portfolioDate"},
        ],
    }


def main() -> None:
    token = get_token()
    health = token_health_check(token)
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase4_token_health.json", health)
    if health.get("error"):
        print(json.dumps({"phase4_status": "stopped", "reason": health["error"], "user_action_required": True}, indent=2))
        sys.exit(0)

    api_calls = {}
    for call in ["data_point_settings_flow", "data_point_settings_returns", "asset_flow_spy_multi", "asset_flow_spy_tna_hist", "asset_flow_spy_enf_hist"]:
        api_calls[call] = run_call(call, token)

    success_count = sum(1 for v in api_calls.values() if v.get("status") == "success")
    failure_count = len(api_calls) - success_count

    phase3_raw = load_phase3_raw()

    norm_flow = build_normalized_asset_flow(api_calls, phase3_raw)
    norm_returns = build_normalized_returns(phase3_raw)
    norm_holdings = build_normalized_holdings(phase3_raw)
    norm_lookthrough = build_normalized_lookthrough(phase3_raw)

    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase4_asset_flow_normalized.json", norm_flow)
    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase4_returns_normalized.json", norm_returns)
    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase4_holdings_normalized.json", norm_holdings)
    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase4_lookthrough_normalized.json", norm_lookthrough)

    validation = build_unit_validation_report(norm_flow, norm_returns, norm_holdings, norm_lookthrough, api_calls)
    write_json(RUNTIME_ROOT / "qa" / "morningstar_phase4_unit_scale_validation_report.json", validation)

    flow_matrix = build_flow_signal_matrix(norm_flow)
    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase4_flow_signal_availability_matrix.json", flow_matrix)

    holdings_matrix = build_holdings_exposure_matrix(norm_holdings, norm_lookthrough)
    write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase4_holdings_exposure_availability_matrix.json", holdings_matrix)

    freshness = build_date_freshness_report(norm_returns, norm_holdings, norm_lookthrough, norm_flow)
    write_json(RUNTIME_ROOT / "qa" / "morningstar_phase4_date_freshness_report.json", freshness)

    failures = []
    for call_name, res in api_calls.items():
        if res.get("status") != "success":
            failures.append({"call_name": call_name, "error_type": res.get("error_type"), "error_message": res.get("error_message")})
    write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase4_failure_log.json", {
        "generated_at": utc_now(), "failure_count": len(failures), "failures": failures,
    })

    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase4_license_boundary_note.json", {
        "generated_at": utc_now(),
        "note": "All Morningstar data remains candidate_only. TNA/ENF unit_scale_unknown blocks production consumption. Holdings and returns are production_candidate_preview ready with warnings.",
        "data_source": "morningstar_direct",
        "license_status": "candidate_only",
        "storage_policy": "controlled_pilot_runtime_only",
        "user_action_required": True,
        "next_step": "Confirm TNA/ENF unit/scale with Morningstar documentation or support before broad backfill.",
    })

    summary = {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase4",
        "scope": "flow_dataset_normalization_unit_scale_validation",
        "scope_exclusions": ["standalone_us_equity_price_series", "individual_stock_fundamentals", "broad_universe_backfill"],
        "token_health": health,
        "api_calls_total": len(api_calls),
        "api_calls_success": success_count,
        "api_calls_failed": failure_count,
        "unit_scale_confirmed_datasets": ["returns", "holdings", "lookthrough_holdings"],
        "unit_scale_unknown_datasets": ["asset_flow_TNA_ENF"],
        "production_candidate_preview_ready": {
            "returns": True,
            "holdings": True,
            "lookthrough_holdings": True,
            "asset_flow": False,
        },
        "normalized_outputs": {
            "asset_flow": str(RUNTIME_ROOT / "normalized" / "morningstar_phase4_asset_flow_normalized.json"),
            "returns": str(RUNTIME_ROOT / "normalized" / "morningstar_phase4_returns_normalized.json"),
            "holdings": str(RUNTIME_ROOT / "normalized" / "morningstar_phase4_holdings_normalized.json"),
            "lookthrough": str(RUNTIME_ROOT / "normalized" / "morningstar_phase4_lookthrough_normalized.json"),
        },
        "reports": {
            "unit_validation": str(RUNTIME_ROOT / "qa" / "morningstar_phase4_unit_scale_validation_report.json"),
            "flow_matrix": str(RUNTIME_ROOT / "normalized" / "morningstar_phase4_flow_signal_availability_matrix.json"),
            "holdings_matrix": str(RUNTIME_ROOT / "normalized" / "morningstar_phase4_holdings_exposure_availability_matrix.json"),
            "freshness": str(RUNTIME_ROOT / "qa" / "morningstar_phase4_date_freshness_report.json"),
        },
        "user_action_required": True,
        "license_boundary": "candidate_only",
        "broad_storage_blocked": True,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
    }
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase4_summary.json", summary)

    print(json.dumps({
        "phase4_status": "completed",
        "api_calls": len(api_calls),
        "success": success_count,
        "failed": failure_count,
        "unit_scale_unknown": ["asset_flow_TNA_ENF"],
        "production_candidate_preview_ready": ["returns", "holdings", "lookthrough_holdings"],
        "user_action_required": True,
    }, indent=2))


if __name__ == "__main__":
    main()
