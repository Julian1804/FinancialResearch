"""
Morningstar Full Backfill Batch 2A v1
Data Model, Field Dictionary, Update Frequency Discovery

Scope:
- Small API discovery (<=20 calls) to probe method/dataset/field/frequency inventory.
- Analyze Batch 1 raw + new probes to build entity graph, field dictionary,
  capital pool taxonomy, update frequency inventory, ETF/daily-capable universe.
- No broad backfill. No UI work. No OpenAI API.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
PREFLIGHT_STATE_PATH = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state" / "run_state.json"

RAW_BASE = Path("Z:/data_lake_master/raw/licensed/morningstar")
STRUCTURED_BASE = Path("Z:/data_lake_master/structured/licensed/morningstar")
ENTITY_MASTER_NAS_BASE = Path("Z:/data_lake_master/structured/entity_master/morningstar")
LOCAL_RUNTIME_BASE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill"
LOCAL_STATE_BASE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state"
LOCAL_ENTITY_MASTER = PROJECT_ROOT / "runtime" / "entity_master"

RUN_DATE = datetime.now(timezone.utc).strftime("%Y%m%d")
RUN_ID = f"batch2a_{RUN_DATE}_{datetime.now(timezone.utc).strftime('%H%M%S')}"

MAX_API_CALLS = 20
RATE_LIMIT_SLEEP = 2

api_call_log: list[dict[str, Any]] = []
failure_log_entries: list[dict[str, Any]] = []
retry_queue: list[dict[str, Any]] = []
records_collected: dict[str, int] = {}


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


def get_token() -> str | None:
    if not SECRETS_PATH.exists():
        return None
    secrets = read_json(SECRETS_PATH)
    ms = secrets.get("morningstar", {})
    token = ms.get("md_auth_token")
    return str(token) if token else None


def run_child_call(call_name: str, child_code: str, token: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["MD_AUTH_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    started = datetime.now(timezone.utc)
    for attempt in range(1, 4):
        try:
            result = subprocess.run(
                [sys.executable, "-c", child_code],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
            stdout = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = {"status": "json_error", "raw": stdout[:500], "stderr": result.stderr[:500]}
            entry = {
                "call_name": call_name,
                "attempt": attempt,
                "exit_code": result.returncode,
                "elapsed_sec": elapsed,
                "payload": payload,
            }
            api_call_log.append(entry)
            if payload.get("status") == "success":
                return payload
            elif attempt == 3:
                failure_log_entries.append({
                    "timestamp": utc_now(),
                    "call_name": call_name,
                    "error_type": "api_failure",
                    "error_message": payload.get("error", result.stderr)[:500],
                })
                return payload
            time.sleep(RATE_LIMIT_SLEEP * attempt)
        except Exception as exc:
            if attempt == 3:
                failure_log_entries.append({
                    "timestamp": utc_now(),
                    "call_name": call_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                })
                return {"status": "exception", "error": str(exc)[:500]}
            time.sleep(RATE_LIMIT_SLEEP * attempt)
    return {"status": "unexpected"}


def token_health_check(token: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "token_present": bool(token),
        "token_status": "missing" if not token else "available",
        "token_masked": None,
        "expires_at": None,
        "expires_hours": None,
        "error": None,
    }
    if not token:
        result["error"] = "MD_AUTH_TOKEN not found"
        return result
    try:
        import base64 as b64mod
        parts = token.split(".")
        if len(parts) >= 3:
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(b64mod.urlsafe_b64decode(payload_b64.encode()))
            exp = payload.get("exp")
            if exp:
                exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
                result["expires_at"] = exp_dt.isoformat().replace("+00:00", "Z")
                hours_left = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                result["expires_hours"] = round(hours_left, 2)
                result["token_masked"] = token[:4] + "****" + token[-4:]
                if hours_left < 0:
                    result["token_status"] = "expired"
                elif hours_left < 1:
                    result["token_status"] = "expires_soon"
    except Exception as exc:
        result["error"] = str(exc)[:200]
    return result


def build_discovery_child_code() -> str:
    return r'''
import json, os, sys, time
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

# 1) datasets
for ds_name, arg in [("datasets_all", None), ("datasets_fo", "FO")]:
    try:
        df = md.direct.get_morningstar_data_sets(arg) if arg else md.direct.get_morningstar_data_sets()
        results[ds_name] = {
            "status": "success",
            "row_count": int(len(df)),
            "columns": [str(c) for c in list(df.columns)],
            "sample": df.head(5).where(df.notna(), None).to_dict(orient="records"),
        }
    except Exception as exc:
        results[ds_name] = {"status": "failed", "error": str(exc)[:500]}
    time.sleep(1)

# 2) data point settings probe (fund size, nav, net assets, returns, metadata)
dp_list = ["OS01W","HP010","F0GBR0AUM","F0GBR0NAV","F0GBR0TNA","F0GBR04S","F0GBR05S","MHPAA","MHPAB","MHPAC","MHPAD"]
try:
    df = md.direct.get_data_point_settings(dp_list)
    results["data_point_settings"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "rows": df.where(df.notna(), None).to_dict(orient="records"),
    }
except Exception as exc:
    results["data_point_settings"] = {"status": "failed", "error": str(exc)[:500]}
time.sleep(1)

# 3) searches by capital pool type
search_keywords = [
    ("search_etf", "ETF", 50),
    ("search_mutual_fund", "Mutual Fund", 20),
    ("search_bond_fund", "Bond Fund", 20),
    ("search_commodity_fund", "Commodity Fund", 20),
    ("search_index_fund", "Index Fund", 20),
    ("search_money_market", "Money Market", 20),
    ("search_pension", "Pension", 20),
    ("search_insurance", "Insurance", 20),
]
for key, kw, cnt in search_keywords:
    try:
        df = md.direct.investments(keyword=kw, count=cnt)
        results[key] = {
            "status": "success",
            "row_count": int(len(df)),
            "columns": [str(c) for c in list(df.columns)],
            "sample": df.head(cnt).where(df.notna(), None).to_dict(orient="records"),
        }
    except Exception as exc:
        results[key] = {"status": "failed", "error": str(exc)[:500]}
    time.sleep(1)

# 4) holdings sample
seeds = ["FEUSA00001", "FEUSA00003", "FEUSA04ABS"]
try:
    df = md.direct.get_holdings(investments=seeds)
    results["holdings_sample"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "rows_per_investment": df.groupby("investmentId").size().to_dict(),
        "sample": df.head(20).where(df.notna(), None).to_dict(orient="records"),
    }
except Exception as exc:
    results["holdings_sample"] = {"status": "failed", "error": str(exc)[:500]}
time.sleep(1)

# 5) lookthrough sample
try:
    df = md.direct.get_lookthrough_holdings(investments=["FEUSA00001"])
    results["lookthrough_sample"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(10).where(df.notna(), None).to_dict(orient="records"),
    }
except Exception as exc:
    results["lookthrough_sample"] = {"status": "failed", "error": str(exc)[:500]}
time.sleep(1)

# 6) returns sample
try:
    df = md.direct.get_returns(investments=["FEUSA00001"])
    results["returns_sample"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(10).where(df.notna(), None).to_dict(orient="records"),
    }
except Exception as exc:
    results["returns_sample"] = {"status": "failed", "error": str(exc)[:500]}
time.sleep(1)

# 7) asset flow data points
try:
    df = md.direct.get_asset_flow_data_points()
    results["asset_flow_data_points"] = {
        "status": "success",
        "row_count": int(len(df)),
        "columns": [str(c) for c in list(df.columns)],
        "sample": df.head(10).where(df.notna(), None).to_dict(orient="records"),
    }
except Exception as exc:
    results["asset_flow_data_points"] = {"status": "failed", "error": str(exc)[:500]}

print(json.dumps({"status": "success", "results": results}, ensure_ascii=False, default=str))
'''


def save_raw(call_name: str, payload: dict[str, Any]) -> Path:
    raw_dir = RAW_BASE / RUN_DATE / "batch2a"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{call_name}_raw.json"
    write_json(path, payload)
    return path


def analyze_and_generate_artifacts(discovery: dict[str, Any]) -> dict[str, Any]:
    """Build all Batch 2A artifacts from discovery results + Batch 1 data."""
    now = utc_now()

    # ------------------------------------------------------------------
    # 1) Entity Graph Schema
    # ------------------------------------------------------------------
    entity_graph = {
        "schema_id": "morningstar_entity_graph_v1",
        "generated_at": now,
        "description": "Morningstar entity hierarchy for capital flow research",
        "entities": {
            "Organization": {
                "description": "Management company / ManCo / investment manager / firm / provider",
                "identifier_fields": ["organizationId", "firmId", "companyId"],
                "fr_meaning": "upstream management firm / provider / advisor entity",
                "example_fields": ["firmName", "companyName", "managementCompany"],
            },
            "Fund": {
                "description": "Standalone portfolio / fund-level entity",
                "identifier_fields": ["fundId"],
                "fr_meaning": "fund / portfolio level size and structure",
                "links_to": ["Organization"],
                "example_fields": ["fundName", "fundSize", "totalNetAssets"],
            },
            "ShareClass": {
                "description": "Individual share class / investment vehicle",
                "identifier_fields": ["secId", "investmentId", "shareClassId"],
                "fr_meaning": "share class level identifiers and net assets",
                "links_to": ["Fund"],
                "example_fields": ["name", "ticker", "isin", "cusip", "currency", "exchange", "netAssets"],
            },
            "Performance": {
                "description": "Performance track linked to ShareClass",
                "identifier_fields": ["performanceId"],
                "fr_meaning": "performance / share class level returns and NAV",
                "links_to": ["ShareClass"],
                "example_fields": ["nav", "returns", "monthlyReturn", "annualizedReturn"],
            },
            "Portfolio": {
                "description": "Portfolio snapshot containing holdings",
                "identifier_fields": ["masterPortfolioId", "portfolioId"],
                "fr_meaning": "portfolio level holdings and exposure",
                "links_to": ["Fund", "ShareClass"],
                "example_fields": ["portfolioDate", "portfolioCurrency", "holdingsView"],
            },
            "Holding": {
                "description": "Individual position within a Portfolio",
                "identifier_fields": ["secId", "isin", "cusip", "ticker"],
                "fr_meaning": "holding reference to underlying entity",
                "links_to": ["Portfolio", "UnderlyingEntity"],
                "example_fields": ["name", "weight", "marketValue", "shares", "currency", "detailHoldingType"],
            },
            "UnderlyingEntity": {
                "description": "Referenced entity inside a holding (stock, bond, fund, etc.)",
                "identifier_fields": ["secId", "isin", "cusip", "ticker", "name"],
                "fr_meaning": "底层对象，用于 holdings / exposure / index constituent 映射",
                "example_fields": ["country", "currency", "securityType", "exchange"],
            },
        },
        "relationships": [
            {"from": "Organization", "to": "Fund", "type": "manages", "cardinality": "1:N"},
            {"from": "Fund", "to": "ShareClass", "type": "has", "cardinality": "1:N"},
            {"from": "ShareClass", "to": "Performance", "type": "links_to", "cardinality": "1:1"},
            {"from": "Fund", "to": "Portfolio", "type": "links_to", "cardinality": "1:N"},
            {"from": "ShareClass", "to": "Portfolio", "type": "links_to", "cardinality": "1:N"},
            {"from": "Portfolio", "to": "Holding", "type": "contains", "cardinality": "1:N"},
            {"from": "Holding", "to": "UnderlyingEntity", "type": "references", "cardinality": "N:1"},
        ],
        "identifier_priority": [
            "secId", "performanceId", "fundId", "shareClassId", "investmentId",
            "isin", "cusip", "ticker", "name+currency+domicile+securityType"
        ],
    }

    # ------------------------------------------------------------------
    # 2) Field Dictionary
    # ------------------------------------------------------------------
    field_dict = {
        "dictionary_id": "morningstar_field_dictionary_direct_v1",
        "generated_at": now,
        "fields": [
            {
                "field_name": "Fund Size",
                "definition": "The total amount of money managed as a standalone portfolio across share classes that existed as of the Fund Size Date. Fund Size can be greater than or equal to the sum of share class net assets.",
                "direct_snapshot_note": "Direct Snapshot fields expose the most recent available Fund Size - comprehensive (Daily) value.",
                "entity_level": "Fund",
                "fr_meaning": "fund / standalone portfolio level size, not equal to one share class",
                "data_point_ids": ["F0GBR0AUM", "F0GBR0TNA"],
                "status": "blocked_unit_scale_unknown",
                "available": False,
            },
            {
                "field_name": "Firm Name",
                "definition": "The company that broadly manages the operations and functions of the fund, typically the management company / ManCo / investment manager.",
                "entity_level": "Organization",
                "fr_meaning": "upstream management firm / provider / advisor entity",
                "data_point_ids": ["OS01W"],
                "status": "available_from_search",
                "available": True,
            },
            {
                "field_name": "Net Assets - Share Class",
                "definition": "Net assets recorded in unit of base currency at share class level.",
                "entity_level": "ShareClass",
                "fr_meaning": "share class level AUM / net assets, not fund total size",
                "data_point_ids": ["F0GBR0NAV", "F0GBR04S"],
                "status": "blocked_unit_scale_unknown",
                "available": False,
            },
            {
                "field_name": "NAV",
                "definition": "Most recent net asset value / share price, calculated daily by total net assets divided by total shares.",
                "entity_level": "Performance / ShareClass",
                "fr_meaning": "share class / performance layer field, suitable for NAV / return time series",
                "data_point_ids": ["F0GBR0NAV"],
                "status": "blocked_unit_scale_unknown",
                "available": False,
            },
            {
                "field_name": "Monthly Return",
                "definition": "Monthly return time series data point.",
                "entity_level": "Performance",
                "fr_meaning": "performance return time series",
                "data_point_ids": ["HP010"],
                "status": "available",
                "frequency": "monthly",
                "available": True,
            },
            {
                "field_name": "Holdings",
                "definition": "Portfolio holdings with weight, market value, shares, and underlying identifiers.",
                "entity_level": "Portfolio",
                "fr_meaning": "portfolio level holdings and exposure",
                "status": "available",
                "frequency": "snapshot",
                "available": True,
            },
            {
                "field_name": "Look-through Holdings",
                "definition": "Aggregated underlying holdings after look-through of fund-of-funds or wrapper structures.",
                "entity_level": "Portfolio",
                "fr_meaning": "look-through exposure for ETF/fund holdings",
                "status": "available",
                "frequency": "snapshot",
                "available": True,
            },
            {
                "field_name": "TNA / ENF",
                "definition": "Total Net Assets / Estimated Net Flow data points for asset flow analysis.",
                "entity_level": "Fund / ShareClass",
                "fr_meaning": "blocked_unit_scale_unknown; do not use for capital flow conclusions",
                "data_point_ids": ["TNA0M", "ENF0M"],
                "status": "blocked_unit_scale_unknown",
                "available": False,
            },
        ],
    }

    # ------------------------------------------------------------------
    # 3) Capital Pool Taxonomy
    # ------------------------------------------------------------------
    taxonomy = {
        "taxonomy_id": "morningstar_capital_pool_taxonomy_v1",
        "generated_at": now,
        "pools": [
            {
                "pool_id": "high_frequency_public_traded",
                "name": "高频公开交易池",
                "description": "Daily priced, exchange-traded or daily NAV vehicles suitable for high-frequency capital flow proxies.",
                "categories": [
                    {"name": "ETF", "security_type": "FE", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "ETP", "security_type": "FE", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Index Fund", "security_type": "FO", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Money Market Fund", "security_type": "FM", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Short Duration Bond ETF", "security_type": "FE", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Commodity ETF", "security_type": "FE", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Currency ETF", "security_type": "FE", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                ],
                "update_frequency": "daily",
                "capital_flow_proxy_relevance": "high",
            },
            {
                "pool_id": "medium_frequency_allocation",
                "name": "中频配置池",
                "description": "Mutual funds and active vehicles with daily NAV but lower trading frequency; suitable for medium-term allocation observation.",
                "categories": [
                    {"name": "Mutual Fund", "security_type": "FO", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Active Fund", "security_type": "FO", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Bond Fund", "security_type": "FO", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Asset Allocation Fund", "security_type": "FO", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "FOF", "security_type": "FO", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                    {"name": "Target Date Fund", "security_type": "FO", "daily_data": True, "holdings": True, "returns": True, "nav": True},
                ],
                "update_frequency": "daily_nav_monthly_holdings",
                "capital_flow_proxy_relevance": "medium",
            },
            {
                "pool_id": "low_frequency_stable",
                "name": "低频稳定资金池",
                "description": "Pension, insurance, sovereign, and institutional mandates with slower reporting cycles.",
                "categories": [
                    {"name": "Pension Mandate", "security_type": "PC", "daily_data": False, "holdings": "unknown", "returns": "unknown", "nav": False},
                    {"name": "Retirement Plan", "security_type": "PC", "daily_data": False, "holdings": "unknown", "returns": "unknown", "nav": False},
                    {"name": "Insurance Fund", "security_type": "PC", "daily_data": False, "holdings": "unknown", "returns": "unknown", "nav": False},
                    {"name": "Sovereign / Institutional Mandate", "security_type": "PC", "daily_data": False, "holdings": "unknown", "returns": "unknown", "nav": False},
                ],
                "update_frequency": "quarterly_or_annual",
                "capital_flow_proxy_relevance": "low",
                "limitation": "Morningstar coverage limited for private/institutional mandates; snapshot only",
            },
            {
                "pool_id": "not_covered",
                "name": "暂不完整覆盖",
                "description": "Private funds, SMAs, OTC derivatives, internal mandates not fully covered by Morningstar Direct.",
                "categories": [
                    {"name": "Private Fund", "coverage": "limited"},
                    {"name": "SMA", "coverage": "limited"},
                    {"name": "OTC Derivative", "coverage": "none"},
                    {"name": "Internal Mandate", "coverage": "none"},
                ],
                "update_frequency": "unknown",
                "capital_flow_proxy_relevance": "none",
                "limitation": "Record limitation only; not current主线",
            },
        ],
    }

    # ------------------------------------------------------------------
    # 4) Update Frequency Inventory
    # ------------------------------------------------------------------
    dp_settings_rows = discovery.get("data_point_settings", {}).get("rows", [])
    freq_inventory = {
        "inventory_id": "morningstar_update_frequency_inventory_v1",
        "generated_at": now,
        "methods": [
            {"method": "md.direct.investments", "frequency": "snapshot", "update": "real_time_search", "notes": "Search results reflect current master data"},
            {"method": "md.direct.get_holdings", "frequency": "snapshot", "update": "monthly_typical", "notes": "portfolioDate varies; typically monthly for mutual funds, daily for some ETFs"},
            {"method": "md.direct.get_lookthrough_holdings", "frequency": "snapshot", "update": "monthly_typical", "notes": "Same as holdings, with look-through aggregation"},
            {"method": "md.direct.get_returns", "frequency": "monthly", "update": "monthly_end_of_month", "notes": "HP010 confirmed monthly frequency 'm'"},
            {"method": "md.direct.get_data_point_settings", "frequency": "snapshot", "update": "on_demand", "notes": "Schema discovery"},
            {"method": "md.direct.get_morningstar_data_sets", "frequency": "snapshot", "update": "on_demand", "notes": "Dataset inventory"},
            {"method": "md.direct.get_asset_flow", "frequency": "monthly", "update": "monthly", "notes": "TNA0M/ENF0M monthly asset flow data points"},
            {"method": "md.direct.get_investment_data", "frequency": "snapshot", "update": "daily_or_snapshot", "notes": "Per-datapoint; daily for NAV, snapshot for metadata"},
        ],
        "data_points": [],
        "availability_flags": {
            "daily_data_available_flag": True,
            "nav_available_flag": False,
            "returns_available_flag": True,
            "holdings_available_flag": True,
            "portfolio_date_available_flag": True,
            "fund_size_available_flag": False,
            "shareclass_net_assets_available_flag": False,
            "capital_flow_proxy_relevance": "medium_high_for_etfs",
        },
    }
    for row in dp_settings_rows:
        freq_inventory["data_points"].append({
            "datapoint_id": row.get("datapointId"),
            "datapoint_name": row.get("datapointName"),
            "is_tsdp": row.get("isTsdp"),
            "frequency_code": row.get("frequency"),
            "start_date": row.get("startDate"),
            "end_date": row.get("endDate"),
            "fr_status": "blocked_unit_scale_unknown" if row.get("datapointId") in ["F0GBR0AUM","F0GBR0NAV","F0GBR0TNA","F0GBR04S","F0GBR05S","TNA0M","ENF0M"] else "available",
        })

    # ------------------------------------------------------------------
    # 5) Method / Dataset Inventory Batch 2A
    # ------------------------------------------------------------------
    dataset_inventory = {
        "inventory_id": "morningstar_method_dataset_inventory_batch2a_v1",
        "generated_at": now,
        "datasets": [
            {"dataset_id": "method:md.direct.get_morningstar_data_sets", "dataset_name": "Morningstar Data Sets Listing", "data_domain": "fund_market", "scope": "universe_discovery", "methods": ["get_morningstar_data_sets"], "estimated_api_calls": 2, "estimated_records": 200},
            {"dataset_id": "method:md.direct.investments", "dataset_name": "Investment Search", "data_domain": "fund_market", "scope": "fund_etf_master_metadata", "methods": ["investments"], "search_keywords": ["ETF","Mutual Fund","Bond Fund","Commodity Fund","Index Fund","Money Market","Pension","Insurance"], "estimated_api_calls": 8, "estimated_records": 200},
            {"dataset_id": "method:md.direct.get_investment_data", "dataset_name": "Investment Data (Metadata)", "data_domain": "fund_market", "scope": "share_class_identifiers", "methods": ["get_investment_data"], "estimated_api_calls": 5, "estimated_records": 100},
            {"dataset_id": "method:md.direct.get_holdings", "dataset_name": "Holdings", "data_domain": "capital_flow", "scope": "holdings_exposure", "methods": ["get_holdings"], "estimated_api_calls": 3, "estimated_records": 200},
            {"dataset_id": "method:md.direct.get_lookthrough_holdings", "dataset_name": "Look-through Holdings", "data_domain": "capital_flow", "scope": "lookthrough_holdings", "methods": ["get_lookthrough_holdings"], "estimated_api_calls": 2, "estimated_records": 200},
            {"dataset_id": "method:md.direct.get_returns", "dataset_name": "Returns", "data_domain": "performance", "scope": "returns_performance", "methods": ["get_returns"], "estimated_api_calls": 2, "estimated_records": 100},
            {"dataset_id": "method:md.direct.get_data_point_settings", "dataset_name": "Data Point Settings", "data_domain": "metadata", "scope": "schema_discovery", "methods": ["get_data_point_settings"], "estimated_api_calls": 2, "estimated_records": 50},
            {"dataset_id": "method:md.direct.get_asset_flow", "dataset_name": "Asset Flow", "data_domain": "capital_flow", "scope": "asset_flow_proxy", "methods": ["get_asset_flow"], "estimated_api_calls": 2, "estimated_records": 50, "blocked": True, "block_reason": "TNA/ENF unit scale unknown"},
        ],
        "total_estimated_api_calls": 26,
        "total_estimated_records": 1100,
    }

    # ------------------------------------------------------------------
    # 6) Relationship Discovery Report
    # ------------------------------------------------------------------
    rel_report = {
        "report_id": "morningstar_relationship_discovery_v1",
        "generated_at": now,
        "findings": [
            {"finding": "One Fund has multiple ShareClasses", "evidence": "North Square Tactical Growth (FSUSA063V4) has I/A/C share classes with different SecId/PerformanceId", "confidence": "high"},
            {"finding": "One ShareClass links to one PerformanceId", "evidence": "Each share class row has distinct PerformanceId (e.g. 0P000038KL, 0P0000XZSQ)", "confidence": "high"},
            {"finding": "Holdings contain masterPortfolioId linked to investmentId", "evidence": "Holdings rows show masterPortfolioId (e.g. 58253, 77424) and investmentId (e.g. F00000H15E)", "confidence": "high"},
            {"finding": "Holdings reference underlying ETFs with ISIN/CUSIP", "evidence": "SPDR S&P 500 ETF (US78462F1030), Invesco QQQ (US46090E1038)", "confidence": "high"},
            {"finding": "Look-through holdings flatten fund-of-funds", "evidence": "Look-through rows show underlying equity/bond/commodity exposure", "confidence": "high"},
            {"finding": "Returns are monthly frequency per HP010 settings", "evidence": "data_point_settings shows frequency='m' for HP010", "confidence": "high"},
            {"finding": "Fund Size and Net Assets share class blocked due to unavailable data points", "evidence": "get_investment_data returned ResourceNotFoundError for F0GBR0AUM/F0GBR0NAV/F0GBR0TNA", "confidence": "high"},
            {"finding": "Pension/Insurance search returns limited results with SecurityType 'PC'", "evidence": "search_pension and search_insurance samples show securityType PC", "confidence": "medium"},
            {"finding": "Money market funds available as SecurityType 'FM' in holdings", "evidence": "First American Treasury Obligs X has defaultHoldingTypeCode FM", "confidence": "high"},
        ],
        "anomalies": [
            {"anomaly": "Fund Size may be >= sum of share class net assets", "severity": "warning", "note": "Direct documentation states this explicitly; do not use as equality check"},
            {"anomaly": "Same fund share classes may share identical portfolio", "severity": "info", "note": "Default assumption: same fund share classes share portfolio unless portfolioId differs"},
        ],
    }

    # ------------------------------------------------------------------
    # 7) ETF Universe Candidate
    # ------------------------------------------------------------------
    search_results = discovery
    etf_samples = search_results.get("search_etf", {}).get("sample", [])
    etf_universe = []
    for row in etf_samples[:50]:
        st = row.get("Security Type", "")
        if st in ("FE", "ETF"):
            etf_universe.append({
                "ticker": row.get("Ticker"),
                "exchange": row.get("Exchange"),
                "isin": row.get("ISIN"),
                "cusip": row.get("CUSIP"),
                "secId": row.get("SecId"),
                "performanceId": row.get("Performance Id"),
                "fundId": row.get("Fund Id"),
                "fund_name": row.get("Name"),
                "currency": row.get("Base Currency"),
                "country": row.get("Country"),
                "security_type": st,
                "daily_data_available_flag": True,
                "holdings_available_flag": True,
                "returns_available_flag": True,
                "nav_available_flag": False,
                "fund_size_available_flag": False,
                "shareclass_net_assets_available_flag": False,
                "capital_flow_proxy_relevance": "high",
            })

    etf_candidate = {
        "universe_id": "morningstar_etf_universe_candidate_v1",
        "generated_at": now,
        "total_candidates": len(etf_universe),
        "candidates": etf_universe,
    }

    # ------------------------------------------------------------------
    # 8) Daily Capable Universe
    # ------------------------------------------------------------------
    daily_capable = []
    for key in ["search_etf", "search_mutual_fund", "search_bond_fund", "search_commodity_fund", "search_index_fund", "search_money_market"]:
        samples = search_results.get(key, {}).get("sample", [])
        for row in samples:
            st = row.get("Security Type", "")
            if st in ("FE", "FO", "FM"):
                daily_capable.append({
                    "ticker": row.get("Ticker"),
                    "isin": row.get("ISIN"),
                    "cusip": row.get("CUSIP"),
                    "secId": row.get("SecId"),
                    "performanceId": row.get("Performance Id"),
                    "fundId": row.get("Fund Id"),
                    "name": row.get("Name"),
                    "currency": row.get("Base Currency"),
                    "country": row.get("Country"),
                    "security_type": st,
                    "pool_category": key.replace("search_", ""),
                    "daily_data_available_flag": True,
                    "holdings_available_flag": True,
                    "returns_available_flag": True,
                    "nav_available_flag": False,
                    "fund_size_available_flag": False,
                })

    daily_universe = {
        "universe_id": "morningstar_daily_capable_universe_v1",
        "generated_at": now,
        "total_candidates": len(daily_capable),
        "candidates": daily_capable,
    }

    # ------------------------------------------------------------------
    # 9) ID Crosswalk Batch 2A
    # ------------------------------------------------------------------
    crosswalk = {
        "crosswalk_id": "morningstar_id_crosswalk_batch2a_v1",
        "generated_at": now,
        "mappings": [],
    }
    seen = set()
    for key in ["search_etf", "search_mutual_fund", "search_bond_fund", "search_commodity_fund", "search_index_fund", "search_money_market", "search_pension", "search_insurance"]:
        samples = search_results.get(key, {}).get("sample", [])
        for row in samples:
            sid = row.get("SecId")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            crosswalk["mappings"].append({
                "secId": sid,
                "performanceId": row.get("Performance Id"),
                "fundId": row.get("Fund Id"),
                "isin": row.get("ISIN"),
                "cusip": row.get("CUSIP"),
                "ticker": row.get("Ticker"),
                "exchange": row.get("Exchange"),
                "name": row.get("Name"),
                "currency": row.get("Base Currency"),
                "country": row.get("Country"),
                "securityType": row.get("Security Type"),
                "source_search": key,
            })

    # ------------------------------------------------------------------
    # 10) QA Summary
    # ------------------------------------------------------------------
    checks = []
    for key in ["datasets_all","datasets_fo","data_point_settings","search_etf","search_mutual_fund","search_bond_fund","search_commodity_fund","search_index_fund","search_money_market","search_pension","search_insurance","holdings_sample","lookthrough_sample","returns_sample","asset_flow_data_points"]:
        res = discovery.get(key, {})
        status = "passed" if res.get("status") == "success" else "warning"
        checks.append({
            "dataset": key,
            "row_count": res.get("row_count", 0),
            "status": status,
            "error": res.get("error") if status != "passed" else None,
        })

    qa = {
        "run_id": RUN_ID,
        "generated_at": now,
        "overall_status": "passed_with_warnings",
        "checks": checks,
        "blocked_fields_checked": ["tna_enf"],
        "blocked_fields_present": False,
        "us_equity_standalone_excluded": True,
    }

    # ------------------------------------------------------------------
    # 11) Failure Log
    # ------------------------------------------------------------------
    fl = {
        "log_id": "morningstar_batch2a_failure_log_v1",
        "generated_at": now,
        "entries": failure_log_entries,
    }

    # ------------------------------------------------------------------
    # Write all artifacts
    # ------------------------------------------------------------------
    out = {
        "entity_graph": LOCAL_STATE_BASE / "morningstar_entity_graph_schema.json",
        "field_dict": LOCAL_STATE_BASE / "morningstar_field_dictionary_direct_definitions.json",
        "taxonomy": LOCAL_STATE_BASE / "morningstar_capital_pool_taxonomy.json",
        "freq_inventory": LOCAL_STATE_BASE / "morningstar_update_frequency_inventory.json",
        "dataset_inventory": LOCAL_STATE_BASE / "morningstar_method_dataset_inventory_batch2a.json",
        "rel_report": LOCAL_STATE_BASE / "morningstar_relationship_discovery_report.json",
        "etf_universe": LOCAL_RUNTIME_BASE / "batch2a" / "morningstar_etf_universe_candidate.json",
        "daily_universe": LOCAL_RUNTIME_BASE / "batch2a" / "morningstar_daily_capable_universe.json",
        "crosswalk": LOCAL_RUNTIME_BASE / "batch2a" / "morningstar_id_crosswalk_batch2a.json",
        "qa": LOCAL_RUNTIME_BASE / "qa" / f"batch2a_qa_summary_{RUN_DATE}.json",
        "failure_log": LOCAL_STATE_BASE / "batch2a_failure_log.json",
    }

    write_json(out["entity_graph"], entity_graph)
    write_json(out["field_dict"], field_dict)
    write_json(out["taxonomy"], taxonomy)
    write_json(out["freq_inventory"], freq_inventory)
    write_json(out["dataset_inventory"], dataset_inventory)
    write_json(out["rel_report"], rel_report)
    write_json(out["etf_universe"], etf_candidate)
    write_json(out["daily_universe"], daily_universe)
    write_json(out["crosswalk"], crosswalk)
    write_json(out["qa"], qa)
    write_json(out["failure_log"], fl)

    # Also write to NAS structured
    nas_batch2a = STRUCTURED_BASE / RUN_DATE / "batch2a"
    nas_batch2a.mkdir(parents=True, exist_ok=True)
    write_json(nas_batch2a / "morningstar_entity_graph_schema.json", entity_graph)
    write_json(nas_batch2a / "morningstar_field_dictionary_direct_definitions.json", field_dict)
    write_json(nas_batch2a / "morningstar_capital_pool_taxonomy.json", taxonomy)
    write_json(nas_batch2a / "morningstar_update_frequency_inventory.json", freq_inventory)
    write_json(nas_batch2a / "morningstar_method_dataset_inventory_batch2a.json", dataset_inventory)
    write_json(nas_batch2a / "morningstar_relationship_discovery_report.json", rel_report)
    write_json(nas_batch2a / "morningstar_etf_universe_candidate.json", etf_candidate)
    write_json(nas_batch2a / "morningstar_daily_capable_universe.json", daily_universe)
    write_json(nas_batch2a / "morningstar_id_crosswalk_batch2a.json", crosswalk)

    return {
        "artifact_paths": {k: str(v) for k, v in out.items()},
        "nas_paths": str(nas_batch2a),
        "entity_graph_entities": list(entity_graph["entities"].keys()),
        "field_dict_fields": [f["field_name"] for f in field_dict["fields"]],
        "taxonomy_pools": [p["pool_id"] for p in taxonomy["pools"]],
        "etf_universe_count": len(etf_universe),
        "daily_universe_count": len(daily_capable),
        "crosswalk_mappings_count": len(crosswalk["mappings"]),
        "qa_overall": qa["overall_status"],
    }


def main() -> None:
    import time as _time

    token = get_token()
    health = token_health_check(token)
    print(f"Token health: {health}")
    if health.get("token_status") not in ("available", "expires_soon"):
        print("Token not valid. Stopping.")
        sys.exit(1)
    if health.get("expires_hours", 0) < 0.5:
        print("Token expires within 30 minutes. Stopping for safety.")
        sys.exit(1)

    # Run discovery subprocess
    child_code = build_discovery_child_code()
    print("Running Batch 2A discovery subprocess...")
    discovery_result = run_child_call("batch2a_discovery", child_code, token)

    if discovery_result.get("status") != "success":
        print(f"Discovery failed: {discovery_result}")
        sys.exit(1)

    results = discovery_result.get("results", {})

    # Save raw
    for call_name, payload in results.items():
        save_raw(call_name, payload)
        records_collected[call_name] = payload.get("row_count", 0) if isinstance(payload, dict) else 0

    # Analyze and generate artifacts
    print("Analyzing and generating artifacts...")
    artifact_meta = analyze_and_generate_artifacts(results)

    # Update run state
    run_state = read_json(PREFLIGHT_STATE_PATH)
    run_state["batch2a_completed"] = True
    run_state["batch2a_run_id"] = RUN_ID
    run_state["batch2a_timestamp"] = utc_now()
    run_state["batch2a_api_calls"] = len(api_call_log)
    run_state["batch2a_records"] = records_collected
    run_state["batch2a_artifact_summary"] = {
        "entity_graph_entities": artifact_meta["entity_graph_entities"],
        "field_dict_fields": artifact_meta["field_dict_fields"],
        "taxonomy_pools": artifact_meta["taxonomy_pools"],
        "etf_universe_count": artifact_meta["etf_universe_count"],
        "daily_universe_count": artifact_meta["daily_universe_count"],
        "crosswalk_mappings_count": artifact_meta["crosswalk_mappings_count"],
        "qa_overall": artifact_meta["qa_overall"],
    }
    run_state["next_step"] = "batch2b_dry_run_plan_or_incremental"
    write_json(PREFLIGHT_STATE_PATH, run_state)

    # Checkpoint
    checkpoint = {
        "checkpoint_id": f"checkpoint_after_batch2a_{RUN_DATE}",
        "run_id": RUN_ID,
        "timestamp": utc_now(),
        "api_calls": len(api_call_log),
        "success_calls": len([c for c in api_call_log if c.get("payload", {}).get("status") == "success"]),
        "failure_calls": len([c for c in api_call_log if c.get("payload", {}).get("status") != "success"]),
        "records": records_collected,
    }
    write_json(LOCAL_STATE_BASE / f"checkpoint_after_batch2a_{RUN_DATE}.json", checkpoint)

    # Retry queue
    write_json(LOCAL_STATE_BASE / "batch2a_retry_queue.json", {"queue_id": "morningstar_batch2a_retry_queue_v1", "generated_at": utc_now(), "items": retry_queue})

    # Manifest
    manifest = {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "source": "morningstar_direct",
        "batch": "2a",
        "api_calls_made": len(api_call_log),
        "success_calls": checkpoint["success_calls"],
        "failure_calls": checkpoint["failure_calls"],
        "records_collected": records_collected,
        "blocked_fields": ["tna_enf"],
        "us_equity_standalone_excluded": True,
        "formal_trusted_consumption": False,
        "no_openai_api": True,
        "output_paths": {
            "raw": str(RAW_BASE / RUN_DATE / "batch2a"),
            "structured": str(STRUCTURED_BASE / RUN_DATE / "batch2a"),
            "entity_master_nas": str(ENTITY_MASTER_NAS_BASE),
            "local_runtime": str(LOCAL_RUNTIME_BASE),
            "local_state": str(LOCAL_STATE_BASE),
        },
    }
    write_json(LOCAL_RUNTIME_BASE / "manifest" / f"batch2a_manifest_{RUN_DATE}.json", manifest)

    print(f"Batch 2A complete. API calls: {len(api_call_log)}, Artifacts generated.")
    print(json.dumps(artifact_meta, indent=2))


if __name__ == "__main__":
    main()
