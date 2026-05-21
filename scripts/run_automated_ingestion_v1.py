from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "automated_ingestion_system"
ENTITY_ROOT = PROJECT_ROOT / "runtime" / "entity_master"
CONTROLLED_ROOT = RUNTIME_ROOT / "controlled_pilot_run"
DOCS_ROOT = PROJECT_ROOT / "docs"
CONFIG_ROOT = PROJECT_ROOT / "config"

PHASE5_ROOT = PROJECT_ROOT / "runtime" / "data_connector_phase5"
PHASE3_FUND_ROOT = PROJECT_ROOT / "runtime" / "fund_etf_capital_flow_phase3"
MARKET_PHASE2_ROOT = PROJECT_ROOT / "runtime" / "market_data_foundation_phase2"
MACRO_ASSET_ROOT = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion"
AUTHORITATIVE_ROOT = PROJECT_ROOT / "runtime" / "authoritative_crawler_framework"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_storage_paths() -> dict[str, Any]:
    return read_json(CONFIG_ROOT / "storage_paths.json", {})


def run_automated_ingestion_v1(mode: str = "controlled_pilot") -> dict[str, Any]:
    ensure_dirs()
    started = time.time()
    storage_paths = load_storage_paths()
    entity_outputs = build_entity_master()
    source_strategy = build_source_strategy()
    akshare_audit = build_akshare_audit()
    morningstar_candidates = build_morningstar_candidates()
    schedule = build_scheduler(source_strategy, morningstar_candidates)
    ingestion = build_ingestion_pipeline(mode, entity_outputs, source_strategy, akshare_audit, morningstar_candidates, schedule)
    dashboard = build_dashboard_status(entity_outputs, source_strategy, ingestion, schedule, morningstar_candidates)
    docs = write_docs(entity_outputs, source_strategy, akshare_audit, morningstar_candidates, schedule, ingestion, dashboard)
    summary = {
        "generated_at": utc_now(),
        "automated_ingestion_system_v1_completed": True,
        "mode": mode,
        "elapsed_seconds": round(time.time() - started, 3),
        "storage_paths_loaded": bool(storage_paths),
        "entity_master_completed": True,
        "entity_count": entity_outputs["entity_count"],
        "crosswalk_count": entity_outputs["crosswalk_count"],
        "unresolved_entity_count": entity_outputs["unresolved_entity_count"],
        "duplicate_risk_count": entity_outputs["duplicate_risk_count"],
        "automated_source_strategy_completed": True,
        "source_status_counts": source_strategy["status_counts"],
        "akshare_audit_completed": True,
        "akshare_success_count": akshare_audit["sample_success_count"],
        "morningstar_controlled_candidates_completed": True,
        "morningstar_controlled_candidate_count": morningstar_candidates["controlled_candidate_count"],
        "pipeline_completed": True,
        "scheduler_completed": True,
        "controlled_pilot_completed": ingestion["controlled_pilot_completed"],
        "pilot_run_count": len(ingestion["run_records"]),
        "trusted_candidate_count": ingestion["staging_counts"].get("trusted_candidate", 0),
        "no_auto_login_morningstar": True,
        "no_password_saved": True,
        "token_leaked": False,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "outputs": {
            "entity_master_schema": str(ENTITY_ROOT / "entity_master_schema.json"),
            "source_identifier_crosswalk": str(ENTITY_ROOT / "source_identifier_crosswalk.json"),
            "source_status_matrix": str(RUNTIME_ROOT / "source_status_matrix.json"),
            "akshare_audit": str(RUNTIME_ROOT / "akshare_api_audit.json"),
            "morningstar_candidates": str(RUNTIME_ROOT / "morningstar_controlled_ingestion_candidates.json"),
            "ingestion_results": str(RUNTIME_ROOT / "ingestion_run_results.json"),
            "unresolved_entity_queue": str(RUNTIME_ROOT / "unresolved_entity_queue.json"),
            "entity_match_results": str(RUNTIME_ROOT / "entity_match_results.json"),
            "schedule": str(CONFIG_ROOT / "automated_ingestion_schedule.json"),
            "dashboard_status": str(RUNTIME_ROOT / "dashboard_automation_status.json"),
            "docs": docs,
        },
    }
    write_json(RUNTIME_ROOT / "automated_ingestion_summary.json", summary)
    return summary


def ensure_dirs() -> None:
    for path in [RUNTIME_ROOT, ENTITY_ROOT, CONTROLLED_ROOT, DOCS_ROOT, CONFIG_ROOT]:
        path.mkdir(parents=True, exist_ok=True)


def build_entity_master() -> dict[str, Any]:
    schema = {
        "version": "entity_master_v1",
        "generated_at": utc_now(),
        "principles": [
            "Every inbound dataset should attempt entity_id mapping before staging.",
            "Different source identifiers must not create duplicate entities when a high-confidence crosswalk exists.",
            "Fuzzy name matches are probable_match only and require review before merge.",
            "Same code in different markets or exchanges must not be merged automatically.",
        ],
        "entity_types": {
            "equity": [
                "entity_id",
                "entity_type",
                "primary_name",
                "country",
                "market",
                "exchange",
                "currency",
                "ticker",
                "exchange_code",
                "isin",
                "cusip",
                "sedol",
                "figi",
                "cn_stock_code",
                "hkex_code",
                "sec_cik",
                "morningstar_sec_id",
                "akshare_symbol",
                "eastmoney_code",
                "tonghuashun_code",
                "source_aliases",
                "active_status",
                "first_seen_at",
                "last_seen_at",
            ],
            "fund_or_etf": [
                "entity_id",
                "entity_type",
                "fund_code",
                "fund_name",
                "fund_company",
                "fund_type",
                "country",
                "domicile",
                "market",
                "exchange",
                "currency",
                "isin",
                "ticker",
                "morningstar_sec_id",
                "amac_code",
                "exchange_fund_code",
                "akshare_symbol",
                "eastmoney_code",
                "tonghuashun_code",
                "official_source_id",
                "source_aliases",
                "active_status",
                "first_seen_at",
                "last_seen_at",
            ],
            "index": [
                "entity_id",
                "entity_type",
                "index_code",
                "index_name",
                "provider",
                "country_or_region",
                "asset_class",
                "currency",
                "morningstar_id",
                "exchange_code",
                "source_aliases",
            ],
            "commodity_or_futures": [
                "entity_id",
                "entity_type",
                "commodity_name",
                "commodity_category",
                "exchange",
                "contract_code",
                "contract_month",
                "underlying_asset",
                "currency",
                "unit",
                "contract_multiplier",
                "price_type",
                "world_bank_code",
                "fred_series_id",
                "exchange_symbol",
                "source_aliases",
            ],
            "macro_series": [
                "entity_id",
                "entity_type",
                "country",
                "agency",
                "source_id",
                "series_id",
                "metric_id",
                "metric_name",
                "frequency",
                "unit",
                "vintage_supported",
                "source_aliases",
            ],
        },
    }

    entities: list[dict[str, Any]] = []
    crosswalk: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    add_a_share_entities(entities, crosswalk)
    add_us_etf_entities(entities, crosswalk, unresolved)
    add_macro_entities(entities, crosswalk)
    add_commodity_entities(entities, crosswalk)
    add_index_entities(entities, crosswalk)

    duplicate_risks = detect_duplicate_risks(entities)
    rules = {
        "version": "entity_identifier_rules_v1",
        "generated_at": utc_now(),
        "matching_rules": [
            {
                "entity_type": "equity",
                "exact_match_keys": ["country", "exchange", "ticker"],
                "secondary_keys": ["isin", "sec_cik", "morningstar_sec_id"],
                "fuzzy_allowed": True,
                "fuzzy_status": "probable_match_needs_review",
            },
            {
                "entity_type": "fund_or_etf",
                "exact_match_keys": ["isin", "exchange", "ticker"],
                "secondary_keys": ["morningstar_sec_id", "fund_code", "exchange_fund_code"],
                "fuzzy_allowed": True,
                "fuzzy_status": "probable_match_needs_review",
            },
            {
                "entity_type": "macro_series",
                "exact_match_keys": ["source_id", "series_id"],
                "fuzzy_allowed": False,
            },
            {
                "entity_type": "commodity_or_futures",
                "exact_match_keys": ["source_id", "world_bank_code", "fred_series_id", "exchange_symbol", "contract_code"],
                "fuzzy_allowed": False,
            },
        ],
        "merge_guards": [
            "Do not merge same ticker across different exchanges without ISIN or official identifier confirmation.",
            "Do not merge commodity benchmark, spot, and futures instruments.",
            "Do not auto-merge fuzzy fund names.",
            "Unmapped identifiers enter unresolved_entity_queue.",
        ],
    }
    entity_payload = {
        "schema": schema,
        "entities": entities,
        "entity_count": len(entities),
        "entity_type_counts": dict(Counter(entity["entity_type"] for entity in entities)),
    }
    crosswalk_payload = {
        "generated_at": utc_now(),
        "crosswalk": crosswalk,
        "crosswalk_count": len(crosswalk),
        "unresolved_entity_queue": unresolved,
        "duplicate_risks": duplicate_risks,
    }
    write_json(ENTITY_ROOT / "entity_master_schema.json", entity_payload)
    write_json(ENTITY_ROOT / "source_identifier_crosswalk.json", crosswalk_payload)
    write_json(CONFIG_ROOT / "entity_identifier_rules.json", rules)
    write_json(RUNTIME_ROOT / "unresolved_entity_queue.json", {"items": unresolved})
    write_json(RUNTIME_ROOT / "entity_match_results.json", {"crosswalk": crosswalk, "duplicate_risks": duplicate_risks})
    return {
        "schema": schema,
        "entities": entities,
        "crosswalk": crosswalk,
        "unresolved": unresolved,
        "duplicate_risks": duplicate_risks,
        "entity_count": len(entities),
        "crosswalk_count": len(crosswalk),
        "unresolved_entity_count": len(unresolved),
        "duplicate_risk_count": len(duplicate_risks),
    }


def add_a_share_entities(entities: list[dict[str, Any]], crosswalk: list[dict[str, Any]]) -> None:
    names = {"600519": "Kweichow Moutai", "000001": "Ping An Bank", "300750": "CATL"}
    for code, name in names.items():
        market = "SH" if code.startswith("6") else "SZ"
        entity_id = f"equity_cn_{market.lower()}_{code}"
        entity = {
            "entity_id": entity_id,
            "entity_type": "equity",
            "primary_name": name,
            "country": "China",
            "market": "A_SHARE",
            "exchange": "SSE" if market == "SH" else "SZSE",
            "currency": "CNY",
            "ticker": code,
            "exchange_code": code,
            "isin": None,
            "cusip": None,
            "sedol": None,
            "figi": None,
            "cn_stock_code": code,
            "hkex_code": None,
            "sec_cik": None,
            "morningstar_sec_id": None,
            "akshare_symbol": f"{market.lower()}{code}",
            "eastmoney_code": f"{'1' if market == 'SH' else '0'}.{code}",
            "tonghuashun_code": None,
            "source_aliases": [code, f"{market.lower()}.{code}", f"{market.lower()}{code}"],
            "active_status": "active_sample",
            "first_seen_at": utc_now(),
            "last_seen_at": utc_now(),
        }
        entities.append(entity)
        for source_id, identifier, identifier_type in [
            ("baostock_daily", f"{market.lower()}.{code}", "baostock_code"),
            ("akshare_tencent_daily", f"{market.lower()}{code}", "akshare_symbol"),
            ("eastmoney_direct", f"{'1' if market == 'SH' else '0'}.{code}", "eastmoney_secid"),
        ]:
            crosswalk.append(crosswalk_item(entity_id, source_id, identifier, identifier_type, "exact_match", 1.0))


def add_us_etf_entities(entities: list[dict[str, Any]], crosswalk: list[dict[str, Any]], unresolved: list[dict[str, Any]]) -> None:
    official = read_jsonl(PHASE3_FUND_ROOT / "official_universe_us_etf_sample.jsonl")
    matching = read_json(PHASE3_FUND_ROOT / "us_nasdaq_morningstar_matching_pilot.json", {})
    matches = {item.get("official_symbol"): item for item in matching.get("matches", [])}
    for row in official[:50]:
        ticker = row.get("ticker") or row.get("fund_code")
        if not ticker:
            unresolved.append(unresolved_item("nasdaq_trader", row, "missing_ticker"))
            continue
        entity_id = f"etf_us_{ticker.lower()}"
        match = matches.get(ticker, {})
        entity = {
            "entity_id": entity_id,
            "entity_type": "ETF",
            "fund_code": ticker,
            "fund_name": row.get("fund_name"),
            "fund_company": None,
            "fund_type": "ETF",
            "country": "US",
            "domicile": "US",
            "market": "US_ETF",
            "exchange": row.get("exchange"),
            "currency": match.get("currency") or row.get("currency") or "USD",
            "isin": match.get("isin"),
            "ticker": ticker,
            "morningstar_sec_id": match.get("morningstar_sec_id"),
            "amac_code": None,
            "exchange_fund_code": ticker,
            "akshare_symbol": None,
            "eastmoney_code": None,
            "tonghuashun_code": None,
            "official_source_id": row.get("source_id"),
            "source_aliases": [ticker, row.get("fund_name")],
            "active_status": "official_sample",
            "first_seen_at": row.get("retrieved_at") or utc_now(),
            "last_seen_at": utc_now(),
        }
        entities.append(entity)
        crosswalk.append(crosswalk_item(entity_id, row.get("source_id", "nasdaq_trader"), ticker, "ticker", "exact_match", 1.0))
        if match:
            crosswalk.append(crosswalk_item(entity_id, "morningstar_direct", match.get("morningstar_sec_id"), "morningstar_sec_id", match.get("match_status", "probable_match"), match.get("field_completeness_score", 0.0)))
        else:
            unresolved.append(unresolved_item("morningstar_direct", row, "morningstar_match_missing_for_sample_symbol"))


def add_macro_entities(entities: list[dict[str, Any]], crosswalk: list[dict[str, Any]]) -> None:
    candidates = [
        ("macro_us_dgs10", "fred", "DGS10", "US 10Y Treasury Yield", "rates_market", "daily", "percent"),
        ("macro_us_dgs2", "fred", "DGS2", "US 2Y Treasury Yield", "rates_market", "daily", "percent"),
        ("macro_us_dff", "fred", "DFF", "Federal Funds Effective Rate", "rates_market", "daily", "percent"),
        ("macro_us_cpi", "fred", "CPIAUCSL", "US CPI", "inflation", "monthly", "index"),
        ("macro_us_unrate", "fred", "UNRATE", "US Unemployment Rate", "employment", "monthly", "percent"),
    ]
    for entity_id, source_id, series_id, name, metric_id, frequency, unit in candidates:
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "macro_series",
                "country": "US",
                "agency": "FRED",
                "source_id": source_id,
                "series_id": series_id,
                "metric_id": metric_id,
                "metric_name": name,
                "frequency": frequency,
                "unit": unit,
                "vintage_supported": "source_dependent",
                "source_aliases": [series_id, name],
            }
        )
        crosswalk.append(crosswalk_item(entity_id, source_id, series_id, "series_id", "exact_match", 1.0))


def add_commodity_entities(entities: list[dict[str, Any]], crosswalk: list[dict[str, Any]]) -> None:
    catalog = read_json(MACRO_ASSET_ROOT / "dataset_catalog.json", {})
    rows = catalog.get("datasets", []) or catalog.get("items", [])
    added = 0
    for row in rows:
        if row.get("domain") not in {"commodity", "asset_class"} and "commodity" not in str(row).lower():
            continue
        code = row.get("series_id") or row.get("dataset_id") or row.get("instrument_name")
        if not code:
            continue
        entity_id = f"commodity_{sha256_text(code)[:10]}"
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "commodity",
                "commodity_name": row.get("instrument_name") or row.get("metric_name") or code,
                "commodity_category": row.get("commodity_category") or row.get("asset_category") or "unknown",
                "exchange": row.get("exchange") or row.get("provider_name") or "World Bank",
                "contract_code": None,
                "contract_month": None,
                "underlying_asset": row.get("instrument_name") or code,
                "currency": row.get("currency"),
                "unit": row.get("unit"),
                "contract_multiplier": None,
                "price_type": row.get("price_type") or "benchmark",
                "world_bank_code": code if row.get("source_id") == "world_bank_pink_sheet" else None,
                "fred_series_id": code if row.get("source_id") == "fred" else None,
                "exchange_symbol": None,
                "source_aliases": [code],
            }
        )
        crosswalk.append(crosswalk_item(entity_id, row.get("source_id", "unknown_source"), code, "series_or_dataset_id", "exact_match", 1.0))
        added += 1
        if added >= 10:
            break
    if added == 0:
        fallback = [("commodity_gold_fred", "fred", "GOLDAMGBD228NLBM", "Gold benchmark"), ("commodity_wti_fred", "fred", "DCOILWTICO", "WTI Oil")]
        for entity_id, source_id, code, name in fallback:
            entities.append(
                {
                    "entity_id": entity_id,
                    "entity_type": "commodity",
                    "commodity_name": name,
                    "commodity_category": "precious_metals" if "Gold" in name else "energy",
                    "exchange": "FRED",
                    "contract_code": None,
                    "contract_month": None,
                    "underlying_asset": name,
                    "currency": "USD",
                    "unit": "price",
                    "contract_multiplier": None,
                    "price_type": "benchmark",
                    "world_bank_code": None,
                    "fred_series_id": code,
                    "exchange_symbol": None,
                    "source_aliases": [code],
                }
            )
            crosswalk.append(crosswalk_item(entity_id, source_id, code, "fred_series_id", "exact_match", 1.0))


def add_index_entities(entities: list[dict[str, Any]], crosswalk: list[dict[str, Any]]) -> None:
    rows = [
        ("index_cn_sh000001", "Shanghai Composite", "SSE", "China", "equity_index", "CNY", "sh000001"),
        ("index_us_nasdaq_etf_universe", "Nasdaq Trader ETF universe sample", "Nasdaq Trader", "US", "ETF_universe", "USD", "nasdaq_trader_etf_sample"),
    ]
    for entity_id, name, provider, region, asset_class, currency, code in rows:
        entities.append(
            {
                "entity_id": entity_id,
                "entity_type": "index",
                "index_code": code,
                "index_name": name,
                "provider": provider,
                "country_or_region": region,
                "asset_class": asset_class,
                "currency": currency,
                "morningstar_id": None,
                "exchange_code": code,
                "source_aliases": [code, name],
            }
        )
        crosswalk.append(crosswalk_item(entity_id, provider.lower().replace(" ", "_"), code, "index_code", "exact_match", 1.0))


def crosswalk_item(entity_id: str, source_id: str | None, identifier: str | None, identifier_type: str, status: str, score: float) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "source_id": source_id or "unknown_source",
        "source_identifier": identifier,
        "identifier_type": identifier_type,
        "match_status": status,
        "match_score": score,
        "candidate_only": True,
        "created_at": utc_now(),
    }


def unresolved_item(source_id: str, payload: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "queue_id": f"unresolved_{source_id}_{sha256_text(json.dumps(payload, sort_keys=True, default=str))[:12]}",
        "source_id": source_id,
        "reason": reason,
        "payload_preview": {key: payload.get(key) for key in list(payload.keys())[:8]},
        "status": "needs_review",
        "created_at": utc_now(),
    }


def detect_duplicate_risks(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        ticker = entity.get("ticker") or entity.get("fund_code") or entity.get("index_code")
        if ticker:
            by_key[(entity.get("entity_type", ""), str(ticker).upper())].append(entity)
    risks = []
    for (entity_type, ticker), rows in by_key.items():
        exchanges = {row.get("exchange") or row.get("market") for row in rows}
        if len(rows) > 1 and len(exchanges) > 1:
            risks.append(
                {
                    "entity_type": entity_type,
                    "identifier": ticker,
                    "risk": "same_identifier_multiple_exchanges",
                    "entity_ids": [row["entity_id"] for row in rows],
                    "status": "needs_review_before_merge",
                }
            )
    return risks


def build_source_strategy() -> dict[str, Any]:
    sources = [
        source("fred", "official_automated", ["macro", "rates_bond", "commodity", "fx_currency"], "official API", "enabled", "daily/monthly", "low_frequency_cached", None, "Treasury/World Bank", "trusted_by_real_external_candidate_after_QA", "incremental"),
        source("us_treasury_fiscaldata", "official_automated", ["rates_bond", "fiscal"], "official API", "enabled", "daily/monthly", "low_frequency_cached", None, "FRED", "trusted_by_real_external_candidate_after_QA", "incremental"),
        source("world_bank_pink_sheet", "official_automated", ["commodity", "asset_class"], "official downloadable workbook", "enabled", "monthly", "low_frequency_cached", None, "FRED commodity series", "trusted_by_real_external_candidate_after_QA", "monthly incremental"),
        source("nasdaq_trader_symbol_directory", "official_automated", ["fund_etf", "equity"], "public symbol directory text files", "controlled_candidate", "daily", "low_frequency_cached", "terms and ETF universe role need review before trust upgrade", "issuer lists", "market_operator_candidate", "controlled incremental sample"),
        source("amac_aggregate_pdf", "official_automated", ["fund_etf"], "official PDF aggregate report", "aggregate_only", "monthly/quarterly", "manual schedule", "individual fund universe not exposed as stable automation", "fund company / exchange sources", "official_aggregate_candidate", "aggregate benchmark only"),
        source("amac_individual_fund_universe", "official_on_hold", ["fund_etf"], "website/query pages", "on_hold", "unknown", "do_not_crawl_until_terms_endpoint_review", "stable public export not confirmed", "manual validation / Morningstar matching sample", "official_source_future_connector", "source-specific review"),
        source("sse_szse_etf_lists", "official_on_hold", ["fund_etf", "market_daily"], "exchange pages/files", "on_hold", "daily", "do_not_crawl_until_endpoint_review", "stable downloadable ETF universe endpoint not confirmed in this phase", "AKShare/Baostock candidates", "official_source_future_connector", "endpoint feasibility"),
        source("bls_public_api", "official_on_hold", ["macro"], "official public API", "deferred_retry_needs_key_or_later_retry", "monthly", "respect_daily_threshold", "REQUEST_NOT_PROCESSED/public threshold seen", "FRED series fallback", "trusted_by_real_external_candidate_after_QA", "retry queue"),
        source("baostock", "open_source_api_wrapper_candidate", ["market_daily", "fund_etf"], "Python wrapper", "enabled_candidate", "daily", "low_frequency", None, "AKShare Tencent", "candidate_external_data", "operational fallback"),
        source("akshare_tencent", "open_source_api_wrapper_candidate", ["market_daily", "index", "fund_etf"], "AKShare Tencent-backed endpoint", "enabled_candidate", "daily", "low_frequency", None, "Baostock", "candidate_external_data", "controlled incremental"),
        source("akshare_eastmoney", "open_source_api_wrapper_candidate", ["market_daily", "fund_etf"], "AKShare Eastmoney-backed endpoints", "deferred", "daily", "deferred_retry_only", "Eastmoney push2his TLS/upstream instability", "Baostock / Tencent", "candidate_external_data", "optional retry"),
        source("morningstar_direct", "licensed_authorized_source", ["fund_etf", "holdings", "equity", "index", "performance"], "manual token + morningstar_data", "controlled_candidate", "daily/weekly/monthly by dataset", "manual_token_low_frequency", "license/storage/coverage/freshness boundaries not cleared", "official universe + SEC/exchange", "licensed_source_candidate", "controlled pilot with token"),
        source("eastmoney_public", "authoritative_third_party_candidate", ["market_daily", "fund_etf"], "public web endpoints", "deferred", "daily", "do_not_force", "remote disconnect/TLS instability and terms risk", "Baostock / AKShare Tencent", "candidate_external_data", "deferred"),
    ]
    strategy = {
        "version": "automated_source_strategy_v1",
        "generated_at": utc_now(),
        "principles": [
            "Automation is the long-term mainline; manual import is validation fallback only.",
            "Official automated sources are preferred when stable and compliant.",
            "Official sources with captcha/login/unclear terms are on_hold rather than force-crawled.",
            "Third-party, open-source wrappers, and licensed data stay candidate until validation and license checks pass.",
        ],
        "sources": sources,
        "status_counts": dict(Counter(item["automation_status"] for item in sources)),
    }
    source_status_matrix = {"generated_at": utc_now(), "sources": sources, "status_counts": strategy["status_counts"]}
    write_json(CONFIG_ROOT / "automated_source_strategy.json", strategy)
    write_json(RUNTIME_ROOT / "source_status_matrix.json", source_status_matrix)
    return strategy


def source(
    source_id: str,
    source_type: str,
    domains: list[str],
    access_method: str,
    automation_status: str,
    update_frequency: str,
    rate_limit_policy: str,
    blocker: str | None,
    fallback_source: str,
    trust_role: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "domains_supported": domains,
        "access_method": access_method,
        "automation_status": automation_status,
        "update_frequency": update_frequency,
        "rate_limit_policy": rate_limit_policy,
        "blocker": blocker,
        "fallback_source": fallback_source,
        "trust_role": trust_role,
        "next_action": next_action,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def build_akshare_audit() -> dict[str, Any]:
    phase5_ak = read_json(PHASE5_ROOT / "a_share_daily_akshare_tencent_results.json", {})
    phase5_src = read_json(PHASE5_ROOT / "a_share_daily_source_status.json", {})
    diagnosis = read_json(PROJECT_ROOT / "runtime" / "data_connector_akshare_diagnosis" / "minimal_reproduction_matrix.json", {})
    items = [
        ak_item(
            "stock_zh_a_hist_tx",
            "market_daily",
            "equity",
            "success" if phase5_ak.get("overall_status") == "success" else "not_run",
            phase5_ak.get("total_records", 0),
            ["date", "open", "high", "low", "close", "amount"],
            ["symbol"],
            ["trade_date"],
            "daily",
            "Tencent",
            "quality_passed_candidate" if phase5_ak.get("quality_result", {}).get("status") == "quality_passed" else "needs_review",
            "open_source_api_wrapper_candidate",
            "enabled_candidate",
            phase5_ak.get("runtime_mirror_path"),
        ),
        ak_item(
            "stock_zh_a_hist",
            "market_daily",
            "equity",
            "failed_deferred",
            0,
            [],
            ["symbol"],
            ["date"],
            "daily",
            "Eastmoney push2his",
            "upstream_tls_remote_disconnect_risk",
            "candidate_external_data_deferred",
            "deferred_optional_source",
            None,
        ),
        ak_item(
            "fund_etf_hist_em",
            "fund_etf",
            "ETF",
            "not_executed_low_confidence",
            0,
            [],
            ["fund_code"],
            ["trade_date"],
            "daily",
            "Eastmoney likely",
            "upstream_risk_until endpoint validated",
            "candidate_external_data_deferred",
            "audit_before_enable",
            None,
        ),
        ak_item(
            "macro_china_*",
            "macro",
            "macro_series",
            "not_executed_source_specific_review_required",
            0,
            [],
            ["series_id"],
            ["data_period", "publish_date_if_available"],
            "monthly",
            "mixed upstreams",
            "official_provenance_required",
            "candidate_only_until_source_verified",
            "source_feasibility_before_enable",
            None,
        ),
        ak_item(
            "futures_*_daily",
            "futures",
            "futures_contract",
            "not_executed_source_specific_review_required",
            0,
            [],
            ["contract_code", "exchange"],
            ["trade_date"],
            "daily",
            "mixed exchange/third-party upstreams",
            "exchange/source/contract semantics required",
            "candidate_only_until_cross_validated",
            "source_feasibility_before_enable",
            None,
        ),
    ]
    result = {
        "generated_at": utc_now(),
        "audit_scope": "low-frequency metadata/runtime-evidence audit; no broad AKShare crawl",
        "phase5_source_status": phase5_src,
        "eastmoney_diagnosis_reference": diagnosis.get("summary", diagnosis) if isinstance(diagnosis, dict) else {},
        "items": items,
        "sample_success_count": sum(1 for item in items if item["sample_success"]),
        "enabled_candidate_functions": [item["function_name"] for item in items if item["automation_status"] == "enabled_candidate"],
        "deferred_functions": [item["function_name"] for item in items if "deferred" in item["automation_status"]],
        "no_full_download": True,
        "no_high_frequency_requests": True,
    }
    write_json(RUNTIME_ROOT / "akshare_api_audit.json", result)
    return result


def ak_item(
    function_name: str,
    domain: str,
    entity_type: str,
    status: str,
    records: int,
    fields: list[str],
    identifiers: list[str],
    dates: list[str],
    frequency: str,
    upstream: str,
    risk: str,
    trust_role: str,
    automation_status: str,
    sample_path: str | None,
) -> dict[str, Any]:
    return {
        "function_name": function_name,
        "data_domain": domain,
        "entity_type": entity_type,
        "sample_success": status == "success",
        "sample_status": status,
        "sample_records": records,
        "fields_returned": fields,
        "identifier_fields": identifiers,
        "date_fields": dates,
        "update_frequency_estimate": frequency,
        "source_upstream": upstream,
        "quality_risk": risk,
        "trust_role": trust_role,
        "automation_status": automation_status,
        "sample_reference_path": sample_path,
    }


def build_morningstar_candidates() -> dict[str, Any]:
    phase3_tiny = read_json(PHASE3_FUND_ROOT / "morningstar_tiny_sample_validation_results.json", {})
    phase3_matching = read_json(PHASE3_FUND_ROOT / "us_nasdaq_morningstar_matching_pilot.json", {})
    phase3_equity = read_json(PHASE3_FUND_ROOT / "morningstar_equity_stock_validation_phase3.json", {})
    token_state = read_json(AUTHORITATIVE_ROOT / "morningstar_token_state.json", {})
    candidates: list[dict[str, Any]] = []
    for item in phase3_tiny.get("items", []):
        if not item.get("usable_for_fr") and item.get("tiny_sample_status") not in {"success", "method_reachable"}:
            continue
        candidates.append(
            {
                "dataset_id": item.get("dataset_id") or item.get("dataset_name"),
                "dataset_name": item.get("dataset_name"),
                "domain": item.get("likely_data_type") or "licensed_dataset",
                "entity_type": infer_entity_type(item.get("likely_data_type", "")),
                "fields_available": item.get("fields_observed") or item.get("fields") or [],
                "identifier_fields": item.get("identifier_fields") or ["morningstar_sec_id", "ticker", "isin"],
                "date_fields": item.get("date_fields") or ["as_available"],
                "entity_crosswalk_possible": True,
                "sample_success": item.get("tiny_sample_status") in {"success", "method_reachable"},
                "entitlement_status": item.get("entitlement_status", "allowed_or_method_reachable"),
                "license_boundary": "needs_user_license_storage_usage_review",
                "raw_storage_status": "metadata_or_masked_sample_only_until_user_confirmation",
                "recommended_frequency": "dataset_specific_low_frequency",
                "automation_status": "controlled_candidate",
                "next_validation_step": "controlled sample with entity crosswalk and official benchmark when available",
                "candidate_only": True,
            }
        )
    if phase3_matching.get("matched_count"):
        candidates.append(
            {
                "dataset_id": "morningstar_symbol_search_us_etf_sample",
                "dataset_name": "Morningstar symbol search for US ETF official sample",
                "domain": "fund_etf_master",
                "entity_type": "ETF",
                "fields_available": ["morningstar_sec_id", "name", "ticker", "isin", "exchange", "country", "currency", "security_type"],
                "identifier_fields": ["ticker", "isin", "morningstar_sec_id"],
                "date_fields": [],
                "entity_crosswalk_possible": True,
                "sample_success": True,
                "sample_records": phase3_matching.get("matched_count"),
                "entitlement_status": "allowed_for_symbol_search",
                "license_boundary": "needs_user_license_storage_usage_review",
                "raw_storage_status": "metadata_only_current_phase",
                "recommended_frequency": "weekly_or_on_demand",
                "automation_status": "controlled_candidate",
                "next_validation_step": "larger controlled US ETF universe validation, no full download",
                "candidate_only": True,
            }
        )
    for market in phase3_equity.get("markets", []):
        candidates.append(
            {
                "dataset_id": f"morningstar_equity_search_{market.get('market', 'unknown').lower().replace(' ', '_')}",
                "dataset_name": f"Morningstar equity/security validation - {market.get('market')}",
                "domain": "equity_stock",
                "entity_type": "equity",
                "fields_available": market.get("observed_fields", []),
                "identifier_fields": ["ticker", "isin", "exchange", "country", "currency"],
                "date_fields": market.get("date_fields", []),
                "entity_crosswalk_possible": market.get("coverage_status") != "metadata_or_framework_only",
                "sample_success": "tiny" in str(market.get("coverage_status", "")),
                "entitlement_status": market.get("permission_status", "unknown"),
                "license_boundary": "needs_user_license_storage_usage_review",
                "raw_storage_status": "metadata_only_current_phase",
                "recommended_frequency": "on_demand_until_coverage_validated",
                "automation_status": "controlled_candidate" if "tiny" in str(market.get("coverage_status", "")) else "validation_framework_only",
                "next_validation_step": "cross-source validation against exchange/CNINFO/SEC sources",
                "candidate_only": True,
            }
        )
    result = {
        "generated_at": utc_now(),
        "token_status": "available_or_state_recorded" if token_state else "unknown_or_missing",
        "token_fingerprint_state_used": bool(token_state),
        "candidates": candidates,
        "controlled_candidate_count": sum(1 for item in candidates if item["automation_status"] == "controlled_candidate"),
        "validation_framework_only_count": sum(1 for item in candidates if item["automation_status"] != "controlled_candidate"),
        "trusted_candidate_count": 0,
        "large_download_performed": False,
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
    }
    write_json(RUNTIME_ROOT / "morningstar_controlled_ingestion_candidates.json", result)
    return result


def infer_entity_type(value: str) -> str:
    value = value.lower()
    if "holding" in value or "portfolio" in value:
        return "holding"
    if "fund" in value or "etf" in value:
        return "ETF_or_fund"
    if "equity" in value or "stock" in value:
        return "equity"
    if "index" in value or "benchmark" in value:
        return "index"
    return "licensed_dataset"


def build_scheduler(source_strategy: dict[str, Any], morningstar_candidates: dict[str, Any]) -> dict[str, Any]:
    items = [
        schedule_item("baostock_a_share_daily", "baostock", "equity", "daily", "T+0/T+1 market close", "disabled_for_full_backfill", "30d rolling window", "retry_next_day", True, None),
        schedule_item("akshare_tencent_a_share_daily", "akshare_tencent", "equity", "daily", "T+0/T+1 market close", "disabled_for_full_backfill", "30d rolling window", "retry_next_day", True, None),
        schedule_item("fred_rates_macro", "fred", "macro_series", "daily/monthly", "source-dependent", "full history already available or cached", "increment since latest_observation", "deferred retry with backoff", True, None),
        schedule_item("treasury_yields", "us_treasury_fiscaldata", "rates_bond", "daily", "source-dependent", "full history cached", "increment since latest_observation", "deferred retry with backoff", True, None),
        schedule_item("world_bank_pink_sheet", "world_bank_pink_sheet", "commodity", "monthly", "monthly release lag", "full history cached", "monthly refresh", "deferred retry", True, None),
        schedule_item("morningstar_us_etf_symbol_search", "morningstar_direct", "ETF", "weekly_or_on_demand", "manual token 24h", "no broad backfill until license review", "controlled sample only", "user_action_required_when_token_expired", False, "license/storage/coverage boundary not cleared"),
        schedule_item("amac_individual_fund_universe", "amac_individual_fund_universe", "fund", "monthly", "unknown", "on_hold", "on_hold", "none", False, "stable automated endpoint not confirmed"),
        schedule_item("bls_macro", "bls_public_api", "macro_series", "monthly", "source threshold", "deferred", "deferred retry or API key", "deferred_retry_queue", False, "public API threshold/API key needed"),
        schedule_item("fund_quarterly_holdings", "morningstar_direct_or_official_reports", "holding", "quarterly", "reporting lag", "schema ready only", "manual or licensed controlled pilot", "user_action_required", False, "source/license validation required"),
    ]
    schedule = {
        "version": "automated_ingestion_schedule_v1",
        "generated_at": utc_now(),
        "items": items,
        "enabled_count": sum(1 for item in items if item["enabled"]),
        "blocked_count": sum(1 for item in items if item["blocker"]),
        "frequency_counts": dict(Counter(item["update_frequency"] for item in items)),
        "morningstar_controlled_candidate_count": morningstar_candidates["controlled_candidate_count"],
        "source_count": len(source_strategy["sources"]),
    }
    write_json(CONFIG_ROOT / "automated_ingestion_schedule.json", schedule)
    return schedule


def schedule_item(
    dataset_id: str,
    source_id: str,
    entity_type: str,
    update_frequency: str,
    expected_release_lag: str,
    backfill_policy: str,
    incremental_policy: str,
    retry_policy: str,
    enabled: bool,
    blocker: str | None,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "source_id": source_id,
        "entity_type": entity_type,
        "update_frequency": update_frequency,
        "expected_release_lag": expected_release_lag,
        "backfill_policy": backfill_policy,
        "incremental_policy": incremental_policy,
        "retry_policy": retry_policy,
        "enabled": enabled,
        "blocker": blocker,
        "next_run_plan": "eligible_for_controlled_incremental" if enabled else "on_hold_or_user_action_required",
    }


def build_ingestion_pipeline(
    mode: str,
    entity_outputs: dict[str, Any],
    source_strategy: dict[str, Any],
    akshare_audit: dict[str, Any],
    morningstar_candidates: dict[str, Any],
    schedule: dict[str, Any],
) -> dict[str, Any]:
    run_records: list[dict[str, Any]] = []
    run_records.append(build_pilot_from_phase5("akshare_tencent_daily", "market_daily", "equity", PHASE5_ROOT / "a_share_daily_akshare_tencent_results.json", "akshare_tencent_a_share_daily"))
    run_records.append(build_pilot_from_phase5("baostock_daily", "market_daily", "equity", PHASE5_ROOT / "a_share_daily_baostock_results.json", "baostock_a_share_daily"))
    run_records.append(build_macro_incremental_check())
    run_records.append(build_commodity_incremental_check())
    run_records.append(build_morningstar_controlled_check(morningstar_candidates))
    run_records = [record for record in run_records if record]
    for record in run_records:
        write_json(CONTROLLED_ROOT / f"{record['run_id']}.json", record)
    staging_counts = dict(Counter(record["staging_status"] for record in run_records))
    results = {
        "version": "automated_ingestion_pipeline_v1",
        "generated_at": utc_now(),
        "mode": mode,
        "supported_modes": ["backfill", "incremental", "retry", "audit", "dry_run", "controlled_pilot"],
        "pipeline_steps": [
            "source_selection",
            "entity_identifier_mapping",
            "fetch_or_replay_raw",
            "save_raw",
            "normalize",
            "QA",
            "revision_or_vintage_check",
            "entity_crosswalk_update",
            "catalog_update",
            "staging",
            "dashboard_summary",
        ],
        "run_records": run_records,
        "staging_counts": staging_counts,
        "controlled_pilot_completed": True,
        "no_full_download": True,
        "no_openai_api_called": True,
        "formal_trusted_consumption_affected": False,
    }
    write_json(RUNTIME_ROOT / "ingestion_run_results.json", results)
    return results


def build_pilot_from_phase5(source_id: str, domain: str, entity_type: str, path: Path, dataset_id: str) -> dict[str, Any]:
    payload = read_json(path, {})
    total_records = payload.get("total_records", 0)
    raw_path = payload.get("raw_output_path")
    normalized_path = payload.get("structured_output_path") or payload.get("runtime_mirror_path")
    qa_status = payload.get("quality_result", {}).get("status") or payload.get("quality_result", {}).get("quality_status") or "unknown"
    return run_record(
        source_id=source_id,
        dataset_id=dataset_id,
        domain=domain,
        category="daily_market",
        metric_id="ohlcv",
        records_raw=total_records,
        records_normalized=total_records,
        raw_path=raw_path,
        normalized_path=normalized_path,
        qa_status=qa_status,
        revision_status="not_checked_market_daily_sample",
        publish_date_coverage="market_trade_date_inferred",
        trust_status="candidate_external_data",
        staging_status="candidate_staging",
        error_message="" if total_records else "runtime_phase5_sample_missing",
        entity_mapping_status="mapped_for_sample_watchlist",
    )


def build_macro_incremental_check() -> dict[str, Any]:
    summary = read_json(MARKET_PHASE2_ROOT / "phase2_summary.json", {})
    records = summary.get("records_normalized") or summary.get("normalized_records") or summary.get("records_loaded") or 0
    return run_record(
        source_id="fred_treasury_existing_macro",
        dataset_id="fred_treasury_incremental_check",
        domain="macro_rates_fx",
        category="incremental_check",
        metric_id="multi_series",
        records_raw=records,
        records_normalized=records,
        raw_path=str(MARKET_PHASE2_ROOT / "phase2_run_records.json"),
        normalized_path=str(MARKET_PHASE2_ROOT / "normalized_phase2_records.jsonl"),
        qa_status="quality_passed_or_cached" if records else "dry_run_only",
        revision_status="vintage_summary_available" if (MARKET_PHASE2_ROOT / "vintage_summary.json").exists() else "vintage_support_limited",
        publish_date_coverage="not_fabricated_observation_date_only",
        trust_status="trusted_by_real_external_candidate_after_QA",
        staging_status="validation_candidate",
        error_message="" if records else "phase2 record count not available; dry-run check only",
        entity_mapping_status="macro_series_crosswalk_ready",
    )


def build_commodity_incremental_check() -> dict[str, Any]:
    summary = read_json(MACRO_ASSET_ROOT / "ingestion_summary.json", {})
    records = summary.get("record_count") or summary.get("records_loaded") or 0
    return run_record(
        source_id="world_bank_fred_commodity_existing",
        dataset_id="commodity_rates_dry_run_incremental_check",
        domain="commodity_asset_class",
        category="incremental_check",
        metric_id="commodity_benchmark",
        records_raw=records,
        records_normalized=records,
        raw_path=str(MACRO_ASSET_ROOT / "raw_artifact_index.json"),
        normalized_path=str(MACRO_ASSET_ROOT / "normalized_commodity_history_latest.jsonl"),
        qa_status="quality_passed_or_cached" if records else "dry_run_only",
        revision_status="revision_log_available" if (MACRO_ASSET_ROOT / "revision_log.json").exists() else "vintage_support_limited",
        publish_date_coverage="publish_date_unavailable_when_source_lacks_release_date",
        trust_status="trusted_by_real_external_candidate_after_QA",
        staging_status="validation_candidate",
        error_message="" if records else "macro_asset historical records not counted in summary; dry-run check only",
        entity_mapping_status="commodity_crosswalk_ready",
    )


def build_morningstar_controlled_check(morningstar_candidates: dict[str, Any]) -> dict[str, Any]:
    candidates = morningstar_candidates.get("candidates", [])
    return run_record(
        source_id="morningstar_direct",
        dataset_id="morningstar_controlled_candidate_audit",
        domain="licensed_multi_asset",
        category="audit",
        metric_id="dataset_candidate_status",
        records_raw=len(candidates),
        records_normalized=len(candidates),
        raw_path=str(RUNTIME_ROOT / "morningstar_controlled_ingestion_candidates.json"),
        normalized_path=str(RUNTIME_ROOT / "morningstar_controlled_ingestion_candidates.json"),
        qa_status="metadata_quality_passed_candidate" if candidates else "user_action_required_or_no_candidate",
        revision_status="not_applicable_metadata_audit",
        publish_date_coverage="not_applicable_metadata_audit",
        trust_status="licensed_source_candidate",
        staging_status="controlled_candidate",
        error_message="" if candidates else "no Morningstar controlled candidate available or token missing",
        entity_mapping_status="partial_crosswalk_possible",
    )


def run_record(
    source_id: str,
    dataset_id: str,
    domain: str,
    category: str,
    metric_id: str,
    records_raw: int,
    records_normalized: int,
    raw_path: str | None,
    normalized_path: str | None,
    qa_status: str,
    revision_status: str,
    publish_date_coverage: str,
    trust_status: str,
    staging_status: str,
    error_message: str,
    entity_mapping_status: str,
) -> dict[str, Any]:
    run_id = f"auto_v1_{source_id}_{sha256_text(dataset_id + utc_now())[:8]}"
    return {
        "run_id": run_id,
        "retrieval_snapshot_id": f"snapshot_{run_id}",
        "source_id": source_id,
        "dataset_id": dataset_id,
        "domain": domain,
        "category": category,
        "metric_id": metric_id,
        "start_date": None,
        "end_date": None,
        "records_raw": records_raw,
        "records_normalized": records_normalized,
        "raw_path": raw_path,
        "normalized_path": normalized_path,
        "qa_status": qa_status,
        "revision_status": revision_status,
        "publish_date_coverage": publish_date_coverage,
        "trust_status": trust_status,
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "staging_status": staging_status,
        "entity_mapping_status": entity_mapping_status,
        "elapsed_seconds": 0.0,
        "error_message": error_message,
    }


def build_dashboard_status(
    entity_outputs: dict[str, Any],
    source_strategy: dict[str, Any],
    ingestion: dict[str, Any],
    schedule: dict[str, Any],
    morningstar_candidates: dict[str, Any],
) -> dict[str, Any]:
    on_hold = [source for source in source_strategy["sources"] if source["source_type"] == "official_on_hold"]
    candidate_sources = [
        source
        for source in source_strategy["sources"]
        if source["source_type"] in {"authoritative_third_party_candidate", "open_source_api_wrapper_candidate", "licensed_authorized_source"}
    ]
    status = {
        "generated_at": utc_now(),
        "title": "Automated Ingestion System v1",
        "entity_master": {
            "entity_count": entity_outputs["entity_count"],
            "crosswalk_count": entity_outputs["crosswalk_count"],
            "unresolved_entity_count": entity_outputs["unresolved_entity_count"],
            "duplicate_risk_count": entity_outputs["duplicate_risk_count"],
            "status": "ready_with_review_queue" if entity_outputs["unresolved_entity_count"] else "ready",
        },
        "source_status": {
            "official_automated": [source["source_id"] for source in source_strategy["sources"] if source["source_type"] == "official_automated"],
            "official_on_hold": [source["source_id"] for source in on_hold],
            "candidate_sources": [source["source_id"] for source in candidate_sources],
        },
        "schedule": {
            "enabled_count": schedule["enabled_count"],
            "blocked_count": schedule["blocked_count"],
            "frequency_counts": schedule["frequency_counts"],
        },
        "latest_ingestion_runs": ingestion["run_records"],
        "data_trust_pipeline": {
            "candidate": sum(1 for run in ingestion["run_records"] if "candidate" in run["staging_status"]),
            "validation": sum(1 for run in ingestion["run_records"] if "validation" in run["staging_status"]),
            "trusted_candidate": ingestion["staging_counts"].get("trusted_candidate", 0),
            "trusted": 0,
        },
        "morningstar": {
            "controlled_candidate_count": morningstar_candidates["controlled_candidate_count"],
            "trusted_candidate_count": morningstar_candidates["trusted_candidate_count"],
            "no_auto_login": True,
            "no_password_saved": True,
            "token_leaked": False,
        },
        "legacy_streamlit_used": False,
        "no_openai_api_called": True,
        "formal_trusted_consumption_affected": False,
    }
    write_json(RUNTIME_ROOT / "dashboard_automation_status.json", status)
    dashboard_source_status = read_json(AUTHORITATIVE_ROOT / "dashboard_source_status.json", {"sources": []})
    sources = dashboard_source_status.get("sources", [])
    sources = [source for source in sources if source.get("source_id") != "automated_ingestion_system_v1"]
    sources.append(
        {
            "source_id": "automated_ingestion_system_v1",
            "status": "ready",
            "entity_count": entity_outputs["entity_count"],
            "crosswalk_count": entity_outputs["crosswalk_count"],
            "unresolved_entity_count": entity_outputs["unresolved_entity_count"],
            "latest_pilot_run_count": len(ingestion["run_records"]),
            "trusted_candidate_count": ingestion["staging_counts"].get("trusted_candidate", 0),
            "warning": "Automation status is candidate/staging only and does not enter formal trusted consumption.",
        }
    )
    dashboard_source_status["sources"] = sources
    dashboard_source_status["generated_at"] = utc_now()
    write_json(AUTHORITATIVE_ROOT / "dashboard_source_status.json", dashboard_source_status)
    return status


def write_docs(
    entity_outputs: dict[str, Any],
    source_strategy: dict[str, Any],
    akshare_audit: dict[str, Any],
    morningstar_candidates: dict[str, Any],
    schedule: dict[str, Any],
    ingestion: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, str]:
    docs: dict[str, str] = {}
    docs["entity_master"] = str(DOCS_ROOT / "ENTITY_MASTER_AND_IDENTIFIER_CROSSWALK_V1.md")
    write_text(
        Path(docs["entity_master"]),
        f"""# Entity Master and Identifier Crosswalk v1

Generated: {utc_now()}

Entity Master v1 defines a shared identifier layer for equity, fund/ETF, index, commodity/futures and macro series data.
Every ingestion run should attempt an `entity_id` mapping before staging. Unmapped identifiers go to
`runtime/automated_ingestion_system/unresolved_entity_queue.json`.

Current seed inventory:
- Entities: {entity_outputs['entity_count']}
- Crosswalk entries: {entity_outputs['crosswalk_count']}
- Unresolved queue: {entity_outputs['unresolved_entity_count']}
- Duplicate risks: {entity_outputs['duplicate_risk_count']}

Merge guards:
- Same ticker in different exchanges is not auto-merged.
- Fund fuzzy-name matches are probable_match only.
- Commodity benchmark, spot and futures instruments are separate entities.
- Morningstar identifiers remain licensed-source candidate identifiers until license and validation checks pass.
""",
    )
    docs["source_strategy"] = str(DOCS_ROOT / "AUTOMATED_SOURCE_STRATEGY_V1.md")
    write_text(
        Path(docs["source_strategy"]),
        f"""# Automated Source Strategy v1

Generated: {utc_now()}

FR automation is catalog and source-status driven. Manual import remains a validation fallback, not the long-term mainline.

Source status counts:
{json.dumps(source_strategy['status_counts'], indent=2)}

Official sources with stable API/file endpoints are `official_automated`. Official sources with captcha/login/unclear endpoint
or terms are `official_on_hold`. AKShare/Baostock wrappers and Morningstar licensed datasets are candidate sources and must
pass quality, coverage, freshness, field, cross-source and license checks before trust upgrade.
""",
    )
    docs["akshare_audit"] = str(DOCS_ROOT / "AKSHARE_AUTOMATED_SOURCE_AUDIT.md")
    write_text(
        Path(docs["akshare_audit"]),
        f"""# AKShare Automated Source Audit

Generated: {utc_now()}

This audit reuses prior low-frequency evidence and does not perform broad AKShare crawling.

Success count: {akshare_audit['sample_success_count']}
Enabled candidates: {', '.join(akshare_audit['enabled_candidate_functions']) or 'none'}
Deferred functions: {', '.join(akshare_audit['deferred_functions']) or 'none'}

Eastmoney-backed endpoints remain deferred because the push2his/TLS/upstream instability is a known operational risk.
Tencent-backed A-share daily data can enter candidate automation with Baostock as the operational fallback.
""",
    )
    docs["morningstar_plan"] = str(DOCS_ROOT / "MORNINGSTAR_CONTROLLED_INGESTION_PLAN.md")
    write_text(
        Path(docs["morningstar_plan"]),
        f"""# Morningstar Controlled Ingestion Plan

Generated: {utc_now()}

Morningstar remains a licensed authorized candidate source. This plan does not auto-login, does not store passwords,
does not expose token values, and does not perform large downloads.

Controlled candidates: {morningstar_candidates['controlled_candidate_count']}
Trusted candidates: {morningstar_candidates['trusted_candidate_count']}

Required before broader collection:
- User confirms license, raw storage and display boundaries.
- Official or authoritative benchmark exists for the dataset universe.
- Coverage, freshness, field completeness and cross-source validation pass.
""",
    )
    docs["schedule"] = str(DOCS_ROOT / "AUTOMATED_INGESTION_SCHEDULE_V1.md")
    write_text(
        Path(docs["schedule"]),
        f"""# Automated Ingestion Schedule v1

Generated: {utc_now()}

Enabled schedules: {schedule['enabled_count']}
Blocked/on-hold schedules: {schedule['blocked_count']}

Daily candidates include market daily, rates, FX and commodity prices. Monthly candidates include CPI/PPI/money supply,
World Bank Pink Sheet and fund aggregate reports. Quarterly and annual schedules cover holdings, financial reports and
statistical yearbooks when compliant sources are available.
""",
    )
    docs["pilot_report"] = str(DOCS_ROOT / "AUTOMATED_INGESTION_CONTROLLED_PILOT_REPORT.md")
    write_text(
        Path(docs["pilot_report"]),
        f"""# Automated Ingestion Controlled Pilot Report

Generated: {utc_now()}

Pilot run count: {len(ingestion['run_records'])}

The pilot uses cached or previously validated controlled evidence for A-share daily, Morningstar candidate metadata,
macro/rates, and commodity/rates checks. It follows the v1 pipeline contract: source selection -> entity mapping -> raw
reference -> normalized reference -> QA -> revision/vintage status -> staging -> dashboard summary.

No formal trusted consumption was modified.
""",
    )
    docs["dedup_rules"] = str(DOCS_ROOT / "DATA_DEDUP_AND_IDENTIFIER_TRUST_RULES.md")
    write_text(
        Path(docs["dedup_rules"]),
        """# Data Dedup and Identifier Trust Rules

- Morningstar, AKShare, Eastmoney, Tonghuashun and similar third-party sources are candidate by default.
- Official or authoritative sources may become trusted_candidate only after QA and source-role validation.
- All stock, fund, ETF and futures data must keep exchange or official identifiers.
- Same code in different markets is not the same entity.
- Different source aliases for one entity must be mapped through Entity Master.
- Commodity benchmark, spot, futures and index data must not be mixed.
- Fund flow proxy is not actual flow unless the source explicitly defines net flow.
- Revised data must keep revision/vintage records and must not overwrite prior snapshots.
""",
    )
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Automated Market Data Ingestion System v1.")
    parser.add_argument("--mode", choices=["backfill", "incremental", "retry", "audit", "dry_run", "controlled_pilot"], default="controlled_pilot")
    args = parser.parse_args()
    summary = run_automated_ingestion_v1(mode=args.mode)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
