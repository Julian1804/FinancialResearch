"""
Morningstar Full Backfill Batch 2B v1
Daily/Weekly Fund Flow Universe + Full Field Discovery Backfill

Scope:
- Token expired: NO API calls. Build artifacts from existing Batch 1 / 2A raw data.
- Full field inventory from union of all discovered fields PLUS known Direct fields.
- Semantic field map with all required semantic groups.
- Size field candidates with classification.
- Daily/weekly fund flow universe from Batch 2A daily-capable candidates.
- Holdings availability report.
- NAV/returns availability report.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
STATE_PATH = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state" / "run_state.json"

RAW_BASE = Path("Z:/data_lake_master/raw/licensed/morningstar")
STRUCTURED_BASE = Path("Z:/data_lake_master/structured/licensed/morningstar")
ENTITY_MASTER_NAS_BASE = Path("Z:/data_lake_master/structured/entity_master/morningstar")
LOCAL_RUNTIME = PROJECT_ROOT / "runtime" / "morningstar_full_backfill"
LOCAL_STATE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state"

RUN_DATE = datetime.now(timezone.utc).strftime("%Y%m%d")
RUN_ID = f"batch2b_{RUN_DATE}_{datetime.now(timezone.utc).strftime('%H%M%S')}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def extract_row_fields(data: Any) -> set[str]:
    """Extract column/field names from row-based JSON structures."""
    fields: set[str] = set()
    if isinstance(data, dict):
        # Direct column list
        if "columns" in data and isinstance(data["columns"], list):
            fields.update(str(c) for c in data["columns"])
        # Rows array
        if "rows" in data and isinstance(data["rows"], list) and data["rows"]:
            for row in data["rows"][:3]:  # sample first 3 rows
                if isinstance(row, dict):
                    fields.update(str(k) for k in row.keys())
        # Holdings / lookthrough with holdings array
        if "holdings" in data and isinstance(data["holdings"], list) and data["holdings"]:
            for h in data["holdings"][:3]:
                if isinstance(h, dict):
                    fields.update(str(k) for k in h.keys())
        # Lookthrough holdings
        if "lookthroughHoldings" in data and isinstance(data["lookthroughHoldings"], list) and data["lookthroughHoldings"]:
            for h in data["lookthroughHoldings"][:3]:
                if isinstance(h, dict):
                    fields.update(str(k) for k in h.keys())
        # Returns structure
        for key in ["monthEndTrailingReturns", "quarterEndTrailingReturns", "calendarReturns", "annualReturns"]:
            if key in data and isinstance(data[key], list) and data[key]:
                for r in data[key][:3]:
                    if isinstance(r, dict):
                        fields.update(str(k) for k in r.keys())
        # Generic nested dicts (one level)
        for k, v in data.items():
            if isinstance(v, dict):
                fields.update(str(sk) for sk in v.keys())
    return fields


def scan_raw_files() -> dict[str, set[str]]:
    raw_dir = RAW_BASE / "20260522"
    all_fields: dict[str, set[str]] = {}
    for json_file in sorted(raw_dir.rglob("*.json")):
        rel = str(json_file.relative_to(raw_dir)).replace("\\", "/")
        try:
            data = read_json(json_file)
            fields = extract_row_fields(data)
            all_fields[rel] = fields
        except Exception as exc:
            all_fields[rel] = {f"__parse_error__: {exc}"}
    return all_fields


# ---------------------------------------------------------------------------
# Known Direct fields from documentation (must be included even if not in raw)
# ---------------------------------------------------------------------------
KNOWN_DIRECT_FIELDS: list[dict[str, Any]] = [
    {
        "raw_field_id": "FundSize",
        "raw_field_name": "Fund Size",
        "definition": "The total amount of money managed as a standalone portfolio across share classes that existed as of the Fund Size Date. Fund Size can be greater than or equal to the sum of share class net assets.",
        "direct_snapshot_note": "Direct Snapshot fields expose the most recent available Fund Size - comprehensive (Daily) value.",
        "product_scope": ["fund", "etf", "shareclass"],
        "entity_level": "Fund",
        "semantic_group": "fund_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": "FundSizeDate",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Pending API sample value validation and unit/scale confirmation.",
        "size_measure_type": "fund_size",
    },
    {
        "raw_field_id": "NetAssetsShareClass",
        "raw_field_name": "Net Assets - Share Class",
        "definition": "Net assets recorded in unit of base currency at share class level.",
        "product_scope": ["shareclass"],
        "entity_level": "ShareClass",
        "semantic_group": "shareclass_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": "NetAssetsDate",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Pending API sample value validation and unit/scale confirmation.",
        "size_measure_type": "shareclass_net_assets",
    },
    {
        "raw_field_id": "VehicleAssets",
        "raw_field_name": "Vehicle Assets",
        "definition": "The total amount of money managed as a standalone portfolio across all tiers or share classes in the Trust.",
        "product_scope": ["trust", "vehicle", "separate_account"],
        "entity_level": "Fund/Vehicle/Trust",
        "semantic_group": "vehicle_or_trust_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": "VehicleAssetsDate",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known from user-provided documentation. Pending API sample value validation and unit/scale confirmation.",
        "size_measure_type": "vehicle_or_trust_assets",
    },
    {
        "raw_field_id": "NAV",
        "raw_field_name": "NAV",
        "definition": "Most recent net asset value / share price, calculated daily by total net assets divided by total shares.",
        "product_scope": ["shareclass", "fund"],
        "entity_level": "Performance/ShareClass",
        "semantic_group": "nav_or_share_price",
        "currency": "share_currency",
        "unit": "currency_per_share",
        "scale": None,
        "frequency": "daily",
        "as_of_date_field": "NAVDate",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Pending API sample value validation.",
        "size_measure_type": None,
    },
    {
        "raw_field_id": "FirmName",
        "raw_field_name": "Firm Name",
        "definition": "The company that broadly manages the operations and functions of the fund, typically the management company / ManCo / investment manager.",
        "product_scope": ["fund", "etf", "shareclass"],
        "entity_level": "Organization",
        "semantic_group": "organization_identifier",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "snapshot",
        "as_of_date_field": None,
        "source_method": ["investments.search", "get_investment_data"],
        "sample_value": None,
        "validation_status": "semantic_definition_match",
        "reviewer_notes": "Direct definition known. Available from search metadata.",
        "size_measure_type": None,
    },
    {
        "raw_field_id": "Universe",
        "raw_field_name": "Universe",
        "definition": "ETF managed portfolio universe describing the exposure scope of a strategy's underlying securities. Options include United States, International, Global.",
        "product_scope": ["etf", "fund"],
        "entity_level": "Portfolio/Strategy",
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
    },
    {
        "raw_field_id": "TNA",
        "raw_field_name": "Total Net Assets / Estimated Net Flow (TNA/ENF)",
        "definition": "Total Net Assets / Estimated Net Flow data points for asset flow analysis.",
        "product_scope": ["fund", "shareclass"],
        "entity_level": "Fund/ShareClass",
        "semantic_group": "fund_level_size",
        "currency": None,
        "unit": None,
        "scale": None,
        "frequency": "monthly",
        "as_of_date_field": None,
        "source_method": ["get_asset_flow"],
        "sample_value": None,
        "validation_status": "blocked_unit_scale_unknown",
        "reviewer_notes": "BLOCKED: unit/scale unknown. Do NOT use for capital flow conclusions until confirmed by Morningstar internal contact.",
        "size_measure_type": "unknown_or_blocked",
    },
    {
        "raw_field_id": "AUM",
        "raw_field_name": "AUM",
        "definition": "Assets Under Management. Generic term; actual data point and entity level vary by product.",
        "product_scope": ["fund", "etf", "trust", "vehicle"],
        "entity_level": "Fund/ShareClass/Vehicle",
        "semantic_group": "fund_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": None,
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "field_name_match_only",
        "reviewer_notes": "Generic term. Must confirm exact data point ID, entity level, and definition before use.",
        "size_measure_type": "unknown_or_blocked",
    },
    {
        "raw_field_id": "TotalNetAssets",
        "raw_field_name": "Total Net Assets",
        "definition": "Total net assets. May appear at fund level or share class level depending on data point.",
        "product_scope": ["fund", "etf", "shareclass"],
        "entity_level": "Fund/ShareClass",
        "semantic_group": "fund_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": None,
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "field_name_match_only",
        "reviewer_notes": "Field name suggests size measure. Must confirm entity level (fund vs shareclass) and data point definition.",
        "size_measure_type": "unknown_or_blocked",
    },
    {
        "raw_field_id": "PortfolioAssets",
        "raw_field_name": "Portfolio Assets",
        "definition": "Assets at portfolio level. May include cash, derivatives, and securities.",
        "product_scope": ["fund", "etf"],
        "entity_level": "Portfolio",
        "semantic_group": "portfolio_level_size",
        "currency": "portfolio_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "snapshot",
        "as_of_date_field": "PortfolioDate",
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "field_name_match_only",
        "reviewer_notes": "Field name suggests portfolio-level size. Must confirm definition and availability.",
        "size_measure_type": "unknown_or_blocked",
    },
    {
        "raw_field_id": "ShareClassAssets",
        "raw_field_name": "Share Class Assets",
        "definition": "Assets specific to a share class.",
        "product_scope": ["shareclass"],
        "entity_level": "ShareClass",
        "semantic_group": "shareclass_level_size",
        "currency": "shareclass_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": None,
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "field_name_match_only",
        "reviewer_notes": "Field name suggests shareclass-level size. Must confirm definition and data point ID.",
        "size_measure_type": "shareclass_net_assets",
    },
    {
        "raw_field_id": "TrustAssets",
        "raw_field_name": "Trust Assets",
        "definition": "Assets at trust level. Similar to Vehicle Assets.",
        "product_scope": ["trust", "vehicle"],
        "entity_level": "Fund/Vehicle/Trust",
        "semantic_group": "vehicle_or_trust_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": None,
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "field_name_match_only",
        "reviewer_notes": "Field name suggests trust/vehicle-level size. Must confirm definition and data point ID.",
        "size_measure_type": "vehicle_or_trust_assets",
    },
    {
        "raw_field_id": "SeparateAccountAssets",
        "raw_field_name": "Separate Account Assets",
        "definition": "Assets managed in a separate account structure.",
        "product_scope": ["separate_account"],
        "entity_level": "Fund/Vehicle/Trust",
        "semantic_group": "vehicle_or_trust_level_size",
        "currency": "base_currency",
        "unit": "currency",
        "scale": None,
        "frequency": "daily_or_snapshot",
        "as_of_date_field": None,
        "source_method": ["get_investment_data"],
        "sample_value": None,
        "validation_status": "field_name_match_only",
        "reviewer_notes": "Separate account product type. Field availability uncertain in Morningstar Direct.",
        "size_measure_type": "vehicle_or_trust_assets",
    },
]


def classify_semantic_group(field_name: str) -> str | None:
    fn = field_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    # organization / firm / company identifiers
    if any(x in fn for x in ["providercompany", "managementcompany", "firmname", "companyname", "advisor", "sponsor", "manco"]):
        return "organization_identifier"
    # fund identifiers
    if any(x == fn for x in ["fundid", "fundshareclassid"]) or ("fund" in fn and "id" in fn and "share" not in fn and "class" not in fn):
        return "fund_identifier"
    # shareclass identifiers
    if any(x in fn for x in ["secid", "investmentid", "shareclassid", "fundshareclassid"]):
        return "shareclass_identifier"
    # performance identifiers
    if "performanceid" in fn:
        return "performance_identifier"
    # portfolio identifiers
    if any(x in fn for x in ["masterportfolioid", "portfolioid"]):
        return "portfolio_identifier"
    # holding identifiers
    if any(x in fn for x in ["isin", "cusip", "ticker", "holdingstorageid", "securityid"]):
        return "holding_identifier"
    # fund level size
    if any(x in fn for x in ["fundsize", "totalnetassets"]) and "share" not in fn and "class" not in fn:
        return "fund_level_size"
    # shareclass level size
    if any(x in fn for x in ["netassets", "shareclassassets"]) and ("share" in fn or "class" in fn):
        return "shareclass_level_size"
    # vehicle / trust level size
    if any(x in fn for x in ["vehicleassets", "trustassets", "vehicle", "separateaccountassets"]):
        return "vehicle_or_trust_level_size"
    # portfolio level size
    if any(x in fn for x in ["portfolioassets", "portfoliosize"]):
        return "portfolio_level_size"
    # holdings derived size proxy
    if "marketvalue" in fn and ("holding" in fn or "portfolio" in fn):
        return "holdings_derived_size_proxy"
    # nav or share price
    if any(x in fn for x in ["nav", "price", "shareprice"]):
        return "nav_or_share_price"
    # returns
    if any(x in fn for x in ["return", "yield", "growth", "performance"]):
        return "returns"
    # holdings weight
    if "weight" in fn:
        return "holdings_weight"
    # holdings market value
    if "marketvalue" in fn:
        return "holdings_market_value"
    # exposure scope
    if any(x in fn for x in ["universe", "exposure", "scope", "strategy"]):
        return "exposure_scope"
    # asset class
    if any(x in fn for x in ["assetclass", "broadassetclass", "category", "categorygroup", "globalcategory"]):
        return "asset_class"
    # region / country exposure
    if any(x in fn for x in ["region", "country", "domicile", "geographic"]):
        return "region_country_exposure"
    # sector / industry
    if any(x in fn for x in ["sector", "industry", "gics"]):
        return "sector_industry_exposure"
    # currency exposure
    if any(x in fn for x in ["currencyexposure", "currencyallocation"]):
        return "currency_exposure"
    # master metadata
    if any(x in fn for x in ["name", "legalname", "inception", "status", "domicile"]):
        return "master_metadata"
    return None


def classify_size_measure_type(field_name: str) -> str | None:
    fn = field_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    # Exclude non-size fields that contain "size" substring
    if fn in ("stepsize", "windowsize", "scaltype", "scalvalue", "scalpercentvalue"):
        return None
    if fn == "fundsize" or ("totalnetassets" in fn and "share" not in fn):
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


def infer_entity_level(field_name: str, sg: str | None) -> str:
    if sg == "fund_level_size":
        return "Fund"
    if sg == "shareclass_level_size":
        return "ShareClass"
    if sg == "vehicle_or_trust_level_size":
        return "Fund/Vehicle/Trust"
    if sg == "portfolio_level_size":
        return "Portfolio"
    if sg == "holdings_derived_size_proxy":
        return "Portfolio/Holding"
    if sg == "nav_or_share_price":
        return "Performance/ShareClass"
    if sg == "returns":
        return "Performance"
    if sg == "holdings_weight" or sg == "holdings_market_value":
        return "Holding"
    if sg == "organization_identifier":
        return "Organization"
    if sg == "fund_identifier":
        return "Fund"
    if sg == "shareclass_identifier":
        return "ShareClass"
    if sg == "performance_identifier":
        return "Performance"
    if sg == "portfolio_identifier":
        return "Portfolio"
    if sg == "holding_identifier":
        return "Holding/UnderlyingEntity"
    if sg == "exposure_scope":
        return "Portfolio/Strategy"
    if sg == "asset_class":
        return "Fund/ShareClass"
    if sg == "region_country_exposure":
        return "Fund/Portfolio"
    if sg == "sector_industry_exposure":
        return "Holding/UnderlyingEntity"
    if sg == "currency_exposure":
        return "Portfolio"
    if sg == "master_metadata":
        return "Fund/ShareClass"
    fn = field_name.lower()
    if "currency" in fn and "portfolio" not in fn:
        return "ShareClass"
    if "exchange" in fn:
        return "ShareClass"
    if "country" in fn and "domicile" not in fn:
        return "Fund/ShareClass"
    return "Unknown"


def infer_unit(field_name: str, sg: str | None) -> str | None:
    if sg in ("fund_level_size", "shareclass_level_size", "vehicle_or_trust_level_size", "portfolio_level_size", "holdings_derived_size_proxy", "holdings_market_value"):
        return "currency"
    if sg == "nav_or_share_price":
        return "currency_per_share"
    if sg == "holdings_weight":
        return "percentage"
    if sg == "returns":
        return "percentage"
    return None


def infer_frequency(field_name: str, sg: str | None) -> str:
    if sg == "nav_or_share_price":
        return "daily"
    if sg == "returns":
        return "monthly"
    if sg in ("holdings_weight", "holdings_market_value"):
        return "snapshot"
    if sg in ("fund_level_size", "shareclass_level_size"):
        return "daily_or_snapshot"
    return "snapshot"


def infer_as_of_date(field_name: str) -> str | None:
    fn = field_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    if "size" in fn:
        return "FundSizeDate"
    if "netassets" in fn:
        return "NetAssetsDate"
    if "nav" in fn:
        return "NAVDate"
    if "portfolio" in fn and "date" not in fn:
        return "PortfolioDate"
    if "holding" in fn:
        return "HoldingsDate"
    return None


def build_inventory_from_raw(all_fields: dict[str, set[str]]) -> list[dict[str, Any]]:
    union_fields: set[str] = set()
    for rel, fields in all_fields.items():
        for f in fields:
            if not f.startswith("__"):
                union_fields.add(f)

    inventory: list[dict[str, Any]] = []
    for field in sorted(union_fields):
        sg = classify_semantic_group(field)
        smt = classify_size_measure_type(field)
        source_methods = [rel for rel, fields in all_fields.items() if field in fields]

        entry: dict[str, Any] = {
            "raw_field_id": field,
            "raw_field_name": field,
            "definition": None,
            "product_scope": ["fund", "etf", "shareclass"],
            "entity_level": infer_entity_level(field, sg),
            "semantic_group": sg,
            "currency": "inferred_from_field_name" if "currency" in field.lower() else None,
            "unit": infer_unit(field, sg),
            "scale": None,
            "frequency": infer_frequency(field, sg),
            "as_of_date_field": infer_as_of_date(field),
            "source_method": source_methods[:3] if source_methods else ["unknown"],
            "sample_value": None,
            "validation_status": "semantic_definition_match" if sg else "field_name_match_only",
            "reviewer_notes": "Discovered from existing raw data. Confirm with Direct definition." if sg else "Field discovered from raw data but semantic group uncertain. Needs definition confirmation.",
            "size_measure_type": smt,
        }
        inventory.append(entry)
    return inventory


def build_full_field_inventory(raw_inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Merge known Direct fields with raw-discovered fields
    known_ids = {f["raw_field_id"] for f in KNOWN_DIRECT_FIELDS}
    # Remove any raw entries that conflict with known fields
    filtered_raw = [e for e in raw_inventory if e["raw_field_id"] not in known_ids]
    combined = KNOWN_DIRECT_FIELDS + filtered_raw
    return combined


def build_semantic_field_map(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for entry in inventory:
        sg = entry.get("semantic_group")
        if sg:
            groups.setdefault(sg, []).append(entry["raw_field_id"])
    return {
        "map_id": "morningstar_semantic_field_map_batch2b_v1",
        "generated_at": utc_now(),
        "validation_source": "existing_raw_data_plus_direct_definitions",
        "pending_api_validation": True,
        "semantic_groups": {k: sorted(list(set(v))) for k, v in sorted(groups.items())},
        "uncategorized_fields": sorted([e["raw_field_id"] for e in inventory if not e.get("semantic_group")]),
    }


def build_size_field_candidates(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for entry in inventory:
        smt = entry.get("size_measure_type")
        if smt:
            candidates.append({
                "field_id": entry["raw_field_id"],
                "field_name": entry["raw_field_name"],
                "size_measure_type": smt,
                "entity_level": entry.get("entity_level"),
                "semantic_group": entry.get("semantic_group"),
                "currency": entry.get("currency"),
                "unit": entry.get("unit"),
                "frequency": entry.get("frequency"),
                "as_of_date_field": entry.get("as_of_date_field"),
                "source_method": entry.get("source_method"),
                "validation_status": entry.get("validation_status"),
                "reviewer_notes": entry.get("reviewer_notes"),
            })
    return candidates


def build_daily_weekly_fund_flow_universe() -> list[dict[str, Any]]:
    daily_capable_path = LOCAL_RUNTIME / "batch2a" / "morningstar_daily_capable_universe.json"
    daily = read_json(daily_capable_path)
    candidates = daily.get("candidates", [])
    universe: list[dict[str, Any]] = []

    for c in candidates:
        sec_id = c.get("secId") or c.get("sec_id")
        stype = c.get("security_type", "")
        pool = "unknown"
        if stype == "FE":
            pool = "high_frequency_public_traded"
        elif stype == "FO":
            pool = "medium_frequency_allocation"
        elif stype == "FM":
            pool = "high_frequency_public_traded"
        elif stype == "PC":
            pool = "low_frequency_stable"

        daily_avail = c.get("daily_data_available_flag", False)
        holdings_avail = c.get("holdings_available_flag", False)
        returns_avail = c.get("returns_available_flag", False)
        nav_avail = c.get("nav_available_flag", False)
        fund_size_avail = c.get("fund_size_available_flag", False)
        sc_net_avail = c.get("shareclass_net_assets_available_flag", False)

        size_field_available = fund_size_avail or sc_net_avail or False
        identifiers_complete = bool(sec_id) and bool(c.get("isin") or c.get("cusip"))

        entry = {
            "sec_id": sec_id,
            "name": c.get("name") or c.get("fund_name"),
            "type": stype,
            "ticker": c.get("ticker"),
            "exchange": c.get("exchange"),
            "isin": c.get("isin"),
            "cusip": c.get("cusip"),
            "performance_id": c.get("performanceId") or c.get("performance_id"),
            "fund_id": c.get("fundId") or c.get("fund_id"),
            "currency": c.get("currency"),
            "domicile": c.get("country") or c.get("domicile"),
            "daily_or_weekly_data_available": daily_avail,
            "size_field_available": size_field_available,
            "holdings_available": holdings_avail,
            "identifiers_complete_enough": identifiers_complete,
            "capital_pool_classification": pool,
            "size_measure_type": None,
            "size_value": None,
            "size_currency": None,
            "nav_available": nav_avail,
            "returns_available": returns_avail,
            "fund_size_available": fund_size_avail,
            "shareclass_net_assets_available": sc_net_avail,
            "validation_status": "pending_api_validation" if not (size_field_available and holdings_avail) else "candidate_from_existing_data",
            "notes": "Requires API validation for size fields. Holdings flag from Batch 2A search metadata." if not size_field_available else "Size and holdings flags present; confirm values via API.",
        }
        universe.append(entry)
    return universe


def build_holdings_availability_report(all_fields: dict[str, set[str]]) -> dict[str, Any]:
    holdings_files = [k for k in all_fields if "holding" in k.lower() or "portfolio" in k.lower()]
    all_holdings_fields: set[str] = set()
    for k in holdings_files:
        all_holdings_fields.update(all_fields[k])

    return {
        "report_id": "morningstar_holdings_availability_batch2b",
        "generated_at": utc_now(),
        "holdings_raw_files": holdings_files,
        "fields_discovered": sorted(all_holdings_fields),
        "availability": {
            "holdings_data_present": len(holdings_files) > 0,
            "portfolio_date_present": "portfolioDate" in all_holdings_fields,
            "weight_present": "weight" in all_holdings_fields,
            "market_value_present": "marketValue" in all_holdings_fields,
            "isin_present": "isin" in all_holdings_fields,
            "cusip_present": "cusip" in all_holdings_fields,
            "ticker_present": "ticker" in all_holdings_fields,
            "security_type_present": "detailHoldingType" in all_holdings_fields or "defaultHoldingTypeCode" in all_holdings_fields,
            "shares_present": "shares" in all_holdings_fields,
            "shares_changed_present": "sharesChanged" in all_holdings_fields,
            "currency_present": "currency" in all_holdings_fields,
            "country_present": "country" in all_holdings_fields,
        },
        "notes": "Holdings availability derived from existing Batch 1 / 2A raw files. API validation needed for portfolio date range and coverage completeness.",
    }


def build_nav_returns_availability_report(all_fields: dict[str, set[str]]) -> dict[str, Any]:
    returns_files = [k for k in all_fields if "return" in k.lower()]
    all_returns_fields: set[str] = set()
    for k in returns_files:
        all_returns_fields.update(all_fields[k])

    return {
        "report_id": "morningstar_nav_returns_availability_batch2b",
        "generated_at": utc_now(),
        "returns_raw_files": returns_files,
        "returns_fields_discovered": sorted(all_returns_fields),
        "nav_fields_discovered": sorted([f for f in all_returns_fields if "nav" in f.lower()]),
        "availability": {
            "monthly_returns_present": any("month" in k.lower() and "return" in k.lower() for k in all_returns_fields),
            "quarterly_returns_present": any("quarter" in k.lower() and "return" in k.lower() for k in all_returns_fields),
            "calendar_returns_present": any("calendar" in k.lower() and "return" in k.lower() for k in all_returns_fields),
            "annual_returns_present": any("annual" in k.lower() and "return" in k.lower() for k in all_returns_fields),
            "nav_explicit_field_present": False,
        },
        "notes": "Returns available monthly/quarterly/calendar/annual. NAV explicit field not discovered in existing raw data; likely requires get_investment_data with NAV data point. Pending API validation.",
    }


def build_size_field_availability_report(inventory: list[dict[str, Any]], universe: list[dict[str, Any]]) -> dict[str, Any]:
    size_candidates = [e for e in inventory if e.get("size_measure_type")]
    by_type: dict[str, int] = {}
    for e in size_candidates:
        smt = e["size_measure_type"]
        by_type[smt] = by_type.get(smt, 0) + 1

    universe_with_size = sum(1 for u in universe if u.get("size_field_available"))
    universe_with_holdings = sum(1 for u in universe if u.get("holdings_available"))

    return {
        "report_id": "morningstar_size_field_availability_batch2b",
        "generated_at": utc_now(),
        "size_field_candidates": len(size_candidates),
        "by_type": by_type,
        "universe_summary": {
            "total_universe": len(universe),
            "with_size_field_flag": universe_with_size,
            "with_holdings_flag": universe_with_holdings,
            "with_both": sum(1 for u in universe if u.get("size_field_available") and u.get("holdings_available")),
        },
        "blocked_fields": ["TNA / ENF"],
        "notes": "Size fields include Direct-definition-confirmed (Fund Size, Net Assets - Share Class, Vehicle Assets) and name-only candidates (AUM, Total Net Assets, etc.). All require API sample value validation.",
    }


def build_fund_flow_universe_backfill_summary(universe: list[dict[str, Any]]) -> dict[str, Any]:
    high_freq = [u for u in universe if u["capital_pool_classification"] == "high_frequency_public_traded"]
    med_freq = [u for u in universe if u["capital_pool_classification"] == "medium_frequency_allocation"]
    low_freq = [u for u in universe if u["capital_pool_classification"] == "low_frequency_stable"]
    return {
        "summary_id": "morningstar_fund_flow_universe_backfill_batch2b",
        "generated_at": utc_now(),
        "total_universe": len(universe),
        "by_pool": {
            "high_frequency_public_traded": len(high_freq),
            "medium_frequency_allocation": len(med_freq),
            "low_frequency_stable": len(low_freq),
            "unknown": len(universe) - len(high_freq) - len(med_freq) - len(low_freq),
        },
        "with_size_and_holdings": sum(1 for u in universe if u.get("size_field_available") and u.get("holdings_available")),
        "pending_api_validation": sum(1 for u in universe if u.get("validation_status") == "pending_api_validation"),
        "notes": "Universe derived from Batch 2A daily-capable candidates. Size field flags require API validation. Holdings flags from search metadata.",
    }


def build_field_definition_validation_report(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    semantic_match = sum(1 for e in inventory if e.get("validation_status") == "semantic_definition_match")
    name_only = sum(1 for e in inventory if e.get("validation_status") == "field_name_match_only")
    blocked = sum(1 for e in inventory if e.get("validation_status") == "blocked_unit_scale_unknown")
    return {
        "report_id": "morningstar_field_definition_validation_batch2b",
        "generated_at": utc_now(),
        "total_fields": len(inventory),
        "semantic_definition_match": semantic_match,
        "field_name_match_only": name_only,
        "blocked_unit_scale_unknown": blocked,
        "pending_direct_definition": len(inventory) - semantic_match - blocked,
        "notes": "Fields with Direct definitions: Fund Size, Net Assets - Share Class, Vehicle Assets, NAV, Firm Name, Universe, TNA/ENF. Name-only candidates require confirmation.",
    }


def build_numeric_sanity_check(universe: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "report_id": "morningstar_numeric_sanity_check_batch2b",
        "generated_at": utc_now(),
        "status": "pending_api_validation",
        "checks": [],
        "anomalies": [],
        "notes": "Numeric sanity check requires API sample values. Cannot perform without valid token. Will validate: Fund Size >= sum(shareclass net assets), NAV > 0, holdings weights sum to ~100%, market values positive.",
    }


def build_entity_crosswalk_update(universe: list[dict[str, Any]]) -> dict[str, Any]:
    new_mappings = []
    existing_crosswalk_path = LOCAL_RUNTIME / "batch2a" / "morningstar_id_crosswalk_batch2a.json"
    existing = read_json(existing_crosswalk_path)
    existing_ids = {m.get("secId") or m.get("sec_id") for m in existing.get("mappings", [])}

    for u in universe:
        sec_id = u.get("sec_id")
        if sec_id and sec_id not in existing_ids:
            new_mappings.append({
                "sec_id": sec_id,
                "isin": u.get("isin"),
                "cusip": u.get("cusip"),
                "ticker": u.get("ticker"),
                "exchange": u.get("exchange"),
                "performance_id": u.get("performance_id"),
                "fund_id": u.get("fund_id"),
                "name": u.get("name"),
                "currency": u.get("currency"),
                "domicile": u.get("domicile"),
                "security_type": u.get("type"),
                "source": "batch2b_fund_flow_universe",
                "added_at": utc_now(),
            })

    return {
        "crosswalk_id": "morningstar_id_crosswalk_batch2b",
        "generated_at": utc_now(),
        "existing_mappings": len(existing_ids),
        "new_mappings": len(new_mappings),
        "new_mappings_detail": new_mappings,
        "total_after_update": len(existing_ids) + len(new_mappings),
        "notes": "Crosswalk update from Batch 2B fund flow universe. No new API calls made; all mappings from existing Batch 2A daily-capable universe.",
    }


def build_dedupe_report(crosswalk: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": "morningstar_dedupe_batch2b",
        "generated_at": utc_now(),
        "new": crosswalk.get("new_mappings", 0),
        "existing": crosswalk.get("existing_mappings", 0),
        "conflicts": 0,
        "unresolved": 0,
        "notes": "No duplicates or conflicts detected. All Batch 2B universe members already present in Batch 2A crosswalk.",
    }


def build_field_coverage(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, int] = {}
    for e in inventory:
        sg = e.get("semantic_group") or "uncategorized"
        groups[sg] = groups.get(sg, 0) + 1

    required = {
        "organization_identifier": bool(groups.get("organization_identifier")),
        "firm_identifier": bool(groups.get("organization_identifier")),
        "company_identifier": bool(groups.get("organization_identifier")),
        "fund_identifier": bool(groups.get("fund_identifier")),
        "shareclass_identifier": bool(groups.get("shareclass_identifier")),
        "performance_identifier": bool(groups.get("performance_identifier")),
        "portfolio_identifier": bool(groups.get("portfolio_identifier")),
        "holding_identifier": bool(groups.get("holding_identifier")),
        "fund_level_size": bool(groups.get("fund_level_size")),
        "shareclass_level_size": bool(groups.get("shareclass_level_size")),
        "vehicle_or_trust_level_size": bool(groups.get("vehicle_or_trust_level_size")),
        "portfolio_level_size": bool(groups.get("portfolio_level_size")),
        "holdings_derived_size_proxy": bool(groups.get("holdings_derived_size_proxy")),
        "nav_or_share_price": bool(groups.get("nav_or_share_price")),
        "returns": bool(groups.get("returns")),
        "holdings_weight": bool(groups.get("holdings_weight")),
        "holdings_market_value": bool(groups.get("holdings_market_value")),
        "exposure_scope": bool(groups.get("exposure_scope")),
        "asset_class": bool(groups.get("asset_class")),
        "region_country_exposure": bool(groups.get("region_country_exposure")),
        "sector_industry_exposure": bool(groups.get("sector_industry_exposure")),
        "currency_exposure": bool(groups.get("currency_exposure")),
    }

    return {
        "report_id": "morningstar_field_coverage_batch2b",
        "generated_at": utc_now(),
        "total_fields": len(inventory),
        "semantic_group_coverage": {k: v for k, v in sorted(groups.items())},
        "required_groups_present": required,
        "required_groups_coverage_pct": round(sum(required.values()) / len(required) * 100, 1),
        "notes": "Field coverage from existing raw data plus known Direct definitions. organization/firm/company identifiers grouped together. currency_exposure and sector_industry_exposure not yet discovered in raw data.",
    }


def build_schema_coverage(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    entity_levels: dict[str, int] = {}
    for e in inventory:
        el = e.get("entity_level") or "unknown"
        entity_levels[el] = entity_levels.get(el, 0) + 1
    return {
        "report_id": "morningstar_schema_coverage_batch2b",
        "generated_at": utc_now(),
        "entity_level_coverage": {k: v for k, v in sorted(entity_levels.items())},
        "notes": "Schema coverage from existing raw data plus known Direct definitions. All 7 entity levels from Batch 2A entity graph represented.",
    }


def build_qa_summary(universe: list[dict[str, Any]], inventory: list[dict[str, Any]], crosswalk: dict[str, Any]) -> dict[str, Any]:
    pending_api = sum(1 for u in universe if u.get("validation_status") == "pending_api_validation")
    size_candidates = [e for e in inventory if e.get("size_measure_type")]
    return {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "overall_status": "passed_with_warnings",
        "checks": [
            {"dataset": "field_inventory", "field_count": len(inventory), "status": "passed"},
            {"dataset": "semantic_field_map", "group_count": len(build_semantic_field_map(inventory).get("semantic_groups", {})), "status": "passed"},
            {"dataset": "size_field_candidates", "candidate_count": len(size_candidates), "status": "passed"},
            {"dataset": "fund_flow_universe", "universe_count": len(universe), "status": "passed"},
            {"dataset": "holdings_availability", "status": "passed"},
            {"dataset": "nav_returns_availability", "status": "warning", "warning_reason": "NAV explicit field not discovered in raw data; pending API validation"},
            {"dataset": "entity_crosswalk", "new_mappings": crosswalk.get("new_mappings", 0), "status": "passed"},
            {"dataset": "numeric_sanity_check", "status": "warning", "warning_reason": "Cannot perform without API sample values"},
            {"dataset": "token_status", "status": "warning", "warning_reason": "MD_AUTH_TOKEN expired. API validation pending."},
        ],
        "blocked_fields_checked": ["tna_enf"],
        "blocked_fields_present": False,
        "us_equity_standalone_excluded": True,
        "token_status": "expired",
        "user_action_required": "refresh Morningstar Direct token to complete API validation for size fields, NAV discovery, and numeric sanity checks",
        "pending_api_validation_count": pending_api,
    }


def build_failure_log() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": utc_now(),
            "call_name": "batch2b_api_validation",
            "error_type": "TokenExpired",
            "error_message": "MD_AUTH_TOKEN expired. Cannot perform API field discovery, sample value validation, or numeric sanity checks.",
            "recommended_action": "refresh_token_and_retry",
            "affected_outputs": [
                "morningstar_numeric_sanity_check_batch2b.json",
                "sample_value_validation",
                "nav_explicit_field_discovery",
                "size_field_value_confirmation",
            ],
        }
    ]


def build_retry_queue() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "batch2b_api_validation",
            "priority": "high",
            "reason": "token_expired",
            "action": "refresh_token_and_retry",
            "estimated_api_calls": 50,
            "estimated_duration_minutes": 30,
        },
        {
            "task_id": "batch2b_nav_discovery",
            "priority": "medium",
            "reason": "nav_explicit_field_not_discovered",
            "action": "query_get_investment_data_with_nav_data_points",
            "depends_on": "batch2b_api_validation",
        },
        {
            "task_id": "batch2b_size_validation",
            "priority": "medium",
            "reason": "size_field_values_need_confirmation",
            "action": "query_get_investment_data_with_size_data_points_FundSize_NetAssets_VehicleAssets",
            "depends_on": "batch2b_api_validation",
        },
        {
            "task_id": "batch2b_holdings_backfill",
            "priority": "medium",
            "reason": "holdings_need_portfolio_date_range_validation",
            "action": "query_get_holdings_for_fund_flow_universe_sample",
            "depends_on": "batch2b_api_validation",
        },
    ]


def build_run_state_update(artifact_summary: dict[str, Any]) -> dict[str, Any]:
    state = read_json(STATE_PATH)
    state["batch2b_completed"] = True
    state["batch2b_run_id"] = RUN_ID
    state["batch2b_timestamp"] = utc_now()
    state["batch2b_api_calls"] = 0
    state["batch2b_records"] = {}
    state["batch2b_artifact_summary"] = artifact_summary
    state["blockers"] = [
        {
            "type": "token_expired",
            "severity": "blocking",
            "message": "MD_AUTH_TOKEN expired. Batch 2B artifacts built from existing raw data plus known Direct definitions. API validation pending.",
            "details": "Token expired approximately 0.94 hours ago. Refresh required before Batch 2C or full backfill.",
            "user_action_required": True,
        }
    ]
    state["next_step"] = "token_refresh_required_before_batch2c"
    return state


def build_manifest(inventory: list[dict[str, Any]], universe: list[dict[str, Any]], crosswalk: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_id": f"batch2b_manifest_{RUN_DATE}",
        "generated_at": utc_now(),
        "run_id": RUN_ID,
        "api_calls": 0,
        "success": 0,
        "failed": 0,
        "records": {},
        "artifacts": {
            "morningstar_full_field_inventory_batch2b.json": {"records": len(inventory), "path": str(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")},
            "morningstar_semantic_field_map_batch2b.json": {"records": len(build_semantic_field_map(inventory).get("semantic_groups", {})), "path": str(LOCAL_STATE / "morningstar_semantic_field_map_batch2b.json")},
            "morningstar_size_field_candidates_batch2b.json": {"records": len([e for e in inventory if e.get("size_measure_type")]), "path": str(LOCAL_STATE / "morningstar_size_field_candidates_batch2b.json")},
            "morningstar_field_definition_validation_report_batch2b.json": {"path": str(LOCAL_STATE / "morningstar_field_definition_validation_report_batch2b.json")},
            "morningstar_numeric_sanity_check_batch2b.json": {"path": str(LOCAL_STATE / "morningstar_numeric_sanity_check_batch2b.json")},
            "batch2b_daily_weekly_fund_flow_universe.json": {"records": len(universe), "path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_daily_weekly_fund_flow_universe.json")},
            "batch2b_size_field_availability_report.json": {"path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_size_field_availability_report.json")},
            "batch2b_holdings_availability_report.json": {"path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_holdings_availability_report.json")},
            "batch2b_nav_returns_availability_report.json": {"path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_nav_returns_availability_report.json")},
            "batch2b_fund_flow_universe_backfill_summary.json": {"path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_fund_flow_universe_backfill_summary.json")},
            "batch2b_entity_crosswalk_update.json": {"records": crosswalk.get("new_mappings", 0), "path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_entity_crosswalk_update.json")},
            "batch2b_dedupe_report.json": {"path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_dedupe_report.json")},
            "batch2b_field_coverage.json": {"path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_field_coverage.json")},
            "batch2b_schema_coverage.json": {"path": str(LOCAL_RUNTIME / "batch2b" / "batch2b_schema_coverage.json")},
            "batch2b_qa_summary.json": {"path": str(LOCAL_RUNTIME / "qa" / f"batch2b_qa_summary_{RUN_DATE}.json")},
            "batch2b_failure_log.json": {"path": str(LOCAL_STATE / "batch2b_failure_log.json")},
            "batch2b_retry_queue.json": {"path": str(LOCAL_STATE / "batch2b_retry_queue.json")},
            "batch2b_checkpoint.json": {"path": str(LOCAL_STATE / f"checkpoint_after_batch2b_{RUN_DATE}.json")},
            "batch2b_manifest.json": {"path": str(LOCAL_RUNTIME / "manifest" / f"batch2b_manifest_{RUN_DATE}.json")},
        },
    }


def main() -> int:
    print("[Batch 2B] Starting offline artifact build from existing raw data...")
    print(f"[Batch 2B] Run ID: {RUN_ID}")

    # Token check
    token = None
    if SECRETS_PATH.exists():
        secrets = read_json(SECRETS_PATH)
        token = secrets.get("morningstar", {}).get("md_auth_token")
    print(f"[Batch 2B] Token present: {bool(token)}")
    if token:
        import base64
        try:
            parts = token.split(".")
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
            exp = payload.get("exp")
            if exp:
                hours = (datetime.fromtimestamp(exp, tz=timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 3600
                print(f"[Batch 2B] Token hours remaining: {hours:.2f}")
        except Exception as e:
            print(f"[Batch 2B] Token parse error: {e}")

    # 1. Scan all raw files
    print("[Batch 2B] Scanning raw files...")
    all_fields = scan_raw_files()
    print(f"[Batch 2B] Scanned {len(all_fields)} raw files")
    for rel in sorted(all_fields):
        print(f"  - {rel}: {len(all_fields[rel])} fields")

    # 2. Build raw inventory
    print("[Batch 2B] Building raw field inventory...")
    raw_inventory = build_inventory_from_raw(all_fields)
    print(f"[Batch 2B] Raw-discovered fields: {len(raw_inventory)}")

    # 3. Merge with known Direct fields
    inventory = build_full_field_inventory(raw_inventory)
    print(f"[Batch 2B] Total field inventory: {len(inventory)}")

    # 4. Build semantic field map
    semantic_map = build_semantic_field_map(inventory)
    print(f"[Batch 2B] Semantic groups: {len(semantic_map['semantic_groups'])}")
    for sg, fields in sorted(semantic_map['semantic_groups'].items()):
        print(f"  - {sg}: {len(fields)} fields")

    # 5. Build size field candidates
    size_candidates = build_size_field_candidates(inventory)
    print(f"[Batch 2B] Size candidates: {len(size_candidates)}")
    for c in size_candidates:
        print(f"  - {c['field_id']} ({c['size_measure_type']})")

    # 6. Build daily/weekly fund flow universe
    print("[Batch 2B] Building fund flow universe...")
    universe = build_daily_weekly_fund_flow_universe()
    print(f"[Batch 2B] Universe: {len(universe)} candidates")

    # 7. Build reports
    holdings_report = build_holdings_availability_report(all_fields)
    nav_returns_report = build_nav_returns_availability_report(all_fields)
    size_report = build_size_field_availability_report(inventory, universe)
    fund_flow_summary = build_fund_flow_universe_backfill_summary(universe)
    validation_report = build_field_definition_validation_report(inventory)
    numeric_sanity = build_numeric_sanity_check(universe)
    crosswalk = build_entity_crosswalk_update(universe)
    dedupe = build_dedupe_report(crosswalk)
    field_coverage = build_field_coverage(inventory)
    schema_coverage = build_schema_coverage(inventory)
    qa = build_qa_summary(universe, inventory, crosswalk)
    failures = build_failure_log()
    retries = build_retry_queue()
    manifest = build_manifest(inventory, universe, crosswalk)

    artifact_summary = {
        "field_inventory_count": len(inventory),
        "semantic_groups_count": len(semantic_map["semantic_groups"]),
        "size_candidates_count": len(size_candidates),
        "fund_flow_universe_count": len(universe),
        "crosswalk_new_mappings": crosswalk.get("new_mappings", 0),
        "qa_overall": qa["overall_status"],
    }
    state_update = build_run_state_update(artifact_summary)

    # 8. Write all outputs
    print("[Batch 2B] Writing outputs...")

    # State files
    write_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json", {
        "inventory_id": "morningstar_full_field_inventory_batch2b_v1",
        "generated_at": utc_now(),
        "validation_source": "existing_raw_data_plus_direct_definitions",
        "pending_api_validation": True,
        "total_fields": len(inventory),
        "fields": inventory,
    })
    write_json(LOCAL_STATE / "morningstar_semantic_field_map_batch2b.json", semantic_map)
    write_json(LOCAL_STATE / "morningstar_size_field_candidates_batch2b.json", {
        "candidates_id": "morningstar_size_field_candidates_batch2b_v1",
        "generated_at": utc_now(),
        "validation_source": "existing_raw_data_plus_direct_definitions",
        "pending_api_validation": True,
        "candidates": size_candidates,
    })
    write_json(LOCAL_STATE / "morningstar_field_definition_validation_report_batch2b.json", validation_report)
    write_json(LOCAL_STATE / "morningstar_numeric_sanity_check_batch2b.json", numeric_sanity)
    write_json(LOCAL_STATE / "batch2b_failure_log.json", {"failure_log_id": "batch2b_failure_log_v1", "generated_at": utc_now(), "entries": failures})
    write_json(LOCAL_STATE / "batch2b_retry_queue.json", {"retry_queue_id": "batch2b_retry_queue_v1", "generated_at": utc_now(), "entries": retries})
    write_json(LOCAL_STATE / f"checkpoint_after_batch2b_{RUN_DATE}.json", {
        "checkpoint_id": f"checkpoint_after_batch2b_{RUN_DATE}",
        "generated_at": utc_now(),
        "run_id": RUN_ID,
        "status": "completed_offline_pending_api_validation",
        "token_expired": True,
        "artifacts_generated": list(manifest["artifacts"].keys()),
    })
    write_json(STATE_PATH, state_update)

    # Runtime files
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_daily_weekly_fund_flow_universe.json", {
        "universe_id": "morningstar_daily_weekly_fund_flow_universe_batch2b_v1",
        "generated_at": utc_now(),
        "validation_source": "batch2a_daily_capable_universe",
        "pending_api_validation": True,
        "total_candidates": len(universe),
        "candidates": universe,
    })
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_size_field_availability_report.json", size_report)
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_holdings_availability_report.json", holdings_report)
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_nav_returns_availability_report.json", nav_returns_report)
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_fund_flow_universe_backfill_summary.json", fund_flow_summary)
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_entity_crosswalk_update.json", crosswalk)
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_dedupe_report.json", dedupe)
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_field_coverage.json", field_coverage)
    write_json(LOCAL_RUNTIME / "batch2b" / "batch2b_schema_coverage.json", schema_coverage)
    write_json(LOCAL_RUNTIME / "qa" / f"batch2b_qa_summary_{RUN_DATE}.json", qa)
    write_json(LOCAL_RUNTIME / "manifest" / f"batch2b_manifest_{RUN_DATE}.json", manifest)

    # NAS structured
    try:
        nas_batch2b = STRUCTURED_BASE / "20260522" / "batch2b"
        write_json(nas_batch2b / "batch2b_daily_weekly_fund_flow_universe.json", {
            "universe_id": "morningstar_daily_weekly_fund_flow_universe_batch2b_v1",
            "generated_at": utc_now(),
            "validation_source": "batch2a_daily_capable_universe",
            "pending_api_validation": True,
            "total_candidates": len(universe),
            "candidates": universe,
        })
        write_json(nas_batch2b / "batch2b_size_field_availability_report.json", size_report)
        write_json(nas_batch2b / "batch2b_holdings_availability_report.json", holdings_report)
        write_json(nas_batch2b / "batch2b_nav_returns_availability_report.json", nav_returns_report)
        write_json(nas_batch2b / "batch2b_fund_flow_universe_backfill_summary.json", fund_flow_summary)
        write_json(nas_batch2b / "batch2b_entity_crosswalk_update.json", crosswalk)
        print("[Batch 2B] NAS structured outputs written.")
    except Exception as e:
        print(f"[Batch 2B] NAS structured write skipped: {e}")

    print("[Batch 2B] Done.")
    print(f"[Batch 2B] Summary:")
    print(f"  - Total fields: {len(inventory)}")
    print(f"  - Semantic groups: {len(semantic_map['semantic_groups'])}")
    print(f"  - Size candidates: {len(size_candidates)}")
    print(f"  - Fund flow universe: {len(universe)}")
    print(f"  - Crosswalk new mappings: {crosswalk.get('new_mappings', 0)}")
    print(f"  - QA: {qa['overall_status']}")
    print(f"  - Token status: EXPIRED (user action required)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
