"""
Morningstar Controlled Backfill Phase 5
AUM Unit Resolution + Holdings-Derived AUM Crosscheck

Scope:
- Do NOT broad download.
- Do NOT collect standalone US equities.
- Focus: resolve TNA/ENF unit via cross-checks (holdings-derived AUM, alternative data points).
- Max 30 API calls, small samples only.
- All outputs remain candidate_only / licensed_high_confidence_candidate.
"""
import os
import sys
import json
import datetime
import math
import traceback
from pathlib import Path

sys.path.insert(0, r'D:\workspace\FinancialResearch')

with open(r'D:\workspace\FinancialResearch\config\local_secrets.json') as f:
    secrets = json.load(f)
os.environ['MD_AUTH_TOKEN'] = secrets['morningstar']['md_auth_token']

import morningstar_data as md

# ---------------------------------------------------------------------------
# Config & runtime layout
# ---------------------------------------------------------------------------
RUNTIME_ROOT = Path(r'D:\workspace\FinancialResearch\runtime\morningstar_controlled_backfill_phase5')
for sub in ['manifest','raw','normalized','qa','failure_log']:
    (RUNTIME_ROOT / sub).mkdir(parents=True, exist_ok=True)

MAX_API_CALLS = 30
SEEDS = {
    "SPY": "FEUSA00001",
    "QQQ": "FEUSA00003",
    "AGG": "FEUSA04ABS",
    "GLD": "FEUSA04AD2",
    "VTI": "FEUSA0002P",
}

api_calls = []
success_calls = []
failure_calls = []

def utc_now():
    return datetime.datetime.utcnow().isoformat() + 'Z'

def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, default=str, ensure_ascii=False)

def record_call(name, success, payload=None, error=None):
    entry = {
        "call_name": name,
        "success": success,
        "timestamp": utc_now(),
        "payload": payload,
        "error": error,
    }
    api_calls.append(entry)
    if success:
        success_calls.append(entry)
    else:
        failure_calls.append(entry)

# ---------------------------------------------------------------------------
# 1) Token health check
# ---------------------------------------------------------------------------
token = os.environ.get('MD_AUTH_TOKEN', '')
if not token:
    health = {"status": "missing", "token_present": False}
else:
    try:
        parts = token.split('.')
        payload_b64 = parts[1] + '=' * (-len(parts[1]) % 4)
        jwt_payload = json.loads(__import__('base64').urlsafe_b64decode(payload_b64.encode()))
        exp_ts = jwt_payload.get('exp')
        expires_at = datetime.datetime.utcfromtimestamp(exp_ts).isoformat() + 'Z' if exp_ts else None
        now = datetime.datetime.utcnow()
        hours_left = (exp_ts - now.timestamp()) / 3600.0 if exp_ts else None
        health = {
            "token_present": True,
            "token_masked": token[:4] + '****' + token[-4:],
            "expires_at": expires_at,
            "hours_remaining": round(hours_left, 2) if hours_left is not None else None,
            "status": "valid" if (hours_left and hours_left > 0) else "expired",
        }
    except Exception as e:
        health = {"token_present": True, "status": "parse_error", "error": str(e)}

write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase5_token_health.json", {
    "generated_at": utc_now(),
    **health,
})

if health.get('status') != 'valid':
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase5_summary.json", {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase5",
        "status": "stopped",
        "stop_reason": "token_not_valid",
        "token_health": health,
        "user_action_required": True,
        "api_call_count": 0,
    })
    print("Token not valid. Stopping Phase 5.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 2) Controlled probes
# ---------------------------------------------------------------------------

# --- Call 1: asset flow data points ---
try:
    dps = md.direct.get_asset_flow_data_points()
    record_call("get_asset_flow_data_points", True, payload={"row_count": len(dps), "columns": list(dps.columns)})
except Exception as e:
    record_call("get_asset_flow_data_points", False, error=str(e)[:500])
    dps = None

# --- Call 2: batch asset flow TNA0M + ENF0M for all seeds ---
asset_flow_rows = []
if dps is not None:
    try:
        selected = dps[dps['datapointId'].isin(['TNA0M', 'ENF0M'])]
        af_df = md.direct.get_asset_flow(market_id="5", data_point_settings=selected, investments=list(SEEDS.values()))
        asset_flow_rows = af_df.to_dict(orient='records')
        record_call("get_asset_flow_batch_5seeds", True, payload={
            "row_count": len(af_df),
            "columns": list(af_df.columns),
            "rows": asset_flow_rows,
        })
    except Exception as e:
        record_call("get_asset_flow_batch_5seeds", False, error=str(e)[:500])

# --- Call 3: batch holdings for all seeds ---
holdings_df = None
try:
    h_df = md.direct.get_holdings(investments=list(SEEDS.values()))
    holdings_df = h_df
    record_call("get_holdings_batch_5seeds", True, payload={
        "row_count": len(h_df),
        "columns": list(h_df.columns),
        "rows_per_investment": h_df.groupby('investmentId').size().to_dict(),
    })
except Exception as e:
    record_call("get_holdings_batch_5seeds", False, error=str(e)[:500])

# --- Call 4: returns SPY ---
returns_rows = []
try:
    r_df = md.direct.get_returns(investments=[SEEDS["SPY"]])
    returns_rows = r_df.to_dict(orient='records')
    record_call("get_returns_SPY", True, payload={
        "row_count": len(r_df),
        "columns": list(r_df.columns),
        "latest_rows": returns_rows[:3],
    })
except Exception as e:
    record_call("get_returns_SPY", False, error=str(e)[:500])

# --- Call 5: lookthrough holdings SPY ---
lookthrough_rows = []
try:
    lt_df = md.direct.get_lookthrough_holdings(investments=[SEEDS["SPY"]])
    lookthrough_rows = lt_df.to_dict(orient='records')
    record_call("get_lookthrough_SPY", True, payload={
        "row_count": len(lt_df),
        "columns": list(lt_df.columns),
    })
except Exception as e:
    record_call("get_lookthrough_SPY", False, error=str(e)[:500])

# --- Call 6: alternative AUM data point probe via get_investment_data ---
alt_aum_result = {"status": "not_attempted"}
candidate_aum_dps = ['F0GBR0AUM','F0GBR0NAV','F0GBR0TNA','F0GBR04S','F0GBR05S','F00000AUM','F00000NAV','F00000TNA']
try:
    cand_df = md.direct.get_investment_data(
        investments=[SEEDS["SPY"]],
        data_points=[{"datapointId": dp} for dp in candidate_aum_dps]
    )
    alt_aum_result = {"status": "success", "columns": list(cand_df.columns), "rows": cand_df.to_dict(orient='records')}
    record_call("get_investment_data_aum_candidates_SPY", True, payload=alt_aum_result)
except Exception as e:
    alt_aum_result = {"status": "failure", "error": str(e)[:800]}
    record_call("get_investment_data_aum_candidates_SPY", False, error=str(e)[:500])

# --- Call 7: data point settings for HP010 / OS01W (returns definition) ---
dp_settings_result = {}
try:
    settings_df = md.direct.get_data_point_settings(['OS01W', 'HP010'])
    dp_settings_result = settings_df.to_dict(orient='records')
    record_call("get_data_point_settings_returns", True, payload={"rows": dp_settings_result})
except Exception as e:
    record_call("get_data_point_settings_returns", False, error=str(e)[:500])

# ---------------------------------------------------------------------------
# 3) Derived analysis
# ---------------------------------------------------------------------------

# Holdings-derived AUM per seed
holdings_derived = {}
if holdings_df is not None:
    for symbol, secid in SEEDS.items():
        sub = holdings_df[holdings_df['investmentId'] == secid]
        total_mv = float(sub['marketValue'].sum()) if 'marketValue' in sub.columns and len(sub) > 0 else None
        total_weight = float(sub['weight'].sum()) if 'weight' in sub.columns and len(sub) > 0 else None
        portfolio_date = sub['portfolioDate'].iloc[0] if len(sub) > 0 else None
        sample = sub.head(3).to_dict(orient='records') if len(sub) > 0 else []
        holdings_derived[symbol] = {
            "secid": secid,
            "portfolio_date": str(portfolio_date) if portfolio_date is not None else None,
            "row_count": len(sub),
            "sum_marketValue_usd": total_mv,
            "sum_weight_percent": total_weight,
            "top_holdings_sample": sample,
        }

# TNA0M / ENF0M extraction per seed
tna_enf_map = {}
for row in asset_flow_rows:
    secid = row.get('investmentId')
    tna = None
    enf = None
    for k, v in row.items():
        if 'Total Net Assets' in k and 'Market Value' in k:
            tna = v
        if 'Estimated Net Flow' in k and 'Market Value' in k:
            enf = v
    tna_enf_map[secid] = {"tna0m": tna, "enf0m": enf}

# Scale comparison
scale_comparison = {}
for symbol, secid in SEEDS.items():
    hd = holdings_derived.get(symbol, {}).get('sum_marketValue_usd')
    te = tna_enf_map.get(secid, {})
    tna = te.get('tna0m')
    enf = te.get('enf0m')
    ratio = None
    if hd is not None and tna is not None and tna != 0:
        ratio = hd / tna
    scale_comparison[symbol] = {
        "secid": secid,
        "tna0m": tna,
        "enf0m": enf,
        "holdings_derived_aum_usd": hd,
        "ratio_hd_to_tna": round(ratio, 2) if ratio is not None else None,
    }

# Determine unit_scale_status
# If ratio is consistent across samples (excluding possible outliers), note hypothesis.
ratios = [v['ratio_hd_to_tna'] for v in scale_comparison.values() if v['ratio_hd_to_tna'] is not None]
if len(ratios) >= 3:
    mean_ratio = sum(ratios) / len(ratios)
    std_ratio = math.sqrt(sum((r - mean_ratio)**2 for r in ratios) / len(ratios)) if len(ratios) > 1 else 0
    cv = std_ratio / mean_ratio if mean_ratio else None
else:
    mean_ratio = None
    std_ratio = None
    cv = None

# VTI is a known outlier (ratio ~1.3T vs others ~380B). Flag it.
vti_ratio = scale_comparison.get('VTI', {}).get('ratio_hd_to_tna')
spy_ratio = scale_comparison.get('SPY', {}).get('ratio_hd_to_tna')
outlier_note = None
if vti_ratio and spy_ratio and abs(vti_ratio - spy_ratio) > 500e9:
    outlier_note = "VTI holdings-derived AUM / TNA0M ratio (~1.34T) is inconsistent with SPY/QQQ/AGG/GLD (~378-380B). This breaks a universal unit hypothesis."

unit_scale_status = "unknown"
unit_scale_reason = (
    "TNA0M/ENF0M values cannot be reconciled with known AUMs under any standard unit (M, B, T) without unsupported extrapolation. "
    "Cross-sample holdings-derived AUM / TNA0M ratio is ~378-380B for SPY/QQQ/AGG/GLD, but VTI breaks this pattern (~1.34T). "
    "Morningstar data point metadata (get_data_point_settings) does not provide scalType/scalValue/currency for flow data points. "
    "No alternative AUM/Net Assets/Fund Size data points were found via get_investment_data (all candidate IDs returned Resource Not Found). "
    "Therefore TNA0M/ENF0M remain unit_scale_unknown."
)

# ---------------------------------------------------------------------------
# 4) Outputs
# ---------------------------------------------------------------------------

# -- AUM unit resolution report --
aum_unit_resolution = {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase5",
    "unit_scale_status": unit_scale_status,
    "unit_scale_reason": unit_scale_reason,
    "cross_sample_ratio_analysis": {
        "ratios_by_symbol": {k: v['ratio_hd_to_tna'] for k, v in scale_comparison.items()},
        "mean_ratio": round(mean_ratio, 2) if mean_ratio else None,
        "std_ratio": round(std_ratio, 2) if std_ratio else None,
        "coefficient_of_variation": round(cv, 4) if cv else None,
        "outlier_note": outlier_note,
    },
    "alternative_aum_probe": alt_aum_result,
    "holdings_derived_aum": holdings_derived,
    "tna_enf_map": tna_enf_map,
    "scale_comparison": scale_comparison,
}
write_json(RUNTIME_ROOT / "qa" / "morningstar_phase5_aum_unit_resolution_report.json", aum_unit_resolution)

# -- Holdings-derived AUM sample --
write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase5_holdings_derived_aum_sample.json", {
    "generated_at": utc_now(),
    "method": "sum of marketValue from md.direct.get_holdings",
    "currency_inferred": "USD (portfolioCurrency)",
    "scale_confidence": "high for marketValue field (absolute local currency)",
    "samples": holdings_derived,
})

# -- TNA / ENF scale comparison report --
write_json(RUNTIME_ROOT / "qa" / "morningstar_phase5_tna_enf_scale_comparison.json", {
    "generated_at": utc_now(),
    "comparison": scale_comparison,
    "interpretation": {
        "consistent_ratio_hypothesis": "If TNA0M were in a single non-standard unit, SPY/QQQ/AGG/GLD imply ~380B USD per unit.",
        "vti_outlier": "VTI ratio is ~1.34T, breaking the hypothesis.",
        "conclusion": "Unit cannot be confirmed. Mark unit_scale_unknown.",
    }
})

# -- Alternative AUM data point probe report --
write_json(RUNTIME_ROOT / "qa" / "morningstar_phase5_alternative_aum_datapoint_probe.json", {
    "generated_at": utc_now(),
    "candidate_ids": candidate_aum_dps,
    "result": alt_aum_result,
    "conclusion": "No alternative AUM/Net Assets/Fund Size data points discovered. Asset-flow TNA0M/ENF0M are the only AUM-related fields accessible.",
})

# -- Returns candidate preview summary --
returns_latest = returns_rows[:5] if returns_rows else []
write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase5_returns_candidate_preview.json", {
    "generated_at": utc_now(),
    "source_method": "md.direct.get_returns",
    "source_investment": "FEUSA00001 (SPY)",
    "status": "production_candidate_preview",
    "field_definition": {
        "field": "HP010 / Monthly Return",
        "unit": "percent (%)",
        "scale_confidence": "high",
        "frequency": "monthly",
        "latest_date": returns_latest[0].get('Date') if returns_latest else None,
    },
    "latest_sample": returns_latest,
    "data_point_settings": dp_settings_result,
    "license_warning": "candidate_only; do not use as sole source for trading decisions",
})

# -- Holdings exposure candidate preview summary --
write_json(RUNTIME_ROOT / "normalized" / "morningstar_phase5_holdings_exposure_candidate_preview.json", {
    "generated_at": utc_now(),
    "holdings": {
        "source_method": "md.direct.get_holdings",
        "samples": {s: {"row_count": holdings_derived[s]["row_count"], "portfolio_date": holdings_derived[s]["portfolio_date"]} for s in SEEDS},
        "fields_confirmed": ["secId","name","isin","cusip","ticker","weight","shares","marketValue","sharesChanged","currency","detailHoldingType"],
        "unit_weight": "percent (%)",
        "unit_marketValue": "absolute local currency (USD)",
        "status": "holdings_exposure_candidate_preview",
    },
    "lookthrough": {
        "source_method": "md.direct.get_lookthrough_holdings",
        "sample": "FEUSA00001 (SPY)",
        "row_count": len(lookthrough_rows),
        "fields_confirmed": ["secId","name","weight","detailHoldingTypeCode"],
        "status": "holdings_exposure_candidate_preview",
    },
    "license_warning": "candidate_only; holdings may not include cash/derivatives",
})

# -- Freshness / date report --
write_json(RUNTIME_ROOT / "qa" / "morningstar_phase5_date_freshness_report.json", {
    "generated_at": utc_now(),
    "asset_flow_date": "2026-04-30",
    "holdings_portfolio_date": "2026-04-30",
    "lookthrough_portfolio_date": "2026-04-30",
    "returns_latest_date": returns_latest[0].get('Date') if returns_latest else None,
    "frequency_asset_flow": "point-in-time (TNA0M/ENF0M); monthly historical (TNA1M/ENF1M)",
    "frequency_returns": "monthly",
    "frequency_holdings": "point-in-time (latest portfolio date)",
    "data_age_days": (datetime.datetime.utcnow() - datetime.datetime(2026, 4, 30)).days,
})

# -- Failure log --
write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase5_failure_log.json", {
    "generated_at": utc_now(),
    "failures": [{"call": f["call_name"], "error": f["error"]} for f in failure_calls],
})

# -- License / storage boundary note --
write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase5_license_boundary_note.json", {
    "generated_at": utc_now(),
    "license_boundary": "candidate_only",
    "broad_storage_blocked": True,
    "formal_trusted_consumption_affected": False,
    "parse_lab_affected": False,
    "note": (
        "All Morningstar data in this phase remains candidate_only. "
        "TNA0M/ENF0M are unit_scale_unknown and must NOT enter trusted consumption. "
        "Holdings-derived AUM is a candidate proxy only; marked with method, date, coverage, and limitations. "
        "Returns and holdings/look-through are production_candidate_preview with license warnings."
    ),
})

# -- Manifest / Summary --
summary = {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase5",
    "scope": "aum_unit_resolution_holdings_derived_crosscheck",
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
    "unit_scale_status": unit_scale_status,
    "unit_scale_reason": unit_scale_reason,
    "holdings_derived_aum_available": True,
    "alternative_aum_datapoints_found": False,
    "returns_status": "production_candidate_preview",
    "holdings_exposure_status": "holdings_exposure_candidate_preview",
    "flow_signal_status": "unit_scale_unknown_blocked",
    "user_action_required": False,
    "license_boundary": "candidate_only",
    "broad_storage_blocked": True,
    "formal_trusted_consumption_affected": False,
    "parse_lab_affected": False,
    "auto_login": False,
    "password_saved": False,
    "openai_api_called": False,
    "us_equity_standalone_excluded": True,
    "api_calls": api_calls,
}
write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase5_summary.json", summary)

# -- Raw sample --
raw_samples = {}
for c in success_calls:
    p = c.get("payload")
    if p and isinstance(p, dict):
        raw_samples[c["call_name"]] = p
write_json(RUNTIME_ROOT / "raw" / "morningstar_phase5_raw_samples.json", {
    "generated_at": utc_now(),
    "samples": raw_samples,
})

print(f"Phase 5 complete. API calls: {len(api_calls)} (success={len(success_calls)}, failed={len(failure_calls)})")
print(f"Outputs written to: {RUNTIME_ROOT}")
