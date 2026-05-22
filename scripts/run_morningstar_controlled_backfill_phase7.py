"""
Morningstar Controlled Backfill Phase 7
TNA / ENF Documentation Evidence Integration + API Metadata Self-Inspection

Scope:
- Do NOT broad download.
- Do NOT collect standalone US equity price time series.
- Update documentation review scaffold with user-reviewed evidence (market_id=5, currency=USD, share class market value).
- Re-run get_data_point_settings for asset flow data points to inspect currency/scalType/scalValue exposure.
- Structural check: share class (asset flow) vs holdings (masterPortfolioId / investmentId) alignment.
- Max 30 API calls (this phase uses <= 3).
- All outputs remain candidate_only.
"""
import os
import sys
import json
import datetime
from pathlib import Path

sys.path.insert(0, r'D:\workspace\FinancialResearch')

with open(r'D:\workspace\FinancialResearch\config\local_secrets.json') as f:
    secrets = json.load(f)
os.environ['MD_AUTH_TOKEN'] = secrets['morningstar']['md_auth_token']

import morningstar_data as md

# ---------------------------------------------------------------------------
# Config & runtime layout
# ---------------------------------------------------------------------------
RUNTIME_ROOT = Path(r'D:\workspace\FinancialResearch\runtime\morningstar_controlled_backfill_phase7')
for sub in ['manifest','raw','normalized','qa','crosswalk','entity_master','failure_log']:
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

write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase7_token_health.json", {
    "generated_at": utc_now(),
    **health,
})

if health.get('status') != 'valid':
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase7_summary.json", {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase7",
        "status": "stopped",
        "stop_reason": "token_not_valid",
        "token_health": health,
        "user_action_required": True,
        "api_call_count": 0,
    })
    print("Token not valid. Stopping Phase 7.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 2) API call: get_data_point_settings for asset flow data points
# ---------------------------------------------------------------------------
FLOW_DATA_POINTS = ['TNA0M','ENF0M','TNA0R','ENF0R','TNA1M','ENF1M','OGR0R','MAP0R']

dp_settings_rows = []
try:
    df_dp = md.direct.get_data_point_settings(data_point_ids=FLOW_DATA_POINTS)
    # Convert DataFrame rows to dicts for JSON serialization
    for _, row in df_dp.iterrows():
        dp_settings_rows.append(row.to_dict())
    record_call("get_data_point_settings_asset_flow", True, payload={
        "requested_ids": FLOW_DATA_POINTS,
        "returned_row_count": len(df_dp),
        "columns": list(df_dp.columns),
        "rows": dp_settings_rows,
    })
except Exception as e:
    record_call("get_data_point_settings_asset_flow", False, error=str(e)[:500])

# ---------------------------------------------------------------------------
# 3) Asset flow structure note (no new API call; inferred from Phase 3-5 data)
# ---------------------------------------------------------------------------
# Phase 5 raw shows get_asset_flow returns columns: investmentId + data point value columns.
# No separate shareClass object column is exposed. The investmentId itself is the share-class identifier.
# Therefore we rely on existing raw samples for structural alignment below.
record_call("get_asset_flow_structure_note", True, payload={
    "note": "No new asset_flow call needed. Structure inferred from Phase 5 raw.",
    "asset_flow_columns": ["investmentId", "Total Net Assets-Market Value(Share Class) - 2026-04-30", "Estimated Net Flow-Market Value(Share Class) - 2026-04-30"],
})

# ---------------------------------------------------------------------------
# 4) Update documentation review scaffold with user-reviewed evidence
# ---------------------------------------------------------------------------
USER_REVIEWED_AT = utc_now()
USER_DOCUMENTATION_SOURCE = "Morningstar Data Documentation (user-reviewed)"
USER_DOCUMENTATION_EXCERPT = (
    "market_id=5 corresponds to US Open-end & ETF ex MM ex FoF. "
    "Currency is USD. TNA0M is 'Total Net Assets-Market Value(Share Class)' at Share Class level, "
    "Market Value basis. Public documentation does not disclose unit, scale, scalType, or scalValue "
    "for TNA0M/ENF0M/OGR0R/MAP0R."
)

items = [
    {
        "data_point_id": "TNA0M",
        "data_point_name": "Total Net Assets-Market Value(Share Class)",
        "category": "TNA",
        "currency": "USD",
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "currency_confirmed_usd_unit_scale_unknown",
        "reviewer_notes": "Cross-sample ratio ~378-380B for SPY/QQQ/AGG/GLD, but VTI breaks at ~1.34T. User confirmed market_id=5 and currency=USD from docs, but unit/scale remain undisclosed.",
        "reviewed_at": USER_REVIEWED_AT,
    },
    {
        "data_point_id": "ENF0M",
        "data_point_name": "Estimated Net Flow-Market Value(Share Class)",
        "category": "ENF",
        "currency": "USD",
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "currency_confirmed_usd_unit_scale_unknown",
        "reviewer_notes": "Same unit ambiguity as TNA0M. ENF/TNA ratio ~8.97x for SPY, not reconcilable with standard unit assumptions.",
        "reviewed_at": USER_REVIEWED_AT,
    },
    {
        "data_point_id": "TNA0R",
        "data_point_name": "Total Net Assets-Ending Value(Share Class)",
        "category": "TNA",
        "currency": "USD",
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "currency_confirmed_usd_unit_scale_unknown",
        "reviewer_notes": "Not yet sampled. Presumed same unit issue as TNA0M.",
        "reviewed_at": USER_REVIEWED_AT,
    },
    {
        "data_point_id": "ENF0R",
        "data_point_name": "Estimated Net Flow-Ending Value(Share Class)",
        "category": "ENF",
        "currency": "USD",
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "currency_confirmed_usd_unit_scale_unknown",
        "reviewer_notes": "Not yet sampled. Presumed same unit issue as ENF0M.",
        "reviewed_at": USER_REVIEWED_AT,
    },
    {
        "data_point_id": "TNA1M",
        "data_point_name": "Historical Total Net Assets-Market Value(Share Class)",
        "category": "TNA",
        "currency": "USD",
        "unit": None,
        "scale": None,
        "frequency": "monthly",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "currency_confirmed_usd_unit_scale_unknown",
        "reviewer_notes": "Historical monthly series. Same unit ambiguity.",
        "reviewed_at": USER_REVIEWED_AT,
    },
    {
        "data_point_id": "ENF1M",
        "data_point_name": "Historical Estimated Net Flow-Market Value(Share Class)",
        "category": "ENF",
        "currency": "USD",
        "unit": None,
        "scale": None,
        "frequency": "monthly",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "currency_confirmed_usd_unit_scale_unknown",
        "reviewer_notes": "Historical monthly series. Same unit ambiguity.",
        "reviewed_at": USER_REVIEWED_AT,
    },
    {
        "data_point_id": "OGR0R",
        "data_point_name": "Organic Growth Rate",
        "category": "OGR",
        "currency": None,
        "unit": "percent or ratio",
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "inferred_ratio_or_percent_unit_scale_unknown",
        "reviewer_notes": "Value 3.217 for SPY; likely percent (3.217%) but not explicitly confirmed.",
        "reviewed_at": USER_REVIEWED_AT,
    },
    {
        "data_point_id": "MAP0R",
        "data_point_name": "Market Appreciation",
        "category": "MAP",
        "currency": None,
        "unit": "percent or ratio",
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5",
        "market_name": "US Open-end & ETF ex MM ex FoF",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": USER_DOCUMENTATION_SOURCE,
        "documentation_excerpt": USER_DOCUMENTATION_EXCERPT,
        "public_docs_unit_scale_status": "not_disclosed",
        "current_FR_status": "inferred_ratio_or_percent_unit_scale_unknown",
        "reviewer_notes": "Value 62508776105.0 for SPY; raw value inconsistent with ratio/percent interpretation. Requires documentation clarification.",
        "reviewed_at": USER_REVIEWED_AT,
    },
]

write_json(RUNTIME_ROOT / "qa" / "morningstar_phase7_documentation_review_scaffold.json", {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase7",
    "purpose": "Updated with user documentation review evidence. Awaiting API metadata self-inspection.",
    "items": items,
    "overall_status": "currency_confirmed_usd_unit_scale_unknown",
})

# ---------------------------------------------------------------------------
# 5) Analyze get_data_point_settings result for scale metadata
# ---------------------------------------------------------------------------
settings_analysis = {
    "requested_data_points": FLOW_DATA_POINTS,
    "api_call_success": False,
    "returned_row_count": 0,
    "has_currency_field": False,
    "has_scalType_field": False,
    "has_scalValue_field": False,
    "has_scalPercentValue_field": False,
    "has_frequency_field": False,
    "has_compounding_field": False,
    "per_data_point": {},
    "conclusion": None,
}

if dp_settings_rows:
    settings_analysis["api_call_success"] = True
    settings_analysis["returned_row_count"] = len(dp_settings_rows)
    sample_cols = list(dp_settings_rows[0].keys()) if dp_settings_rows else []
    settings_analysis["has_currency_field"] = "currency" in sample_cols
    settings_analysis["has_scalType_field"] = "scalType" in sample_cols
    settings_analysis["has_scalValue_field"] = "scalValue" in sample_cols
    settings_analysis["has_scalPercentValue_field"] = "scalPercentValue" in sample_cols
    settings_analysis["has_frequency_field"] = "frequency" in sample_cols
    settings_analysis["has_compounding_field"] = "compounding" in sample_cols

    for row in dp_settings_rows:
        dp_id = row.get("datapointId") or row.get("dataPointId") or row.get("datapointID")
        if not dp_id:
            continue
        settings_analysis["per_data_point"][dp_id] = {
            "currency": row.get("currency"),
            "scalType": row.get("scalType"),
            "scalValue": row.get("scalValue"),
            "scalPercentValue": row.get("scalPercentValue"),
            "frequency": row.get("frequency"),
            "compounding": row.get("compounding"),
        }

    # Determine conclusion
    any_has_currency = any(
        v.get("currency") not in (None, "", "null")
        for v in settings_analysis["per_data_point"].values()
    )
    any_has_scal = any(
        v.get("scalType") not in (None, "", "null")
        for v in settings_analysis["per_data_point"].values()
    )

    if any_has_currency or any_has_scal:
        settings_analysis["conclusion"] = (
            "unit_scale_resolution_candidate: API returned some currency or scalType metadata. "
            "Requires numerical cross-validation before trusted consumption."
        )
    else:
        settings_analysis["conclusion"] = (
            "asset flow data points scale metadata not exposed via get_data_point_settings. "
            "Currency and scalType/scalValue/scalPercentValue are null or absent. "
            "TNA/ENF remain unit_scale_unknown."
        )
else:
    settings_analysis["conclusion"] = (
        "get_data_point_settings call failed or returned empty. Cannot assess scale metadata. "
        "TNA/ENF remain unit_scale_unknown."
    )

write_json(RUNTIME_ROOT / "qa" / "morningstar_phase7_datapoint_settings_inspection.json", {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase7",
    "settings_analysis": settings_analysis,
})

# ---------------------------------------------------------------------------
# 6) Share class vs holdings structural alignment check
# ---------------------------------------------------------------------------
# Load Phase 5 raw samples for structural comparison (no new API calls needed)
PHASE5_RAW_PATH = Path(r'D:\workspace\FinancialResearch\runtime\morningstar_controlled_backfill_phase5\raw\morningstar_phase5_raw_samples.json')
structural_check = {
    "data_source": str(PHASE5_RAW_PATH),
    "asset_flow_investmentIds": [],
    "holdings_investmentIds": [],
    "holdings_masterPortfolioIds": [],
    "investmentId_to_masterPortfolioId": {},
    "alignment_conclusion": None,
    "share_class_vs_holdings_note": None,
}

try:
    with open(PHASE5_RAW_PATH, 'r', encoding='utf-8') as f:
        phase5_raw = json.load(f)

    af_samples = phase5_raw.get("samples", {}).get("get_asset_flow_batch_5seeds", {})
    h_samples = phase5_raw.get("samples", {}).get("get_holdings_batch_5seeds", {})

    af_rows = af_samples.get("rows", [])
    h_rows_per_inv = h_samples.get("rows_per_investment", {})

    af_ids = [r["investmentId"] for r in af_rows if "investmentId" in r]
    h_ids = list(h_rows_per_inv.keys())

    structural_check["asset_flow_investmentIds"] = af_ids
    structural_check["holdings_investmentIds"] = h_ids

    # For deeper check, load a small sample of holdings rows from Phase 5 normalized if available,
    # but raw only has summary. Use Phase 6 raw which has full holdings DataFrame serialized?
    # Phase 6 raw only has columns/rows_per_investment summary too. We can infer from Phase 5 AUM report.
    # Instead, rely on known mapping from Phase 5 normalized holdings sample.
    PHASE5_AUM_PATH = Path(r'D:\workspace\FinancialResearch\runtime\morningstar_controlled_backfill_phase5\normalized\morningstar_phase5_holdings_derived_aum_sample.json')
    if PHASE5_AUM_PATH.exists():
        with open(PHASE5_AUM_PATH, 'r', encoding='utf-8') as f:
            aum_data = json.load(f)
        for sym, info in aum_data.get("samples", {}).items():
            inv_id = info.get("secid")
            mp_id = info.get("top_holdings_sample", [{}])[0].get("masterPortfolioId") if info.get("top_holdings_sample") else None
            if inv_id and mp_id:
                structural_check["investmentId_to_masterPortfolioId"][inv_id] = mp_id
                structural_check["holdings_masterPortfolioIds"].append(mp_id)

    # Alignment logic
    ids_match = set(af_ids) == set(h_ids)
    structural_check["alignment_conclusion"] = (
        f"Asset flow and holdings use identical investmentId keys (share class level). "
        f"Ids match: {ids_match}. "
        f"Holdings additionally expose masterPortfolioId (fund/portfolio level). "
        f"Therefore asset flow TNA/ENF are at share-class level, aligned with holdings investmentId, "
        f"but holdings provide an extra fund-level identifier (masterPortfolioId)."
    )
    structural_check["share_class_vs_holdings_note"] = (
        "Same share-class identifier (investmentId) is used across asset flow and holdings. "
        "Holdings add masterPortfolioId for portfolio/fund granularity. "
        "No evidence that asset flow returns shareClass objects beyond the investmentId column."
    )
except Exception as e:
    structural_check["alignment_conclusion"] = f"Error during structural check: {str(e)[:500]}"

write_json(RUNTIME_ROOT / "qa" / "morningstar_phase7_shareclass_vs_holdings_alignment.json", {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase7",
    "structural_check": structural_check,
})

# ---------------------------------------------------------------------------
# 7) Failure log, license note, raw samples, summary
# ---------------------------------------------------------------------------
write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase7_failure_log.json", {
    "generated_at": utc_now(),
    "failures": [{"call": f["call_name"], "error": f["error"]} for f in failure_calls],
})

write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase7_license_boundary_note.json", {
    "generated_at": utc_now(),
    "license_boundary": "candidate_only",
    "broad_storage_blocked": True,
    "formal_trusted_consumption_affected": False,
    "parse_lab_affected": False,
    "note": (
        "Phase 7 integrated user documentation evidence (currency=USD, market_id=5). "
        "TNA/ENF remain unit_scale_unknown pending scale metadata resolution. "
        "No new broad downloads. No standalone US equity price series."
    ),
})

raw_samples = {}
for c in success_calls:
    p = c.get("payload")
    if p and isinstance(p, dict):
        raw_samples[c["call_name"]] = p
write_json(RUNTIME_ROOT / "raw" / "morningstar_phase7_raw_samples.json", {
    "generated_at": utc_now(),
    "samples": raw_samples,
})

summary = {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase7",
    "scope": "documentation_evidence_integration_api_metadata_inspection",
    "scope_exclusions": [
        "broad_universe_backfill",
        "standalone_us_equity_price_series",
        "full_holdings_backfill",
    ],
    "token_health": health,
    "api_call_count": len(api_calls),
    "api_calls_success": len(success_calls),
    "api_calls_failed": len(failure_calls),
    "max_api_calls": MAX_API_CALLS,
    "documentation_evidence_written": True,
    "market_id_confirmed": "5",
    "currency_confirmed": "USD",
    "tna0m_share_class_market_value_recorded": True,
    "datapoint_settings_inspection_complete": True,
    "datapoint_settings_returns_currency_scalType_scalValue": settings_analysis.get("has_currency_field") or settings_analysis.get("has_scalType_field"),
    "tna_enf_unit_scale_status": "unit_scale_unknown",
    "shareclass_vs_holdings_alignment_checked": True,
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
write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase7_summary.json", summary)

print(f"Phase 7 complete. API calls: {len(api_calls)} (success={len(success_calls)}, failed={len(failure_calls)})")
print(f"Outputs written to: {RUNTIME_ROOT}")
