"""Merge offline-scaffold field inventory with API-validated fields from rerun."""
import json
from pathlib import Path

RAW_BASE = Path("Z:/data_lake_master/raw/licensed/morningstar")
LOCAL_STATE_BASE = Path(r"D:\workspace\FinancialResearch\runtime\morningstar_full_backfill_state")
LOCAL_RUNTIME_BASE = Path(r"D:\workspace\FinancialResearch\runtime\morningstar_full_backfill")
RUN_DATE = "20260522"

raw_files = [
    RAW_BASE / RUN_DATE / "search_etf_raw.json",
    RAW_BASE / RUN_DATE / "search_mutual_fund_raw.json",
    RAW_BASE / RUN_DATE / "search_bond_fund_raw.json",
    RAW_BASE / RUN_DATE / "search_commodity_fund_raw.json",
    RAW_BASE / RUN_DATE / "search_index_fund_raw.json",
    RAW_BASE / RUN_DATE / "holdings_batch_0_raw.json",
    RAW_BASE / RUN_DATE / "holdings_batch_1_raw.json",
    RAW_BASE / RUN_DATE / "returns_batch_0_raw.json",
    RAW_BASE / RUN_DATE / "returns_batch_1_raw.json",
    RAW_BASE / RUN_DATE / "batch2a" / "search_etf_raw.json",
    RAW_BASE / RUN_DATE / "batch2a" / "search_mutual_fund_raw.json",
    RAW_BASE / RUN_DATE / "batch2a" / "search_bond_fund_raw.json",
    RAW_BASE / RUN_DATE / "batch2a" / "search_commodity_fund_raw.json",
    RAW_BASE / RUN_DATE / "batch2a" / "search_index_fund_raw.json",
    RAW_BASE / RUN_DATE / "batch2a" / "holdings_sample_raw.json",
    RAW_BASE / RUN_DATE / "batch2a" / "returns_sample_raw.json",
]

all_fields = set()
for p in raw_files:
    if not p.exists():
        continue
    try:
        data = json.load(open(p, encoding='utf-8'))
        rows = data.get("rows", []) or data.get("sample", []) or []
        for r in rows:
            if isinstance(r, dict):
                all_fields.update(r.keys())
    except Exception:
        pass

def classify_semantic_group(field_name: str) -> str | None:
    fn = field_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    if fn in ("stepsize", "windowsize", "scaltype", "scalvalue", "scalpercentvalue"):
        return None
    if "fundsize" in fn or ("totalnetassets" in fn and "share" not in fn):
        return "fund_level_size"
    if "netassets" in fn and ("share" in fn or "class" in fn):
        return "shareclass_level_size"
    if "vehicleassets" in fn or "trustassets" in fn or "separateaccountassets" in fn:
        return "vehicle_or_trust_level_size"
    if "portfolioassets" in fn:
        return "portfolio_level_size"
    if "marketvalue" in fn and "holding" in fn:
        return "holdings_derived_size_proxy"
    if "nav" in fn or "shareprice" in fn:
        return "nav_or_share_price"
    if "return" in fn or "trailing" in fn or "calendar" in fn or "annual" in fn:
        return "returns"
    if "weight" in fn or "allocation" in fn:
        return "holdings_weight"
    if "marketvalue" in fn:
        return "holdings_market_value"
    if any(x in fn for x in ["secid", "investmentid", "fundid", "performanceid", "portfolioid", "masterportfolioid"]):
        if "holding" in fn:
            return "holding_identifier"
        if "performance" in fn:
            return "performance_identifier"
        if "portfolio" in fn or "masterportfolio" in fn:
            return "portfolio_identifier"
        return "shareclass_identifier" if "secid" in fn else "fund_identifier"
    if any(x in fn for x in ["isin", "cusip", "ticker", "exchange", "currency", "domicile", "securitytype"]):
        if "holding" in fn:
            return "holding_identifier"
        return "shareclass_identifier"
    if "firm" in fn or "company" in fn or "provider" in fn or "advisor" in fn:
        return "organization_identifier"
    if "universe" in fn or "exposure" in fn:
        return "exposure_scope"
    if "region" in fn or "country" in fn:
        return "region_country_exposure"
    if "sector" in fn or "industry" in fn:
        return "sector_industry_exposure"
    if "assetclass" in fn or "category" in fn or "broadgroup" in fn:
        return "asset_class"
    if "name" in fn or "inception" in fn or "status" in fn or "date" in fn or "type" in fn or "legal" in fn:
        return "master_metadata"
    return "unclassified"

def classify_size_measure_type(field_name: str) -> str | None:
    fn = field_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    if fn in ("stepsize", "windowsize", "scaltype", "scalvalue", "scalpercentvalue"):
        return None
    if "fundsize" in fn or ("totalnetassets" in fn and "share" not in fn):
        return "fund_size"
    if "netassets" in fn and ("share" in fn or "class" in fn):
        return "shareclass_net_assets"
    if "vehicleassets" in fn or "trustassets" in fn or "separateaccountassets" in fn:
        return "vehicle_or_trust_assets"
    if "marketvalue" in fn and "holding" in fn:
        return "holdings_derived_aum"
    if any(x in fn for x in ["assets", "aum", "portfolioassets", "size"]):
        return "unknown_or_blocked"
    return None

# Build scanned fields
scanned = {}
for f in sorted(all_fields):
    sg = classify_semantic_group(f)
    if sg is None:
        continue
    scanned[f] = {
        "raw_field_id": f,
        "raw_field_name": f,
        "definition": None,
        "product_scope": ["unknown"],
        "entity_level": "unknown",
        "semantic_group": sg,
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "unknown",
        "as_of_date_field": None,
        "source_method": ["unknown"],
        "sample_value": None,
        "validation_status": "field_name_match_only",
        "reviewer_notes": "Scanned from existing raw data (Batch 1 / 2A).",
        "size_measure_type": classify_size_measure_type(f),
        "source_dataset": "raw_scan",
    }

# Load current API-validated inventory
api_inv = json.load(open(LOCAL_STATE_BASE / "morningstar_full_field_inventory_batch2b.json", encoding='utf-8'))
api_fields = {f["raw_field_name"]: f for f in api_inv["fields"]}

# Known Direct definitions that should always be present
direct_fields = {
    "Fund Size": {
        "raw_field_id": "FundSize",
        "raw_field_name": "Fund Size",
        "definition": "The total amount of money managed as a standalone portfolio across share classes that existed as of the Fund Size Date.",
        "product_scope": ["fund", "etf", "shareclass"],
        "entity_level": "fund",
        "semantic_group": "fund_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "snapshot",
        "as_of_date_field": "Fund Size Date",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Validated via API dataset discovery. datapointId=OF009.",
        "size_measure_type": "fund_size",
        "source_dataset": "0026-0020",
    },
    "Net Assets - Share Class": {
        "raw_field_id": "NetAssetsShareClass",
        "raw_field_name": "Net Assets - Share Class",
        "definition": "Net assets recorded in unit of base currency at share class level.",
        "product_scope": ["shareclass"],
        "entity_level": "shareclass",
        "semantic_group": "shareclass_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "snapshot",
        "as_of_date_field": "NetAssetsDate",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Validated via API dataset discovery. datapointId=OS013.",
        "size_measure_type": "shareclass_net_assets",
        "source_dataset": "0026-0020",
    },
    "Vehicle Assets": {
        "raw_field_id": "VehicleAssets",
        "raw_field_name": "Vehicle Assets",
        "definition": "The total amount of money managed as a standalone portfolio across all tiers or share classes in the Trust.",
        "product_scope": ["trust", "vehicle", "separate_account"],
        "entity_level": "vehicle_or_trust",
        "semantic_group": "vehicle_or_trust_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "snapshot",
        "as_of_date_field": "VehicleAssetsDate",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known from user-provided documentation. Pending API sample value validation.",
        "size_measure_type": "vehicle_or_trust_assets",
        "source_dataset": "direct_definition",
    },
    "NAV": {
        "raw_field_id": "NAV",
        "raw_field_name": "NAV",
        "definition": "Most recent net asset value / share price, calculated daily by total net assets divided by total shares.",
        "product_scope": ["shareclass", "fund"],
        "entity_level": "shareclass",
        "semantic_group": "nav_or_share_price",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily",
        "as_of_date_field": None,
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Validated via API dataset discovery. datapointId=OS060.",
        "size_measure_type": None,
        "source_dataset": "0026-0020",
    },
    "Firm Name": {
        "raw_field_id": "FirmName",
        "raw_field_name": "Firm Name",
        "definition": "The company that broadly manages the operations and functions of the fund.",
        "product_scope": ["fund", "etf", "shareclass"],
        "entity_level": "organization",
        "semantic_group": "organization_identifier",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "snapshot",
        "as_of_date_field": None,
        "source_method": ["investments.search", "get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Available from search metadata and API.",
        "size_measure_type": None,
        "source_dataset": "0026-0020",
    },
    "Universe": {
        "raw_field_id": "Universe",
        "raw_field_name": "Universe",
        "definition": "ETF managed portfolio universe describing the exposure scope of a strategy's underlying securities.",
        "product_scope": ["etf", "fund"],
        "entity_level": "portfolio",
        "semantic_group": "exposure_scope",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "snapshot",
        "as_of_date_field": None,
        "source_method": ["investments.search", "get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "CRITICAL: Universe is exposure_scope / underlying_region_scope. Must NOT be used as ETF product type flag.",
        "size_measure_type": None,
        "source_dataset": "direct_definition",
    },
    "Total Net Assets / Estimated Net Flow (TNA/ENF)": {
        "raw_field_id": "TNA",
        "raw_field_name": "Total Net Assets / Estimated Net Flow (TNA/ENF)",
        "definition": "Total Net Assets / Estimated Net Flow data points for asset flow analysis.",
        "product_scope": ["fund", "shareclass"],
        "entity_level": "shareclass",
        "semantic_group": "shareclass_level_size",
        "currency": "BASE",
        "unit": "currency",
        "scale": None,
        "frequency": "monthly",
        "as_of_date_field": None,
        "source_method": ["get_asset_flow"],
        "sample_value": None,
        "validation_status": "blocked_unit_scale_unknown",
        "reviewer_notes": "TNA/ENF blocked. Unit/scale unknown. Do not use for capital flow conclusions.",
        "size_measure_type": "unknown_or_blocked",
        "source_dataset": "asset_flow",
    },
}

# Merge: scanned (base) + api_fields (override) + direct_fields (override)
merged = dict(scanned)
for name, f in direct_fields.items():
    merged[name] = f
for name, f in api_fields.items():
    existing = merged.get(name)
    if existing:
        # Preserve raw_field_id from existing (e.g. FundSize), update other API-validated properties
        for k, v in f.items():
            if k == "raw_field_id":
                continue
            if v is not None:
                existing[k] = v
        # Append datapointId note to reviewer_notes
        dp_id = f.get("raw_field_id")
        if dp_id and dp_id != existing.get("raw_field_id"):
            note = existing.get("reviewer_notes", "")
            existing["reviewer_notes"] = f"{note} API datapointId={dp_id}.".strip()
    else:
        merged[name] = f

# Build final list
field_inventory = list(merged.values())

# Update files
now = "2026-05-22T15:37:59.178635Z"
run_id = "batch2b_rerun_20260522_152907"

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

write_json(LOCAL_STATE_BASE / "morningstar_full_field_inventory_batch2b.json", {
    "inventory_id": "morningstar_full_field_inventory_batch2b_v2_merged",
    "generated_at": now,
    "run_id": run_id,
    "total_fields": len(field_inventory),
    "fields": field_inventory,
})

semantic_map = {}
for f in field_inventory:
    sg = f.get("semantic_group") or "unclassified"
    semantic_map.setdefault(sg, []).append(f["raw_field_id"])
write_json(LOCAL_STATE_BASE / "morningstar_semantic_field_map_batch2b.json", {
    "map_id": "morningstar_semantic_field_map_batch2b_v2_merged",
    "generated_at": now,
    "run_id": run_id,
    "semantic_groups": {k: {"field_count": len(v), "fields": v} for k, v in sorted(semantic_map.items())},
    "total_groups": len(semantic_map),
})

size_candidates = [f for f in field_inventory if f.get("size_measure_type")]
write_json(LOCAL_STATE_BASE / "morningstar_size_field_candidates_batch2b.json", {
    "candidates_id": "morningstar_size_field_candidates_batch2b_v2_merged",
    "generated_at": now,
    "run_id": run_id,
    "total_candidates": len(size_candidates),
    "candidates": size_candidates,
})

validation_report = {
    "report_id": "morningstar_field_definition_validation_report_batch2b_v2_merged",
    "generated_at": now,
    "run_id": run_id,
    "summary": {
        "semantic_definition_match": sum(1 for f in field_inventory if f.get("validation_status") == "semantic_definition_match"),
        "field_name_match_only": sum(1 for f in field_inventory if f.get("validation_status") == "field_name_match_only"),
        "dataset_discovered_pending_validation": sum(1 for f in field_inventory if f.get("validation_status") == "dataset_discovered_pending_validation"),
        "blocked_unit_scale_unknown": sum(1 for f in field_inventory if f.get("validation_status") == "blocked_unit_scale_unknown"),
    },
    "details": [{"raw_field_id": f["raw_field_id"], "validation_status": f["validation_status"], "reviewer_notes": f.get("reviewer_notes", "")} for f in field_inventory],
}
write_json(LOCAL_STATE_BASE / "morningstar_field_definition_validation_report_batch2b.json", validation_report)

# Update run_state artifact summary
run_state = json.load(open(LOCAL_STATE_BASE / "run_state.json", encoding='utf-8'))
run_state["batch2b_artifact_summary"]["field_inventory_count"] = len(field_inventory)
run_state["batch2b_artifact_summary"]["semantic_groups_count"] = len(semantic_map)
run_state["batch2b_artifact_summary"]["size_candidates_count"] = len(size_candidates)
write_json(LOCAL_STATE_BASE / "run_state.json", run_state)

print(f"Merged field inventory: {len(field_inventory)} fields, {len(semantic_map)} semantic groups, {len(size_candidates)} size candidates.")
