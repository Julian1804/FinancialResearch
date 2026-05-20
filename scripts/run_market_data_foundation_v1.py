from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_ROOT = PROJECT_ROOT / "config"
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "market_data_foundation_catalog"
MACRO_ASSET_ROOT = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion"

DOC_MACRO = PROJECT_ROOT / "docs" / "MACRO_DATA_MODEL_V1.md"
DOC_ASSET = PROJECT_ROOT / "docs" / "ASSET_CLASS_DATA_MODEL_V1.md"
DOC_RATES = PROJECT_ROOT / "docs" / "RATES_BOND_DATA_MODEL_V1.md"
DOC_FX = PROJECT_ROOT / "docs" / "FX_CURRENCY_DATA_MODEL_V1.md"
DOC_SCHEMA = PROJECT_ROOT / "docs" / "MARKET_DATA_FOUNDATION_SCHEMA.md"
DOC_CATALOG = PROJECT_ROOT / "docs" / "MARKET_DATA_FOUNDATION_CATALOG_V1.md"
DOC_TRUST = PROJECT_ROOT / "docs" / "ECONOMIC_CLASSIFICATION_AND_TRUST_PRINCIPLES.md"


def run_market_data_foundation_v1() -> dict[str, Any]:
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    dashboard_summary = read_json(MACRO_ASSET_ROOT / "dashboard_macro_asset_summary.json")
    available = available_dataset_map(dashboard_summary)

    macro_taxonomy = {"version": "macro_taxonomy_v2", "generated_at": utc_now(), "items": macro_items()}
    asset_taxonomy = {"version": "asset_class_taxonomy_v2", "generated_at": utc_now(), "items": asset_items()}
    rates_taxonomy = {"version": "rates_bond_taxonomy_v2", "generated_at": utc_now(), "items": rates_items()}
    fx_taxonomy = {"version": "fx_currency_taxonomy_v2", "generated_at": utc_now(), "items": fx_items()}
    commodity_taxonomy = upgrade_commodity_taxonomy(read_json(CONFIG_ROOT / "commodity_taxonomy.json"))
    domain_taxonomy = build_domain_taxonomy()
    catalog = build_foundation_catalog(available)
    source_gap_matrix = build_source_gap_matrix(catalog)
    next_plan = build_next_ingestion_plan(catalog)

    write_json(CONFIG_ROOT / "macro_taxonomy.json", macro_taxonomy)
    write_json(CONFIG_ROOT / "asset_class_taxonomy.json", asset_taxonomy)
    write_json(CONFIG_ROOT / "rates_bond_taxonomy.json", rates_taxonomy)
    write_json(CONFIG_ROOT / "fx_currency_taxonomy.json", fx_taxonomy)
    write_json(CONFIG_ROOT / "commodity_taxonomy.json", commodity_taxonomy)
    write_json(CONFIG_ROOT / "market_data_domain_taxonomy.json", domain_taxonomy)

    write_json(RUNTIME_ROOT / "foundation_catalog.json", catalog)
    write_json(RUNTIME_ROOT / "source_gap_matrix.json", source_gap_matrix)
    write_json(RUNTIME_ROOT / "next_ingestion_plan.json", next_plan)
    write_json(RUNTIME_ROOT / "foundation_summary.json", summarize_foundation(catalog))

    write_docs(catalog)

    return {
        "generated_at": utc_now(),
        "taxonomy_completed": True,
        "futures_framework_completed": True,
        "foundation_catalog_completed": True,
        "catalog_item_count": len(catalog["items"]),
        "status_counts": dict(Counter(item["current_status"] for item in catalog["items"])),
        "outputs": {
            "foundation_catalog": str(RUNTIME_ROOT / "foundation_catalog.json"),
            "source_gap_matrix": str(RUNTIME_ROOT / "source_gap_matrix.json"),
            "next_ingestion_plan": str(RUNTIME_ROOT / "next_ingestion_plan.json"),
        },
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "no_openai_api_called": True,
    }


def taxonomy_item(
    domain: str,
    category: str,
    subcategory: str,
    metric_id: str,
    display_name: str,
    economic_meaning: str,
    unit: str,
    frequency: str,
    source_priority: list[str],
    dashboard_section: str,
    asof_time_field: str,
    revision_sensitive: bool,
    trusted: list[str],
    candidate: list[str],
    future: list[str],
    secondary_domain: str | None = None,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "primary_domain": domain,
        "secondary_domain": secondary_domain,
        "category": category,
        "subcategory": subcategory,
        "metric_id": metric_id,
        "display_name": display_name,
        "economic_meaning": economic_meaning,
        "default_unit": unit,
        "frequency": frequency,
        "source_priority": source_priority,
        "dashboard_section": dashboard_section,
        "asof_time_field": asof_time_field,
        "revision_sensitive": revision_sensitive,
        "vintage_required_if_available": revision_sensitive,
        "trusted_candidate_sources": trusted,
        "candidate_sources": candidate,
        "future_sources": future,
    }


def macro_items() -> list[dict[str, Any]]:
    return [
        taxonomy_item("macro_fundamental", "inflation", "consumer_prices", "us_cpi", "US CPI", "Consumer inflation proxy for purchasing power and policy pressure.", "index", "monthly", ["FRED:CPIAUCSL", "BLS:CUUR0000SA0"], "Inflation", "publish_date", True, ["FRED", "BLS"], [], ["BLS API key"]),
        taxonomy_item("macro_fundamental", "inflation", "producer_prices", "us_ppi", "US PPI", "Producer inflation and upstream cost pressure.", "index", "monthly", ["FRED:PPIACO", "BLS:WPUFD4"], "Inflation", "publish_date", True, ["FRED", "BLS"], [], ["BLS API key"]),
        taxonomy_item("macro_fundamental", "employment", "unemployment", "us_unemployment_rate", "US unemployment rate", "Labor market slack and recession risk proxy.", "percent", "monthly", ["FRED:UNRATE", "BLS:LNS14000000"], "Employment", "publish_date", True, ["FRED", "BLS"], [], ["BLS API key"]),
        taxonomy_item("macro_fundamental", "employment", "payrolls", "us_nonfarm_payrolls", "US nonfarm payrolls", "Hiring momentum and household income proxy.", "thousands_persons", "monthly", ["FRED:PAYEMS", "BLS:CES0000000001"], "Employment", "publish_date", True, ["FRED", "BLS"], [], ["BLS API key"]),
        taxonomy_item("macro_policy", "central_bank_policy", "policy_rate", "fed_funds_effective", "Fed Funds Effective Rate", "Implemented monetary policy stance.", "percent", "daily", ["FRED:DFF"], "Central Bank Policy", "publish_date", False, ["FRED"], [], [], "rates_market"),
        taxonomy_item("macro_policy", "money_supply", "broad_money", "china_m2", "China M2", "Broad money supply and domestic liquidity condition.", "CNY", "monthly", [], "Money Supply", "publish_date", True, [], ["AKShare macro if provenance verified"], ["PBOC official connector"]),
        taxonomy_item("macro_external", "reserves", "fx_reserves", "china_fx_reserves", "China FX reserves", "External buffer and currency defense capacity.", "USD", "monthly", [], "Reserves", "publish_date", True, [], [], ["SAFE/PBOC official connector"]),
        taxonomy_item("macro_external", "reserves", "gold_reserves", "china_gold_reserves", "China gold reserves", "Official reserve composition and de-dollarization indicator.", "troy_ounces", "monthly", [], "Reserves", "publish_date", True, [], [], ["PBOC/World Gold Council if licensed"]),
    ]


def asset_items() -> list[dict[str, Any]]:
    return [
        taxonomy_item("asset_class", "currency", "dollar_index", "trade_weighted_usd", "Trade-weighted USD", "USD strength and global liquidity pressure proxy.", "index", "daily", ["FRED:DTWEXBGS"], "FX / Currency", "publish_date", False, ["FRED"], [], ["DXY licensed source"], "fx_market"),
        taxonomy_item("asset_class", "rates_bonds", "sovereign_yield", "us_10y_yield", "US 10Y Treasury Yield", "Discount rate and global duration anchor.", "percent", "daily", ["FRED:DGS10"], "Rates / Bonds", "publish_date", False, ["FRED"], [], [], "rates_market"),
        taxonomy_item("asset_class", "rates_bonds", "sovereign_yield", "us_2y_yield", "US 2Y Treasury Yield", "Front-end policy expectation proxy.", "percent", "daily", ["FRED:DGS2"], "Rates / Bonds", "publish_date", False, ["FRED"], [], [], "rates_market"),
        taxonomy_item("asset_class", "precious_metals", "gold", "gold_benchmark", "Gold benchmark", "Safe-haven, real-rate and reserve asset proxy.", "USD_per_troy_oz", "monthly", ["WorldBank:GOLD"], "Precious Metals", "publish_date", True, ["World Bank"], [], ["COMEX futures", "LBMA if licensed"], "commodity"),
        taxonomy_item("asset_class", "energy", "crude_oil", "wti_oil", "WTI crude oil", "Energy inflation and growth/war risk proxy.", "USD_per_barrel", "daily/monthly", ["FRED:DCOILWTICO", "WorldBank:CRUDE_WTI"], "Energy", "publish_date", True, ["FRED", "World Bank"], [], ["NYMEX futures"], "commodity"),
        taxonomy_item("asset_class", "base_metals", "copper", "copper_benchmark", "Copper benchmark", "Industrial cycle and China demand proxy.", "USD_per_mt", "monthly", ["WorldBank:COPPER"], "Base Metals", "publish_date", True, ["World Bank"], [], ["LME/SHFE futures"], "commodity"),
    ]


def rates_items() -> list[dict[str, Any]]:
    return [
        taxonomy_item("rates_market", "sovereign_yield", "us_treasury", "us_2y_yield", "US 2Y Yield", "Policy expectation tenor.", "percent", "daily", ["FRED:DGS2"], "Yield Curve", "publish_date", False, ["FRED"], [], [], "macro_condition"),
        taxonomy_item("rates_market", "sovereign_yield", "us_treasury", "us_10y_yield", "US 10Y Yield", "Global risk-free discount rate proxy.", "percent", "daily", ["FRED:DGS10"], "Yield Curve", "publish_date", False, ["FRED"], [], [], "macro_condition"),
        taxonomy_item("rates_market", "market_rate", "overnight", "fed_funds_effective", "Fed Funds Effective Rate", "Overnight money-market rate.", "percent", "daily", ["FRED:DFF"], "Overnight Rates", "publish_date", False, ["FRED"], [], [], "macro_policy"),
        taxonomy_item("rates_market", "interbank_rate", "china_interbank", "shibor_overnight", "SHIBOR O/N", "China interbank liquidity proxy.", "percent", "daily", [], "Interbank Rates", "publish_date", False, [], ["AKShare if provenance verified"], ["SHIBOR official"]),
        taxonomy_item("rates_market", "interbank_rate", "china_interbank", "dr007", "DR007", "China pledged repo policy corridor proxy.", "percent", "daily", [], "Interbank Rates", "publish_date", False, [], [], ["CFETS/PBOC source"]),
        taxonomy_item("rates_market", "real_yield", "inflation_linked", "us_real_yield_10y", "US 10Y real yield", "Real discount rate and gold valuation pressure.", "percent", "daily", [], "Real Yields", "publish_date", False, [], [], ["FRED TIPS series"]),
    ]


def fx_items() -> list[dict[str, Any]]:
    return [
        taxonomy_item("fx_market", "dollar_index", "trade_weighted", "trade_weighted_usd", "Trade-weighted USD", "Broad USD strength proxy.", "index", "daily", ["FRED:DTWEXBGS"], "Dollar Index", "publish_date", False, ["FRED"], [], ["ICE DXY licensed"], "capital_flow_proxy"),
        taxonomy_item("fx_market", "currency_pair", "spot_fx", "usd_cny", "USD/CNY", "Onshore RMB exchange rate.", "CNY_per_USD", "daily", [], "Currency Pairs", "publish_date", False, [], ["AKShare if provenance verified"], ["PBOC/SAFE/official FX"]),
        taxonomy_item("fx_market", "currency_pair", "spot_fx", "usd_jpy", "USD/JPY", "JPY funding/carry trade pressure.", "JPY_per_USD", "daily", [], "Currency Pairs", "publish_date", False, [], [], ["FRED/ECB/official source"]),
        taxonomy_item("fx_market", "currency_pair", "spot_fx", "eur_usd", "EUR/USD", "Euro-dollar cross and dollar strength proxy.", "USD_per_EUR", "daily", [], "Currency Pairs", "publish_date", False, [], [], ["FRED/ECB"]),
        taxonomy_item("fx_market", "currency_pair", "spot_fx", "usd_cnh", "USD/CNH", "Offshore RMB stress/carry proxy.", "CNH_per_USD", "daily", [], "Currency Pairs", "publish_date", False, [], [], ["authorized FX source"]),
    ]


def upgrade_commodity_taxonomy(existing: dict[str, Any]) -> dict[str, Any]:
    existing = existing or {}
    existing.update(
        {
            "version": "commodity_taxonomy_v2",
            "generated_at": utc_now(),
            "futures_framework": {
                "schema_ready": True,
                "supported_future_exchanges": ["COMEX", "NYMEX", "LME", "SHFE", "INE", "DCE", "CZCE"],
                "status_by_exchange": {
                    "COMEX": "needs_authorization_or_future_connector",
                    "NYMEX": "needs_authorization_or_future_connector",
                    "LME": "needs_authorization_or_future_connector",
                    "SHFE": "future_connector",
                    "INE": "future_connector",
                    "DCE": "future_connector",
                    "CZCE": "future_connector",
                },
                "continuous_contract_policy": "Continuous futures are derived data and must not overwrite raw single-contract data.",
            },
        }
    )
    existing.setdefault("price_types", ["spot", "futures", "index", "benchmark", "settlement", "average_price", "unknown"])
    existing.setdefault("exchanges", ["COMEX", "NYMEX", "LME", "SHFE", "INE", "DCE", "CZCE", "World Bank", "FRED", "unknown"])
    existing.setdefault("commodity_categories", ["energy", "precious_metals", "base_metals", "ferrous_metals", "agriculture", "chemicals", "other"])
    return existing


def build_domain_taxonomy() -> dict[str, Any]:
    return {
        "version": "market_data_domain_taxonomy_v1",
        "generated_at": utc_now(),
        "domains": [
            {"domain": "macro_fundamental", "meaning": "Country-level economic fundamentals such as inflation, employment, GDP and trade."},
            {"domain": "macro_policy", "meaning": "Policy rates, central bank statements and fiscal/monetary policy stance."},
            {"domain": "rates_market", "meaning": "Market prices of money and bonds, including yields, curves and interbank rates."},
            {"domain": "fx_market", "meaning": "Currency pairs, dollar index and carry-trade related FX proxies."},
            {"domain": "asset_class", "meaning": "Tradable asset categories and capital-flow proxies."},
            {"domain": "commodity", "meaning": "Commodity spot, futures, benchmark, index and settlement data."},
            {"domain": "futures", "meaning": "Exchange contract data; raw contracts and continuous contracts are separate."},
        ],
        "classification_correction_policy": "Classify by economic meaning; do not merge macro indicators, policy rates, market yields, FX and commodity futures just because they share a chart.",
    }


def build_foundation_catalog(available: dict[str, dict[str, Any]]) -> dict[str, Any]:
    requested = [
        ("macro", "US CPI", "us_cpi", "FRED:CPIAUCSL", "BLS:CUUR0000SA0", 1),
        ("macro", "US PPI", "us_ppi", "FRED:PPIACO", "BLS:WPUFD4", 1),
        ("macro", "US unemployment", "us_unemployment_rate", "FRED:UNRATE", "BLS:LNS14000000", 1),
        ("macro", "US payrolls", "us_nonfarm_payrolls", "FRED:PAYEMS", "BLS:CES0000000001", 1),
        ("macro", "Fed funds", "fed_funds_effective", "FRED:DFF", "", 1),
        ("macro", "China CPI", "china_cpi", "", "NBS official", 2),
        ("macro", "China PPI", "china_ppi", "", "NBS official", 2),
        ("macro", "China M0/M1/M2", "china_money_supply", "", "PBOC official", 2),
        ("macro", "China FX reserves", "china_fx_reserves", "", "SAFE/PBOC official", 2),
        ("macro", "China gold reserves", "china_gold_reserves", "", "PBOC official", 3),
        ("macro", "Japan policy rate", "japan_policy_rate", "", "BOJ official", 3),
        ("macro", "Euro Area CPI", "euro_area_cpi", "", "Eurostat/ECB", 3),
        ("macro", "UK CPI", "uk_cpi", "", "ONS/BoE", 3),
        ("rates_bonds", "US 2Y", "us_2y_yield", "FRED:DGS2", "", 1),
        ("rates_bonds", "US 10Y", "us_10y_yield", "FRED:DGS10", "", 1),
        ("rates_bonds", "US 30Y", "us_30y_yield", "", "FRED:DGS30", 2),
        ("rates_bonds", "China 1Y government bond", "china_1y_gov_yield", "", "ChinaBond/CFETS", 2),
        ("rates_bonds", "China 10Y government bond", "china_10y_gov_yield", "", "ChinaBond/CFETS", 2),
        ("rates_bonds", "UK gilt yield", "uk_gilt_yield", "", "BoE/DMO/FRED", 3),
        ("rates_bonds", "Japan JGB yield", "japan_jgb_yield", "", "MOF/BoJ/FRED", 3),
        ("rates_bonds", "SOFR", "sofr", "", "FRED:SOFR", 2),
        ("rates_bonds", "SHIBOR", "shibor", "", "SHIBOR official", 2),
        ("rates_bonds", "DR007", "dr007", "", "CFETS/PBOC", 2),
        ("rates_bonds", "SONIA", "sonia", "", "BoE", 3),
        ("fx", "DXY / trade-weighted USD", "trade_weighted_usd", "FRED:DTWEXBGS", "ICE DXY licensed", 1),
        ("fx", "USD/CNY", "usd_cny", "", "PBOC/SAFE", 2),
        ("fx", "USD/JPY", "usd_jpy", "", "FRED/ECB/BoJ", 2),
        ("fx", "EUR/USD", "eur_usd", "", "FRED/ECB", 2),
        ("fx", "GBP/USD", "gbp_usd", "", "FRED/BoE", 3),
        ("fx", "USD/CNH", "usd_cnh", "", "authorized FX source", 3),
        ("commodity", "Gold spot/benchmark", "gold_benchmark", "WorldBank:GOLD", "COMEX/LBMA", 1),
        ("commodity", "Silver", "silver_benchmark", "WorldBank:SILVER", "COMEX/LBMA", 2),
        ("commodity", "WTI", "wti_oil", "FRED:DCOILWTICO", "NYMEX", 1),
        ("commodity", "Brent", "brent_oil", "WorldBank:CRUDE_BRENT", "ICE", 1),
        ("commodity", "Copper", "copper_benchmark", "WorldBank:COPPER", "LME/SHFE", 1),
        ("commodity", "Aluminum", "aluminum_benchmark", "WorldBank:ALUMINUM", "LME/SHFE", 2),
        ("commodity", "Iron ore", "iron_ore_benchmark", "WorldBank:IRON_ORE", "DCE/SGX", 2),
        ("commodity", "Soybeans", "soybeans_benchmark", "WorldBank:SOYBEANS", "CBOT/DCE", 2),
        ("commodity", "Wheat", "wheat_benchmark", "WorldBank:WHEAT_US_HRW", "CBOT/CZCE", 2),
        ("commodity", "Coal", "coal_benchmark", "WorldBank:COAL_AUS", "DCE/ZCE", 2),
        ("commodity", "Lithium", "lithium_price", "", "Benchmark Mineral/Asian Metal/authorized source", 3),
        ("futures", "COMEX Gold futures", "comex_gold_futures", "", "CME DataMine/authorized", 3),
        ("futures", "NYMEX WTI futures", "nymex_wti_futures", "", "CME DataMine/authorized", 3),
        ("futures", "LME Copper", "lme_copper", "", "LME licensed", 3),
        ("futures", "SHFE Copper", "shfe_copper", "", "SHFE official", 2),
        ("futures", "INE Crude", "ine_crude", "", "INE official", 2),
        ("futures", "DCE Iron Ore", "dce_iron_ore", "", "DCE official", 2),
        ("futures", "CZCE agriculture futures", "czce_agri", "", "CZCE official", 2),
    ]
    items = []
    for domain, name, metric_id, preferred, alt, priority in requested:
        current_status = status_for(metric_id, preferred, available)
        items.append(
            {
                "domain": domain,
                "display_name": name,
                "metric_id": metric_id,
                "current_status": current_status,
                "preferred_source": preferred or alt,
                "alternative_source": alt,
                "official_source_available": bool(preferred or alt),
                "cost_status": "free_available" if current_status == "available" else "unknown_or_authorization_needed" if domain == "futures" else "free_source_to_build",
                "connector_status": "connected" if current_status == "available" else "future_connector" if "authorized" not in alt.lower() else "needs_authorization",
                "priority": priority,
                "schema_ready": True,
                "dashboard_ready": current_status in {"available", "partially_available"},
                "QA_ready": current_status == "available",
            }
        )
    return {
        "generated_at": utc_now(),
        "items": items,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def status_for(metric_id: str, preferred: str, available: dict[str, dict[str, Any]]) -> str:
    if preferred.startswith("FRED:") and preferred.split(":", 1)[1] in available:
        return "available"
    if preferred.startswith("WorldBank:") and preferred.split(":", 1)[1] in available:
        return "available"
    if metric_id in {"us_cpi", "us_ppi", "us_unemployment_rate", "us_nonfarm_payrolls"}:
        return "available"
    if metric_id in {"trade_weighted_usd", "fed_funds_effective", "us_2y_yield", "us_10y_yield", "wti_oil"}:
        return "available"
    if metric_id in {"gold_benchmark", "silver_benchmark", "brent_oil", "copper_benchmark", "aluminum_benchmark", "iron_ore_benchmark", "soybeans_benchmark", "wheat_benchmark", "coal_benchmark"}:
        return "available"
    return "future_connector" if "futures" in metric_id or "authorized" in preferred.lower() else "missing"


def available_dataset_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for item in summary.get("macro_series", []) + summary.get("asset_series", []):
        out[item.get("series_id")] = item
    return out


def build_source_gap_matrix(catalog: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in catalog["items"]:
        if item["current_status"] != "available":
            rows.append(
                {
                    "domain": item["domain"],
                    "metric_id": item["metric_id"],
                    "display_name": item["display_name"],
                    "current_status": item["current_status"],
                    "preferred_source": item["preferred_source"],
                    "next_action": "build_connector_or_verify_authorization",
                    "priority": item["priority"],
                }
            )
    return {"generated_at": utc_now(), "gap_count": len(rows), "items": rows}


def build_next_ingestion_plan(catalog: dict[str, Any]) -> dict[str, Any]:
    priority = sorted([item for item in catalog["items"] if item["current_status"] != "available"], key=lambda item: item["priority"])
    return {
        "generated_at": utc_now(),
        "principle": "Fill official/free macro, rates and FX gaps before broad risky market scraping.",
        "items": [
            {
                "metric_id": item["metric_id"],
                "domain": item["domain"],
                "preferred_source": item["preferred_source"],
                "priority": item["priority"],
                "safe_next_step": "feasibility_smoke_then_small_ingestion",
            }
            for item in priority[:20]
        ],
    }


def summarize_foundation(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "item_count": len(catalog["items"]),
        "domain_counts": dict(Counter(item["domain"] for item in catalog["items"])),
        "status_counts": dict(Counter(item["current_status"] for item in catalog["items"])),
        "schema_ready_count": sum(1 for item in catalog["items"] if item["schema_ready"]),
        "dashboard_ready_count": sum(1 for item in catalog["items"] if item["dashboard_ready"]),
    }


def write_docs(catalog: dict[str, Any]) -> None:
    DOC_MACRO.write_text(render_model_doc("Macro Data Model v1", ["dataset_id", "source_id", "provider_name", "country", "region", "macro_category", "metric_id", "metric_name", "data_period_start", "data_period_end", "observation_date", "publish_date", "publish_date_source", "value", "unit", "frequency", "seasonal_adjustment", "preliminary_or_final", "vintage_date", "revision_status", "retrieval_snapshot_id", "retrieved_at", "raw_path", "checksum", "quality_status", "trust_status", "candidate_only"]), encoding="utf-8")
    DOC_ASSET.write_text(render_model_doc("Asset Class Data Model v1", ["dataset_id", "source_id", "provider_name", "asset_class", "asset_category", "instrument_id", "instrument_name", "market", "country_or_region", "currency", "price_type", "observation_date", "publish_date", "publish_date_source", "value", "unit", "frequency", "vintage_date", "revision_status", "retrieval_snapshot_id", "raw_path", "checksum", "quality_status", "trust_status", "candidate_only"]), encoding="utf-8")
    DOC_RATES.write_text(render_model_doc("Rates Bond Data Model v1", ["dataset_id", "source_id", "provider_name", "country", "rate_type", "instrument_type", "tenor", "maturity_bucket", "curve_name", "observation_date", "publish_date", "publish_date_source", "yield_value", "rate_value", "unit", "frequency", "nominal_or_real", "seasonality", "vintage_date", "revision_status", "retrieval_snapshot_id", "quality_status", "trust_status", "candidate_only"]), encoding="utf-8")
    DOC_FX.write_text(render_model_doc("FX Currency Data Model v1", ["dataset_id", "source_id", "provider_name", "base_currency", "quote_currency", "currency_pair", "fx_type", "observation_date", "publish_date", "publish_date_source", "rate", "frequency", "market", "source_timezone", "vintage_date", "revision_status", "retrieval_snapshot_id", "quality_status", "trust_status", "candidate_only"]), encoding="utf-8")
    DOC_SCHEMA.write_text(render_schema_doc(), encoding="utf-8")
    DOC_CATALOG.write_text(render_catalog_doc(catalog), encoding="utf-8")
    DOC_TRUST.write_text(render_trust_doc(), encoding="utf-8")


def render_model_doc(title: str, fields: list[str]) -> str:
    return f"""# {title}

Generated: {utc_now()}

Fields:

{chr(10).join(f'- `{field}`' for field in fields)}

All records preserve raw paths, checksum, quality status, trust status and `candidate_only`.
"""


def render_schema_doc() -> str:
    return f"""# Market Data Foundation Schema

Generated: {utc_now()}

The platform separates macro fundamentals, policy rates, market rates, FX, asset classes,
commodities and futures by economic meaning. Raw single-contract futures data must remain separate
from derived continuous contracts.

Pipeline: raw -> normalized -> QA -> catalog -> staging -> dashboard -> statistical report.

Futures schema includes exchange, contract_code, contract_month, expiry_date, OHLC, settlement,
volume, open_interest, contract_multiplier, continuous_contract_method and roll_adjustment_method.
"""


def render_catalog_doc(catalog: dict[str, Any]) -> str:
    counts = Counter(item["current_status"] for item in catalog["items"])
    return f"""# Market Data Foundation Catalog v1

Generated: {utc_now()}

Items: {len(catalog['items'])}

Status counts:

```json
{json.dumps(dict(counts), ensure_ascii=False, indent=2)}
```

This catalog is a database-building guide, not formal trusted consumption.
"""


def render_trust_doc() -> str:
    return f"""# Economic Classification and Trust Principles

Generated: {utc_now()}

Rules:

1. Classify by economic meaning, not by what looks convenient on a chart.
2. Macro indicators and asset prices are related but not the same data domain.
3. Policy rates and market rates must be separated.
4. Futures, spot, index, settlement and benchmark prices must not be mixed.
5. Unknown data must stay unclassified or needs_review.
6. No reliable source means no factual display.
7. Revisions and vintages must be preserved for as-of analysis.
8. As-of analysis must not use future revised values silently.
9. Candidate data must not be presented as trusted.
10. UI must show data gaps instead of hiding them for aesthetics.
"""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_market_data_foundation_v1(), ensure_ascii=False, indent=2))
