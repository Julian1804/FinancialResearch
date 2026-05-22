"""
Morningstar Controlled Backfill Phase 6
Documentation Check Scaffold + US Equity Entity Shell Design

Scope:
- Do NOT broad download.
- Do NOT collect standalone US equity price time series.
- Build documentation review scaffold for TNA/ENF data points.
- Build US equity entity shell from holdings/look-through holdings (底层对象识别、去重、crosswalk)。
- Max 30 API calls (this phase uses <= 5).
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
RUNTIME_ROOT = Path(r'D:\workspace\FinancialResearch\runtime\morningstar_controlled_backfill_phase6')
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

write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase6_token_health.json", {
    "generated_at": utc_now(),
    **health,
})

if health.get('status') != 'valid':
    write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase6_summary.json", {
        "generated_at": utc_now(),
        "phase": "morningstar_controlled_backfill_phase6",
        "status": "stopped",
        "stop_reason": "token_not_valid",
        "token_health": health,
        "user_action_required": True,
        "api_call_count": 0,
    })
    print("Token not valid. Stopping Phase 6.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 2) API calls: batch holdings (to extract underlying equities)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 3) Documentation review scaffold for TNA / ENF data points
# ---------------------------------------------------------------------------

documentation_review_items = [
    {
        "data_point_id": "TNA0M",
        "data_point_name": "Total Net Assets-Market Value(Share Class)",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "unknown",
        "reviewer_notes": "Cross-sample ratio ~378-380B for SPY/QQQ/AGG/GLD, but VTI breaks at ~1.34T. No scalType from get_data_point_settings.",
        "reviewed_at": None,
    },
    {
        "data_point_id": "ENF0M",
        "data_point_name": "Estimated Net Flow-Market Value(Share Class)",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "unknown",
        "reviewer_notes": "Same unit ambiguity as TNA0M. ENF/TNA ratio ~8.97x for SPY, not reconcilable with standard unit assumptions.",
        "reviewed_at": None,
    },
    {
        "data_point_id": "TNA0R",
        "data_point_name": "Total Net Assets-Ending Value(Share Class)",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "unknown",
        "reviewer_notes": "Not yet sampled. Presumed same unit issue as TNA0M.",
        "reviewed_at": None,
    },
    {
        "data_point_id": "ENF0R",
        "data_point_name": "Estimated Net Flow-Ending Value(Share Class)",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "unknown",
        "reviewer_notes": "Not yet sampled. Presumed same unit issue as ENF0M.",
        "reviewed_at": None,
    },
    {
        "data_point_id": "TNA1M",
        "data_point_name": "Historical Total Net Assets-Market Value(Share Class)",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "monthly",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "unknown",
        "reviewer_notes": "Historical monthly series. Same unit ambiguity.",
        "reviewed_at": None,
    },
    {
        "data_point_id": "ENF1M",
        "data_point_name": "Historical Estimated Net Flow-Market Value(Share Class)",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "monthly",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "unknown",
        "reviewer_notes": "Historical monthly series. Same unit ambiguity.",
        "reviewed_at": None,
    },
    {
        "data_point_id": "OGR0R",
        "data_point_name": "Organic Growth Rate",
        "currency": None,
        "unit": "percent or ratio",
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "inferred_ratio_or_percent",
        "reviewer_notes": "Value 3.217 for SPY; likely percent (3.217%) but not explicitly confirmed.",
        "reviewed_at": None,
    },
    {
        "data_point_id": "MAP0R",
        "data_point_name": "Market Appreciation",
        "currency": None,
        "unit": "percent or ratio",
        "scale": None,
        "frequency": "point-in-time",
        "market_id_scope": "5 (US Market)",
        "share_class_fund_market_scope": "Share Class",
        "documentation_source": "Morningstar Data Documentation (to be reviewed by user)",
        "documentation_excerpt": "",
        "unit_scale_status": "inferred_ratio_or_percent",
        "reviewer_notes": "Value 62508776105.0 for SPY; this raw value is inconsistent with a ratio/percent interpretation. Requires documentation clarification.",
        "reviewed_at": None,
    },
]

write_json(RUNTIME_ROOT / "qa" / "morningstar_phase6_documentation_review_scaffold.json", {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase6",
    "purpose": "Track user documentation review for TNA/ENF data points. Documentation_excerpt to be filled by user after checking Morningstar Data Documentation.",
    "items": documentation_review_items,
    "overall_status": "pending_user_review",
})

# ---------------------------------------------------------------------------
# 4) US Equity Entity Shell from holdings / look-through
# ---------------------------------------------------------------------------

entity_shells = []
crosswalk_entries = []
unique_secids = set()

if holdings_df is not None:
    # Filter to rows that have a ticker (underlying securities typically have tickers)
    # and are not NaN. Also include commodities/bonds for completeness but flag type.
    df = holdings_df.copy()
    # Group by secId to deduplicate across funds
    for secid, group in df.groupby('secId'):
        if secid in unique_secids or str(secid) == 'nan':
            continue
        unique_secids.add(secid)
        row = group.iloc[0]
        ticker = row.get('ticker')
        if str(ticker) == 'nan':
            ticker = None
        name = row.get('name')
        cusip = row.get('cusip')
        if str(cusip) == 'nan':
            cusip = None
        isin = row.get('isin')
        if str(isin) == 'nan':
            isin = None
        currency = row.get('currency')
        if str(currency) == 'nan':
            currency = None
        detail_holding_type = row.get('detailHoldingType')
        sec_type = None
        if isinstance(detail_holding_type, str):
            if 'EQUITY' in detail_holding_type.upper():
                sec_type = 'EQUITY'
            elif 'BOND' in detail_holding_type.upper():
                sec_type = 'BOND'
            elif 'COMMODITY' in detail_holding_type.upper():
                sec_type = 'COMMODITY'
            else:
                sec_type = detail_holding_type.upper()
        # Infer country from ISIN if possible
        country = None
        if isinstance(isin, str) and len(isin) >= 2:
            country = isin[:2]
        # linked fund ids
        linked_funds = group['investmentId'].unique().tolist()
        
        shell = {
            "secId": secid,
            "ticker": ticker,
            "name": name,
            "cusip": cusip,
            "isin": isin,
            "exchange": None,
            "currency": currency,
            "country": country,
            "sector": None,
            "industry": None,
            "security_type": sec_type,
            "source_provenance": "morningstar_direct_get_holdings",
            "first_seen_from_holding": "2026-04-30",
            "linked_fund_ids": linked_funds,
            "entity_shell_status": "candidate_shell",
            "price_time_series_collected": False,
        }
        entity_shells.append(shell)
        
        # Crosswalk entry
        crosswalk_entries.append({
            "secId": secid,
            "ticker": ticker,
            "isin": isin,
            "cusip": cusip,
            "name": name,
            "security_type": sec_type,
            "linked_fund_ids": linked_funds,
            "source": "morningstar_direct",
        })

# Sort by ticker for readability
entity_shells.sort(key=lambda x: (x['ticker'] or '', x['secId']))
crosswalk_entries.sort(key=lambda x: (x['ticker'] or '', x['secId']))

# Count US equities (country == 'US' and security_type == 'EQUITY')
us_equity_count = sum(1 for e in entity_shells if e.get('country') == 'US' and e.get('security_type') == 'EQUITY')
total_entities = len(entity_shells)

write_json(RUNTIME_ROOT / "entity_master" / "morningstar_phase6_us_equity_entity_shell.json", {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase6",
    "scope": "entity_shell_from_holdings_lookthrough",
    "scope_exclusions": [
        "standalone_us_equity_price_series",
        "individual_stock_fundamentals",
        "broad_universe_backfill",
    ],
    "total_entities": total_entities,
    "us_equity_entities": us_equity_count,
    "fields": [
        "secId","ticker","name","cusip","isin","exchange","currency","country",
        "sector","industry","security_type","source_provenance","first_seen_from_holding",
        "linked_fund_ids","entity_shell_status","price_time_series_collected"
    ],
    "entities": entity_shells,
    "license_warning": "candidate_only; entity shells are identifiers only, no price time series",
})

write_json(RUNTIME_ROOT / "crosswalk" / "morningstar_phase6_identifier_crosswalk.json", {
    "generated_at": utc_now(),
    "crosswalk": crosswalk_entries,
})

# ---------------------------------------------------------------------------
# 5) Other outputs
# ---------------------------------------------------------------------------

# Failure log
write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase6_failure_log.json", {
    "generated_at": utc_now(),
    "failures": [{"call": f["call_name"], "error": f["error"]} for f in failure_calls],
})

# License / storage boundary note
write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase6_license_boundary_note.json", {
    "generated_at": utc_now(),
    "license_boundary": "candidate_only",
    "broad_storage_blocked": True,
    "formal_trusted_consumption_affected": False,
    "parse_lab_affected": False,
    "note": (
        "Documentation review scaffold is a tracking artifact only. "
        "US equity entity shells are identifier-only shells derived from holdings; no price time series collected. "
        "TNA/ENF remain unit_scale_unknown until user completes documentation review."
    ),
})

# Summary / Manifest
summary = {
    "generated_at": utc_now(),
    "phase": "morningstar_controlled_backfill_phase6",
    "scope": "documentation_review_scaffold_us_equity_entity_shell",
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
    "documentation_review_scaffold_complete": True,
    "documentation_review_status": "pending_user_review",
    "us_equity_entity_shell_complete": True,
    "us_equity_entity_count": us_equity_count,
    "total_entity_shell_count": total_entities,
    "price_time_series_collected": False,
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
write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase6_summary.json", summary)

# Raw sample
raw_samples = {}
for c in success_calls:
    p = c.get("payload")
    if p and isinstance(p, dict):
        raw_samples[c["call_name"]] = p
write_json(RUNTIME_ROOT / "raw" / "morningstar_phase6_raw_samples.json", {
    "generated_at": utc_now(),
    "samples": raw_samples,
})

print(f"Phase 6 complete. API calls: {len(api_calls)} (success={len(success_calls)}, failed={len(failure_calls)})")
print(f"Total entity shells: {total_entities} (US equity: {us_equity_count})")
print(f"Outputs written to: {RUNTIME_ROOT}")
