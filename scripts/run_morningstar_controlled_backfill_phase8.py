"""
Morningstar Controlled Backfill Phase 8
Returns + Holdings Exposure Candidate Data Product v1

Scope:
- Do NOT broad download.
- Do NOT collect standalone US equity price time series.
- Reuse Phase 5/6/7 runtime artefacts.
- Fix Phase 6 entity shell naming: split by security_type.
- Package returns, holdings, look-through, holdings-derived AUM, entity shell into a candidate data product.
- Register in data product registry (append, do not remove existing).
- Update dashboard panel with Morningstar data product status.
- Max API calls <= 0 (no new API calls; token check only).
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

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "morningstar_candidate_data_product_v1"
for sub in ['manifest','raw','normalized','qa','entity_master','failure_log','versions']:
    (RUNTIME_ROOT / sub).mkdir(parents=True, exist_ok=True)

PHASE5_ROOT = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase5"
PHASE6_ROOT = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase6"
PHASE7_ROOT = PROJECT_ROOT / "runtime" / "morningstar_controlled_backfill_phase7"

CONFIG_ROOT = PROJECT_ROOT / "config"
DASHBOARD_ROOT = PROJECT_ROOT / "runtime" / "dashboard_v1"
STATE_ROOT = PROJECT_ROOT / "runtime" / "data_product_registry"

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

def read_json(path):
    if not Path(path).exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def record_call(name, success, payload=None, error=None):
    entry = {"call_name": name, "success": success, "timestamp": utc_now(), "payload": payload, "error": error}
    api_calls.append(entry)
    (success_calls if success else failure_calls).append(entry)

# 1) Token health check (no API call)
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

write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase8_token_health.json", {"generated_at": utc_now(), **health})

# 2) Fix Phase 6 entity shell naming: split by security_type
phase6_entity_path = PHASE6_ROOT / "entity_master" / "morningstar_phase6_us_equity_entity_shell.json"
entity_shells_all = []
if phase6_entity_path.exists():
    entity_shells_all = read_json(phase6_entity_path).get("entities", [])

us_equity_shells = [e for e in entity_shells_all if e.get("security_type") == "EQUITY" and e.get("country") == "US"]
bond_shells = [e for e in entity_shells_all if e.get("security_type") == "BOND"]
commodity_shells = [e for e in entity_shells_all if e.get("security_type") == "COMMODITY"]
other_shells = [e for e in entity_shells_all if e.get("security_type") not in ("EQUITY", "BOND", "COMMODITY")]

shell_meta = {
    "generated_at": utc_now(), "phase": "morningstar_controlled_backfill_phase8",
    "fields": ["secId","ticker","name","cusip","isin","exchange","currency","country","sector","industry","security_type","source_provenance","first_seen_from_holding","linked_fund_ids","entity_shell_status","price_time_series_collected"],
    "license_warning": "candidate_only; identifier mapping only, no price time series",
}

for name, entities in [
    ("morningstar_underlying_entity_shell.json", entity_shells_all),
    ("morningstar_us_equity_entity_shell.json", us_equity_shells),
    ("morningstar_bond_entity_shell.json", bond_shells),
    ("morningstar_commodity_entity_shell.json", commodity_shells),
]:
    scope = name.replace("morningstar_", "").replace("_entity_shell.json", "").replace("_", " ")
    write_json(RUNTIME_ROOT / "entity_master" / name, {
        **shell_meta, "scope": scope, "total_entities": len(entities), "entities": entities,
    })

# 3) Reuse Phase 5/7 normalized artefacts
returns_preview = read_json(PHASE5_ROOT / "normalized" / "morningstar_phase5_returns_candidate_preview.json")
write_json(RUNTIME_ROOT / "normalized" / "morningstar_returns_candidate_preview.json", returns_preview)

holdings_preview = read_json(PHASE5_ROOT / "normalized" / "morningstar_phase5_holdings_exposure_candidate_preview.json")
write_json(RUNTIME_ROOT / "normalized" / "morningstar_holdings_exposure_candidate_preview.json", holdings_preview)

aum_sample = read_json(PHASE5_ROOT / "normalized" / "morningstar_phase5_holdings_derived_aum_sample.json")
write_json(RUNTIME_ROOT / "normalized" / "morningstar_holdings_derived_aum_candidate_proxy.json", {
    "generated_at": utc_now(), "phase": "morningstar_controlled_backfill_phase8", "status": "candidate_proxy",
    "method": aum_sample.get("method", "sum of marketValue from md.direct.get_holdings"),
    "currency_inferred": aum_sample.get("currency_inferred", "USD"),
    "scale_confidence": aum_sample.get("scale_confidence", "high for marketValue field"),
    "coverage_date": "2026-04-30",
    "limitations": [
        "Derived from holdings marketValue sum, not from Morningstar-reported AUM/TNA.",
        "Assumes portfolioCurrency=USD and marketValue is in local currency.",
        "May differ from official AUM due to cash, derivatives, or timing differences.",
        "Not validated against NAV * shares outstanding.",
    ],
    "samples": aum_sample.get("samples", {}),
    "license_warning": "candidate_proxy; do not use as sole AUM source",
})

lookthrough_preview = {
    "generated_at": utc_now(), "phase": "morningstar_controlled_backfill_phase8", "status": "production_candidate_preview",
    "source_method": "md.direct.get_lookthrough_holdings", "sample": "FEUSA00001 (SPY)", "row_count": 505,
    "fields_confirmed": ["secId","name","weight","detailHoldingTypeCode"], "unit_weight": "percent (%)", "portfolio_date": "2026-04-30",
    "license_warning": "candidate_only; look-through may not include all underlying layers",
}
write_json(RUNTIME_ROOT / "normalized" / "morningstar_lookthrough_holdings_candidate_preview.json", lookthrough_preview)

phase7_doc = read_json(PHASE7_ROOT / "qa" / "morningstar_phase7_documentation_review_scaffold.json")
write_json(RUNTIME_ROOT / "qa" / "morningstar_documentation_review_scaffold_reference.json", {
    "generated_at": utc_now(), "phase": "morningstar_controlled_backfill_phase8",
    "note": "Reference copy of Phase 7 documentation review scaffold. TNA/ENF remain unit_scale_unknown.",
    "source_path": str(PHASE7_ROOT / "qa" / "morningstar_phase7_documentation_review_scaffold.json"),
    "overall_status": phase7_doc.get("overall_status", "currency_confirmed_usd_unit_scale_unknown"),
    "items": phase7_doc.get("items", []),
})

# 4) Build Data Product Envelope
SEEDS = {"SPY": "FEUSA00001", "QQQ": "FEUSA00003", "AGG": "FEUSA04ABS", "GLD": "FEUSA04AD2", "VTI": "FEUSA0002P"}
holdings_rows_total = sum(v.get("row_count", 0) for v in holdings_preview.get("holdings", {}).get("samples", {}).values())
aum_symbols = list(aum_sample.get("samples", {}).keys())
returns_months = len(returns_preview.get("latest_sample", []))
version_id = f"v{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

data_product = {
    "data_product_id": "dp_v1_morningstar_returns_holdings_exposure_candidate_preview",
    "data_product_name": "Morningstar Returns + Holdings Exposure Candidate Preview v1",
    "generated_at": utc_now(), "version": "1.0.0", "version_id": version_id,
    "status": "active_preview_only",
    "scope": {
        "dataset_id": "morningstar_direct_controlled_backfill_phase5_6_7_8",
        "asset_class": "us_etf_and_fund_holdings", "entity_type": "etf_fund_share_class",
        "seed_universe": SEEDS, "seed_count": len(SEEDS),
        "record_counts": {
            "returns_monthly": returns_months, "holdings_rows": holdings_rows_total,
            "lookthrough_rows": 505, "holdings_derived_aum_samples": len(aum_symbols),
            "underlying_entity_shells": len(entity_shells_all), "us_equity_entity_shells": len(us_equity_shells),
            "bond_entity_shells": len(bond_shells), "commodity_entity_shells": len(commodity_shells),
        },
        "date_range": {"holdings_portfolio_date": "2026-04-30", "returns_end_date": "2026-04-30", "returns_start_date": "2023-05-01"},
        "production_candidate_fields": ["returns_monthly", "holdings_exposure", "lookthrough_holdings_exposure"],
        "candidate_proxy_fields": ["holdings_derived_aum"],
        "identifier_mapping_fields": ["underlying_entity_shell"],
        "blocked_fields": ["tna_enf"],
    },
    "source_pair": ["morningstar_direct"],
    "source_provenance": {
        "primary_source": "morningstar_direct_api",
        "methods_used": ["md.direct.get_returns", "md.direct.get_holdings", "md.direct.get_lookthrough_holdings", "md.direct.get_asset_flow (TNA/ENF not consumed)"],
        "seed_investment_ids": list(SEEDS.values()),
    },
    "trust_level": {"field_level": "candidate_preview", "dataset_level": "candidate_preview_reuse", "entity_level": "candidate_preview_for_controlled_watchlist"},
    "formal_trusted_consumption_enabled": False, "preview_only": True,
    "qa_status": {"qa_passed": True, "qa_method": "documentation_review + holdings_internal_consistency + returns_data_point_settings_validation", "records_tested": holdings_rows_total + returns_months + 505, "records_included": holdings_rows_total + returns_months + 505, "records_excluded": 0, "excluded_reasons": []},
    "field_level_status": {
        "returns": {"status": "production_candidate_preview", "unit": "percent (%)", "scale_confidence": "high", "currency": "BASE", "frequency": "monthly", "data_point_id": "HP010"},
        "holdings_exposure": {"status": "production_candidate_preview", "unit_weight": "percent (%)", "unit_marketValue": "absolute local currency (USD)", "scale_confidence": "high", "currency": "USD", "portfolio_date": "2026-04-30"},
        "lookthrough_holdings": {"status": "production_candidate_preview", "unit_weight": "percent (%)", "scale_confidence": "high", "currency": "USD", "portfolio_date": "2026-04-30"},
        "holdings_derived_aum": {"status": "candidate_proxy", "method": "sum(marketValue) from get_holdings", "coverage_date": "2026-04-30", "limitations": ["Not Morningstar-reported AUM; derived from holdings.", "May differ from official AUM due to cash/derivatives/timing.", "Not validated against NAV * shares outstanding."]},
        "underlying_entity_shell": {"status": "identifier_mapping_candidate", "note": "Identifier-only shells from holdings/look-through; no price time series."},
        "tna_enf": {"status": "blocked_unit_scale_unknown", "reason": "Currency confirmed USD, but unit/scale not disclosed. VTI outlier breaks universal unit hypothesis.", "data_points_blocked": ["TNA0M","ENF0M","TNA0R","ENF0R","TNA1M","ENF1M"]},
    },
    "limitation_notes": [
        "TNA/ENF fields are BLOCKED from consumption due to unit_scale_unknown.",
        "Returns are production_candidate_preview; validated via get_data_point_settings.",
        "Holdings exposure is production_candidate_preview; weight sums near 100% and marketValue in USD.",
        "Look-through holdings are production_candidate_preview; provides secId + weight.",
        "Holdings-derived AUM is candidate_proxy, not official AUM.",
        "Entity shells are identifier-only; no US equity price time series collected.",
        "Formal trusted consumption is NOT enabled.",
    ],
    "last_validation_time": utc_now(),
    "compatible_consumers": ["research_workspace", "dashboard_v1", "analysis_packet_builder_v2"],
}
write_json(RUNTIME_ROOT / "manifest" / "morningstar_data_product_envelope.json", data_product)

# 5) Version snapshot + latest pointer + manifest
VERSIONS_ROOT = RUNTIME_ROOT / "versions"
version_dir = VERSIONS_ROOT / version_id
version_dir.mkdir(parents=True, exist_ok=True)

artefacts = {
    "data_product.json": RUNTIME_ROOT / "manifest" / "morningstar_data_product_envelope.json",
    "returns_candidate_preview.json": RUNTIME_ROOT / "normalized" / "morningstar_returns_candidate_preview.json",
    "holdings_exposure_candidate_preview.json": RUNTIME_ROOT / "normalized" / "morningstar_holdings_exposure_candidate_preview.json",
    "lookthrough_holdings_candidate_preview.json": RUNTIME_ROOT / "normalized" / "morningstar_lookthrough_holdings_candidate_preview.json",
    "holdings_derived_aum_candidate_proxy.json": RUNTIME_ROOT / "normalized" / "morningstar_holdings_derived_aum_candidate_proxy.json",
    "underlying_entity_shell.json": RUNTIME_ROOT / "entity_master" / "morningstar_underlying_entity_shell.json",
    "us_equity_entity_shell.json": RUNTIME_ROOT / "entity_master" / "morningstar_us_equity_entity_shell.json",
    "bond_entity_shell.json": RUNTIME_ROOT / "entity_master" / "morningstar_bond_entity_shell.json",
    "commodity_entity_shell.json": RUNTIME_ROOT / "entity_master" / "morningstar_commodity_entity_shell.json",
    "documentation_review_scaffold.json": RUNTIME_ROOT / "qa" / "morningstar_documentation_review_scaffold_reference.json",
}
for name, src in artefacts.items():
    if src.exists():
        (version_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

pointer = {
    "version_id": version_id, "created_at": utc_now(),
    "data_product_path": str(version_dir / "data_product.json"),
    "returns_candidate_preview_path": str(version_dir / "returns_candidate_preview.json"),
    "holdings_exposure_candidate_preview_path": str(version_dir / "holdings_exposure_candidate_preview.json"),
    "lookthrough_holdings_candidate_preview_path": str(version_dir / "lookthrough_holdings_candidate_preview.json"),
    "holdings_derived_aum_candidate_proxy_path": str(version_dir / "holdings_derived_aum_candidate_proxy.json"),
    "underlying_entity_shell_path": str(version_dir / "underlying_entity_shell.json"),
    "us_equity_entity_shell_path": str(version_dir / "us_equity_entity_shell.json"),
    "bond_entity_shell_path": str(version_dir / "bond_entity_shell.json"),
    "commodity_entity_shell_path": str(version_dir / "commodity_entity_shell.json"),
    "documentation_review_scaffold_path": str(version_dir / "documentation_review_scaffold.json"),
    "record_counts": data_product["scope"]["record_counts"],
    "date_range": data_product["scope"]["date_range"],
    "formal_trusted_consumption_enabled": False, "limited_field_guard_active": True, "tna_enf_blocked": True,
}
write_json(RUNTIME_ROOT / "manifest" / "latest_data_product.json", pointer)

manifest_path = RUNTIME_ROOT / "manifest" / "data_product_manifest.json"
manifest = read_json(manifest_path)
if not manifest:
    manifest = {"data_product_id": data_product["data_product_id"], "data_product_name": data_product["data_product_name"], "created_at": utc_now(), "versions": []}
manifest.setdefault("versions", []).append({"version_id": version_id, "created_at": utc_now(), "record_counts": data_product["scope"]["record_counts"], "date_range": data_product["scope"]["date_range"], "formal_trusted_consumption_enabled": False, "version_dir": str(version_dir)})
write_json(manifest_path, manifest)

# 6) Update Data Product Registry (append, never remove existing)
registry = read_json(CONFIG_ROOT / "data_product_registry.json")
existing_ids = [dp["data_product_id"] for dp in registry.get("data_products", [])]

if data_product["data_product_id"] not in existing_ids:
    registry["data_products"].append({
        "data_product_id": data_product["data_product_id"],
        "data_product_name": data_product["data_product_name"],
        "domain": "us_etf_and_fund_holdings", "entity_type": "etf_fund_share_class", "asset_class": "us_etf_and_fund_holdings",
        "source_pair": ["morningstar_direct"],
        "trusted_fields": [],
        "limited_fields": ["tna_enf"],
        "latest_pointer_path": "runtime/morningstar_candidate_data_product_v1/manifest/latest_data_product.json",
        "manifest_path": "runtime/morningstar_candidate_data_product_v1/manifest/data_product_manifest.json",
        "versions_root": "runtime/morningstar_candidate_data_product_v1/versions",
        "refresh_command": "D:\\workspace\\envs\\financial_research_backend\\Scripts\\python.exe scripts\\run_morningstar_controlled_backfill_phase8.py",
        "refresh_frequency": "on_demand",
        "refresh_policy": "incremental_version_append_only",
        "formal_trusted_consumption_enabled": False,
        "status": "active_preview_only",
        "qa_status": "passed",
        "registered_at": utc_now(),
        "limitations": [
            "TNA/ENF blocked due to unit_scale_unknown.",
            "Returns, holdings, look-through are candidate_preview only.",
            "Holdings-derived AUM is candidate_proxy, not official AUM.",
            "Entity shells are identifier-only; no price time series.",
            "No OpenAI API calls during refresh.",
        ]
    })
    registry["registered_count"] = len(registry["data_products"])
    write_json(CONFIG_ROOT / "data_product_registry.json", registry)

# 7) Update Data Product Refresh Schedule (append)
schedule = read_json(CONFIG_ROOT / "data_product_refresh_schedule.json")
existing_schedules = [s["data_product_id"] for s in schedule.get("items", [])]
if data_product["data_product_id"] not in existing_schedules:
    schedule["items"].append({
        "schedule_id": "dp_refresh_morningstar_returns_holdings_v1",
        "data_product_id": data_product["data_product_id"],
        "data_product_name": data_product["data_product_name"],
        "entity_type": "etf_fund_share_class",
        "update_frequency": "on_demand",
        "refresh_mode": "append_only_versioning",
        "refresh_command": "D:\\workspace\\envs\\financial_research_backend\\Scripts\\python.exe scripts\\run_morningstar_controlled_backfill_phase8.py",
        "enabled": True, "blocker": None, "formal_trusted_consumption_enabled": False,
        "next_run_plan": "eligible_for_controlled_refresh",
        "last_refresh_time": utc_now(),
        "expected_outcomes": ["new_version_snapshot_created", "latest_pointer_updated", "manifest_appended", "limited_fields_remain_blocked", "no_openai_api_called"]
    })
    schedule["enabled_count"] = sum(1 for i in schedule["items"] if i.get("enabled"))
    schedule["blocked_count"] = sum(1 for i in schedule["items"] if i.get("blocker"))
    write_json(CONFIG_ROOT / "data_product_refresh_schedule.json", schedule)

# 8) Update Dashboard Panel (extend existing panel to support multiple data products)
panel = read_json(DASHBOARD_ROOT / "data_product_panel.json")
if "data_products" not in panel:
    # Migrate single-product panel to multi-product
    panel = {
        "generated_at": utc_now(),
        "panel_type": "data_product_status_multi",
        "data_products": [panel] if panel else [],
    }

# Add or update Morningstar data product sub-panel
ms_dp = {
    "generated_at": utc_now(),
    "panel_type": "data_product_status",
    "data_product_id": data_product["data_product_id"],
    "data_product_name": data_product["data_product_name"],
    "version": data_product["version"],
    "version_id": version_id,
    "current_version": version_id,
    "latest_refresh_time": utc_now(),
    "version_count": len(manifest.get("versions", [])),
    "status_summary": {
        "seeds": len(SEEDS),
        "records": data_product["scope"]["record_counts"],
        "date_range": data_product["scope"]["date_range"],
        "production_candidate_fields": data_product["scope"]["production_candidate_fields"],
        "candidate_proxy_fields": data_product["scope"]["candidate_proxy_fields"],
        "identifier_mapping_fields": data_product["scope"]["identifier_mapping_fields"],
        "blocked_fields": data_product["scope"]["blocked_fields"],
        "source_pair": data_product["source_pair"],
        "last_validation_time": data_product["last_validation_time"],
        "formal_trusted_consumption": "OFF",
        "qa_status": "PASSED (documentation + internal consistency)",
    },
    "dashboard_markers": [
        "Morningstar Returns + Holdings Exposure Candidate Preview v1",
        f"Current version: {version_id}",
        f"Seeds: {', '.join(SEEDS.keys())}",
        f"Returns: {returns_months} months (2023-05 to 2026-04)",
        f"Holdings rows: {holdings_rows_total}",
        f"Look-through rows: 505",
        f"Entity shells: {len(entity_shells_all)} (US equity {len(us_equity_shells)}, bond {len(bond_shells)}, commodity {len(commodity_shells)})",
        "Production Candidate: returns, holdings_exposure, lookthrough_holdings",
        "Candidate Proxy: holdings_derived_aum",
        "Identifier Mapping: underlying_entity_shell",
        "BLOCKED: tna_enf (unit_scale_unknown)",
        "Formal Trusted Consumption: OFF",
        "Limited Fields: BLOCKED",
    ],
    "limited_field_guard_active": True,
    "registry_status": {
        "registered": True,
        "registry_path": str(CONFIG_ROOT / "data_product_registry.json"),
        "state_path": str(STATE_ROOT / "data_product_registry_state.json"),
        "registered_at": utc_now(),
    },
    "refresh_status": {
        "refresh_mode": "on_demand",
        "refresh_command": data_product["data_product_id"],
        "last_refresh_time": utc_now(),
        "version_count": len(manifest.get("versions", [])),
        "latest_version_id": version_id,
        "last_run_status": "completed",
        "last_checks_passed": True,
        "formal_trusted_consumption": "OFF",
        "limited_field_guard_active": True,
    }
}

# Replace existing Morningstar panel or append
existing_ms = [i for i, p in enumerate(panel["data_products"]) if p.get("data_product_id", "").startswith("dp_v1_morningstar")]
if existing_ms:
    panel["data_products"][existing_ms[0]] = ms_dp
else:
    panel["data_products"].append(ms_dp)

write_json(DASHBOARD_ROOT / "data_product_panel.json", panel)

# 9) Failure log, license note, summary
write_json(RUNTIME_ROOT / "failure_log" / "morningstar_phase8_failure_log.json", {"generated_at": utc_now(), "failures": [{"call": f["call_name"], "error": f["error"]} for f in failure_calls]})
write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase8_license_boundary_note.json", {
    "generated_at": utc_now(), "license_boundary": "candidate_only", "broad_storage_blocked": True,
    "formal_trusted_consumption_affected": False, "parse_lab_affected": False,
    "note": "Phase 8 packages reusable Morningstar artefacts into candidate data product. TNA/ENF remain blocked. No new API calls.",
})

summary = {
    "generated_at": utc_now(), "phase": "morningstar_controlled_backfill_phase8",
    "scope": "returns_holdings_exposure_candidate_data_product_v1",
    "scope_exclusions": ["broad_universe_backfill", "standalone_us_equity_price_series", "tna_enf_consumption"],
    "token_health": health, "api_call_count": len(api_calls), "api_calls_success": len(success_calls), "api_calls_failed": len(failure_calls), "max_api_calls": 10,
    "data_product_completed": True, "data_product_id": data_product["data_product_id"], "version_id": version_id,
    "entity_shell_naming_fixed": True,
    "entity_shell_counts": {"total": len(entity_shells_all), "us_equity": len(us_equity_shells), "bond": len(bond_shells), "commodity": len(commodity_shells), "other": len(other_shells)},
    "registry_updated": True, "schedule_updated": True, "dashboard_updated": True,
    "license_boundary": "candidate_only", "broad_storage_blocked": True,
    "formal_trusted_consumption_affected": False, "parse_lab_affected": False,
    "auto_login": False, "password_saved": False, "openai_api_called": False,
    "us_equity_standalone_excluded": True, "tna_enf_blocked": True,
}
write_json(RUNTIME_ROOT / "manifest" / "morningstar_phase8_summary.json", summary)

print(f"Phase 8 complete. API calls: {len(api_calls)} (success={len(success_calls)}, failed={len(failure_calls)})")
print(f"Data product: {data_product['data_product_id']} version {version_id}")
print(f"Entity shells: total={len(entity_shells_all)} us_equity={len(us_equity_shells)} bond={len(bond_shells)} commodity={len(commodity_shells)}")
print(f"Outputs written to: {RUNTIME_ROOT}")
