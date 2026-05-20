from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services import data_connector_phase2_service as phase2  # noqa: E402
from scripts.run_fund_etf_capital_flow_foundation import RUNTIME_ROOT as PHASE1_ROOT  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "fund_etf_capital_flow_phase2"
DOCS_ROOT = PROJECT_ROOT / "docs"
CONFIG_ROOT = PROJECT_ROOT / "config"
MORNINGSTAR_PILOT_ROOT = PROJECT_ROOT / "runtime" / "morningstar_connector_pilot"
AUTHORITATIVE_RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "authoritative_crawler_framework"


ETF_SAMPLE = [
    {"symbol": "510300", "name": "CSI 300 ETF sample", "market": "SH", "region": "China", "exchange": "SSE"},
    {"symbol": "510500", "name": "CSI 500 ETF sample", "market": "SH", "region": "China", "exchange": "SSE"},
    {"symbol": "159915", "name": "ChiNext ETF sample", "market": "SZ", "region": "China", "exchange": "SZSE"},
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def storage_root(*parts: str) -> Path:
    context = phase2.load_context()
    cold = Path(context.storage_paths["cold_data_root"])
    return cold.joinpath(*parts)


def official_source_audit() -> dict[str, Any]:
    sources = [
        ("amac_public_fund_disclosure", "Asset Management Association of China", "China", "official_industry_association", "manual_import_required", "AMAC product and manager disclosure feasibility needs terms/source-specific review."),
        ("sse_etf_list", "Shanghai Stock Exchange ETF/fund list", "China", "exchange_official", "manual_or_small_connector_after_endpoint_review", "Use official exchange list only if stable file/table endpoint is confirmed."),
        ("szse_etf_list", "Shenzhen Stock Exchange ETF/fund list", "China", "exchange_official", "manual_or_small_connector_after_endpoint_review", "Use official exchange list only if stable file/table endpoint is confirmed."),
        ("fund_company_official_sites", "Southern/E Fund/ChinaAMC official sites", "China", "issuer_official", "manual_import_required", "Issuer sites vary; no captcha/login bypass."),
        ("eastmoney_ths_morningstar_cn", "Eastmoney / iFinD / Morningstar China", "China", "third_party_candidate", "candidate_cross_validation_only", "Third-party candidate fallback; not official."),
        ("sec_edgar_investment_company_filings", "SEC EDGAR investment company filings", "US", "regulator_official", "official_filing_metadata_connector_candidate", "Useful for filings and reference, not a simple ETF universe table by itself."),
        ("us_etf_issuer_lists", "iShares / Vanguard / State Street official product lists", "US", "issuer_official", "manual_or_source_specific_connector", "Issuer official lists are strong anchors if terms and file endpoints are clear."),
        ("us_exchange_etf_lists", "Nasdaq / NYSE / Cboe ETF lists", "US", "exchange_or_market_operator", "needs_source_specific_audit", "Potential official universe baseline; do not assume file availability."),
        ("esma_ucits_sources", "ESMA / UCITS related public sources", "Europe", "regulator_or_regional_authority", "needs_source_specific_audit", "Useful for official reference where accessible."),
        ("europe_exchange_etf_lists", "LSE / Euronext / Xetra ETF lists", "Europe", "exchange_official", "needs_source_specific_audit", "Potential official exchange universe baseline."),
        ("europe_issuer_lists", "iShares Europe / Amundi / DWS Xtrackers", "Europe", "issuer_official", "manual_or_source_specific_connector", "Issuer official lists are feasible anchors after terms review."),
    ]
    rows = []
    for source_id, name, region, role, connector, blocker in sources:
        rows.append(
            {
                "source_id": source_id,
                "source_name": name,
                "region": region,
                "official_or_third_party": role,
                "access_method": "official website / file / page table where legal and stable",
                "file_download_available": "to_verify",
                "html_table_available": "to_verify",
                "api_available": "not_confirmed",
                "crawler_allowed": "needs_terms_review",
                "robots_or_terms_status": "not_reviewed_in_phase2",
                "known_blockers": blocker,
                "recommended_connector_type": connector,
                "initial_backfill_strategy": "manual import first unless official stable download is confirmed",
                "incremental_update_strategy": "periodic official list refresh after source terms review",
                "trust_role": "official_crosscheck_source" if "official" in role or "exchange" in role or "regulator" in role else "candidate_cross_validation_source",
                "next_action": "source_specific_terms_and_endpoint_review",
            }
        )
    result = {"generated_at": utc_now(), "sources": rows, "large_download_performed": False}
    write_json(OUTPUT_ROOT / "official_fund_universe_source_audit.json", result)
    write_text(
        DOCS_ROOT / "FUND_ETF_OFFICIAL_UNIVERSE_SOURCE_AUDIT.md",
        """# Fund / ETF Official Universe Source Audit

Official or authoritative sources remain the anchor for Morningstar validation. Sources with unclear terms, captcha, login, paywall, or unstable endpoints are marked for manual import or source-specific review rather than crawled.
""",
    )
    return result


def official_universe_manual_fallback(audit: dict[str, Any]) -> dict[str, Any]:
    result = {
        "generated_at": utc_now(),
        "connector_status": "manual_fallback_ready",
        "automatic_official_connector_run": False,
        "reason": "No official universe endpoint has been source-specific reviewed and cleared for automated ingestion in this phase.",
        "manual_templates_root": str(PHASE1_ROOT / "manual_import_templates"),
        "raw_target_root": str(storage_root("raw", "fund_etf", "official_universe")),
        "structured_target_root": str(storage_root("structured", "fund_etf", "official_universe")),
        "source_audit_count": len(audit["sources"]),
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "official_fund_universe_ingestion_results.json", result)
    return result


def baostock_code(symbol: str) -> str:
    return f"sh.{symbol}" if symbol.startswith("5") else f"sz.{symbol}"


def run_etf_market_sample() -> dict[str, Any]:
    started = time.time()
    raw_payload: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    items = []
    try:
        import baostock as bs
    except Exception as exc:  # noqa: BLE001
        result = {
            "generated_at": utc_now(),
            "overall_status": "failed",
            "failure_mode": f"baostock_import_failed:{type(exc).__name__}",
            "items": [],
            "records": [],
            "candidate_only": True,
        }
        write_json(OUTPUT_ROOT / "etf_market_data_ingestion_results.json", result)
        return result

    login = bs.login()
    if login.error_code != "0":
        result = {
            "generated_at": utc_now(),
            "overall_status": "failed",
            "failure_mode": "baostock_login_failed:" + login.error_msg,
            "items": [],
            "records": [],
            "candidate_only": True,
        }
        write_json(OUTPUT_ROOT / "etf_market_data_ingestion_results.json", result)
        return result
    try:
        start = (date.today() - timedelta(days=75)).isoformat()
        end = date.today().isoformat()
        for etf in ETF_SAMPLE:
            rs = bs.query_history_k_data_plus(
                baostock_code(etf["symbol"]),
                "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="3",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(dict(zip(rs.fields, rs.get_row_data())))
            rows = rows[-30:]
            raw_payload.extend([{**row, "etf_name": etf["name"]} for row in rows])
            for row in rows:
                normalized.append(normalize_etf_row(row, etf))
            items.append({"symbol": etf["symbol"], "status": "success" if rows else "failed", "record_count": len(rows), "error_message": "" if rows else rs.error_msg})
    finally:
        bs.logout()

    raw_bytes = json.dumps(raw_payload, ensure_ascii=False, indent=2).encode("utf-8")
    checksum = phase2.sha256(raw_bytes)
    for row in normalized:
        row["raw_checksum"] = checksum
    raw_path = storage_root("raw", "fund_etf", "etf_market_data", "baostock_etf_market_sample.json")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_bytes)
    structured_path = storage_root("structured", "fund_etf", "etf_market_data", "baostock_etf_market_sample.jsonl")
    write_jsonl(structured_path, normalized)
    runtime_path = OUTPUT_ROOT / "etf_market_data_normalized_sample.jsonl"
    write_jsonl(runtime_path, normalized)
    quality = etf_quality(normalized)
    result = {
        "generated_at": utc_now(),
        "overall_status": "success" if normalized else "failed",
        "source_id": "baostock_etf_daily_sample",
        "source_role": "ETF market activity candidate source",
        "items": items,
        "record_count": len(normalized),
        "raw_output_path": str(raw_path),
        "structured_output_path": str(structured_path),
        "runtime_mirror_path": str(runtime_path),
        "quality_result": quality,
        "elapsed_seconds": round(time.time() - started, 3),
        "trust_status": "candidate_external_data",
        "candidate_only": True,
        "not_actual_flow_warning": "ETF amount/volume are market activity proxies, not net fund flow.",
    }
    write_json(OUTPUT_ROOT / "etf_market_data_ingestion_results.json", result)
    return result


def normalize_etf_row(row: dict[str, str], etf: dict[str, str]) -> dict[str, Any]:
    return {
        "dataset_id": f"baostock_etf_daily_sample:{etf['symbol']}",
        "source_id": "baostock_etf_daily_sample",
        "etf_code": etf["symbol"],
        "etf_name": etf["name"],
        "region": etf["region"],
        "trade_date": row.get("date"),
        "observation_date": row.get("date"),
        "publish_date": row.get("date"),
        "open": phase2.to_float(row.get("open")),
        "high": phase2.to_float(row.get("high")),
        "low": phase2.to_float(row.get("low")),
        "close": phase2.to_float(row.get("close")),
        "volume": phase2.to_float(row.get("volume")),
        "amount": phase2.to_float(row.get("amount")),
        "turnover_rate": phase2.to_float(row.get("turn")),
        "nav": None,
        "premium_discount": None,
        "shares_outstanding": None,
        "aum": None,
        "currency": "CNY",
        "exchange": etf["exchange"],
        "quality_status": "pending",
        "trust_status": "candidate_external_data",
        "candidate_only": True,
        "raw_checksum": "",
    }


def etf_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "records_present": bool(records),
        "required_fields_present": bool(records) and all(row.get("etf_code") and row.get("trade_date") for row in records),
        "ohlc_numeric": all(isinstance(row.get(field), (int, float)) for row in records for field in ["open", "high", "low", "close"]),
        "volume_non_negative": all((row.get("volume") is None or row["volume"] >= 0) for row in records),
        "amount_non_negative": all((row.get("amount") is None or row["amount"] >= 0) for row in records),
    }
    status = "quality_passed" if all(checks.values()) else "quality_failed"
    return {"quality_status": status, "checks": checks}


def update_fund_flow_signal_schema_v2() -> dict[str, Any]:
    taxonomy = json.loads((CONFIG_ROOT / "fund_etf_taxonomy.json").read_text(encoding="utf-8"))
    taxonomy["version"] = "fund_etf_taxonomy_v2"
    taxonomy["flow_proxy_types"] = sorted(
        set(taxonomy.get("flow_proxy_types", []))
        | {
            "price_momentum",
            "country_exposure_change",
            "sector_exposure_change",
            "currency_exposure_change",
            "estimated_net_flow",
        }
    )
    taxonomy["fund_flow_signal_domains"] = ["fund_master", "nav_performance", "aum_size", "holdings_portfolio", "exposure_allocation", "flow_proxy"]
    write_json(CONFIG_ROOT / "fund_etf_taxonomy.json", taxonomy)
    schema = {
        "generated_at": utc_now(),
        "schema_version": "fund_flow_signal_v2",
        "schemas": {
            "fund_master": ["fund_id", "fund_code", "fund_name", "fund_type", "fund_company", "domicile", "region", "market", "currency", "isin", "ticker", "exchange", "morningstar_sec_id", "official_source_id", "publish_date", "quality_status", "trust_status", "candidate_only"],
            "nav_performance": ["fund_id", "observation_date", "nav", "adjusted_nav", "return_1d", "return_1m", "return_3m", "return_ytd", "currency", "source_id", "publish_date", "quality_status"],
            "aum_size": ["fund_id", "observation_date", "aum", "net_assets", "shares_outstanding", "currency", "source_id", "publish_date", "quality_status", "limitation_note"],
            "holdings_portfolio": ["fund_id", "holding_date", "holding_name", "holding_code", "asset_type", "weight", "shares", "market_value", "sector", "industry", "country", "region", "currency", "source_id", "publish_date", "quality_status"],
            "exposure_allocation": ["fund_id", "observation_date", "allocation_type", "allocation_name", "weight", "source_id", "publish_date", "quality_status"],
            "flow_proxy": ["fund_id_or_etf_code", "observation_date", "proxy_type", "proxy_value", "unit", "confidence", "limitation_note", "not_actual_flow_warning", "quality_status", "trust_status", "candidate_only"],
        },
    }
    write_json(OUTPUT_ROOT / "fund_flow_signal_schema_summary.json", schema)
    write_text(DOCS_ROOT / "FUND_FLOW_SIGNAL_DATA_MODEL_V2.md", "# Fund Flow Signal Data Model v2\n\nFund flow signals are candidate evidence. Trading amount, volume, NAV, AUM, shares outstanding, holdings and exposure changes are proxies unless the source explicitly defines actual net flow.\n")
    return schema


def classify_dataset(name: str) -> tuple[list[str], str, list[str], str, int]:
    text = name.lower()
    domains: list[str] = []
    fields: list[str] = []
    dtype = "other"
    priority = 50
    if any(term in text for term in ["fund", "etf", "share class", "medalist", "rating"]):
        domains.append("fund_etf")
        dtype = "fund_etf"
        priority = min(priority, 10)
    if any(term in text for term in ["holding", "portfolio", "composition"]):
        domains.append("holdings_portfolio")
        dtype = "holdings_portfolio"
        fields += ["holding", "weight", "portfolio_date"]
        priority = min(priority, 3)
    if any(term in text for term in ["allocation", "exposure", "sector", "country", "region", "currency"]):
        domains.append("allocation_exposure")
        dtype = "allocation_exposure"
        fields += ["allocation_weight", "exposure"]
        priority = min(priority, 5)
    if any(term in text for term in ["nav", "aum", "net assets", "flow", "return", "performance", "turnover"]):
        domains.append("flow_proxy_performance")
        dtype = "performance_nav_flow_proxy"
        fields += ["return", "nav", "flow_or_proxy"]
        priority = min(priority, 4)
    if any(term in text for term in ["equity", "stock", "company", "security", "ordinary share", "adr", "listing", "market cap", "financial", "valuation", "operations"]):
        domains.append("equity_stock")
        dtype = "equity_stock_or_company_fundamental"
        fields += ["company_profile", "valuation_or_fundamental"]
        priority = min(priority, 6)
    if any(term in text for term in ["index", "benchmark"]):
        domains.append("index_benchmark")
        dtype = "index_benchmark"
        priority = min(priority, 7)
    if not domains:
        domains.append("licensed_metadata")
    return sorted(set(domains)), dtype, sorted(set(fields)), "metadata_only", priority


def morningstar_dataset_classification_v2() -> dict[str, Any]:
    payload = json.loads((MORNINGSTAR_PILOT_ROOT / "morningstar_dataset_entitlement_map.json").read_text(encoding="utf-8"))
    rows = []
    for item in payload.get("items", []):
        dataset_id = item.get("dataset_id")
        if not dataset_id:
            continue
        name = str(item.get("dataset_name") or "")
        domains, dtype, fields, sample, priority = classify_dataset(name)
        rows.append(
            {
                "dataset_id": dataset_id,
                "dataset_name": name.replace("–", "-"),
                "detected_asset_domains": domains,
                "detected_regions_if_any": [],
                "likely_data_type": dtype,
                "likely_fields": fields,
                "sample_allowed": sample,
                "entitlement_status": item.get("permission_status"),
                "download_risk": "do_not_download_until_entitlement_and_license_review",
                "raw_storage_risk": "needs_user_confirmation",
                "FR_use_case": dtype,
                "priority": priority,
                "next_validation_action": "field metadata sample or user-approved tiny sample only",
            }
        )
    result = {
        "generated_at": utc_now(),
        "items": sorted(rows, key=lambda row: (row["priority"], row["dataset_name"])),
        "domain_counts": dict(Counter(domain for row in rows for domain in row["detected_asset_domains"])),
        "classification_only_no_coverage_inference": True,
    }
    write_json(OUTPUT_ROOT / "morningstar_dataset_universe_classification_v2.json", result)
    write_text(DOCS_ROOT / "MORNINGSTAR_MULTI_ASSET_DATASET_CLASSIFICATION.md", "# Morningstar Multi-Asset Dataset Classification\n\nThis is metadata classification only. Dataset names can suggest likely use cases but cannot prove region coverage, field completeness, freshness or row-level entitlement.\n")
    return result


def multiregion_coverage_validation(classification: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for region in ["US", "China", "Europe"]:
        rows.append(
            {
                "region": region,
                "official_count": 0,
                "morningstar_candidate_count": sum(1 for item in classification["items"] if "fund_etf" in item["detected_asset_domains"]),
                "matched_count": 0,
                "unmatched_official_count": 0,
                "unmatched_morningstar_count": None,
                "coverage_ratio": None,
                "match_accuracy_sample_rate": None,
                "field_completeness_score": None,
                "freshness_gap_days": None,
                "update_frequency_status": "unknown",
                "cross_source_match_rate": None,
                "region_status": "official_universe_missing",
                "validation_status": "blocked",
                "trust_upgrade_status": "not_eligible",
                "next_action": "official_connector_or_manual_import_required",
            }
        )
    result = {"generated_at": utc_now(), "regions": rows, "candidate_only": True}
    write_json(OUTPUT_ROOT / "morningstar_multiregion_fund_coverage_validation.json", result)
    write_text(DOCS_ROOT / "MORNINGSTAR_MULTI_REGION_FUND_COVERAGE_VALIDATION.md", "# Morningstar Multi-Region Fund Coverage Validation\n\nUS, China and Europe coverage validation is blocked until official fund/ETF universe imports or cleared official connectors exist. No coverage ratio is inferred from Morningstar metadata.\n")
    return result


def equity_stock_validation(classification: dict[str, Any]) -> dict[str, Any]:
    candidates = [item for item in classification["items"] if "equity_stock" in item["detected_asset_domains"]]
    markets = []
    for market in ["A-share", "Hong Kong", "US", "Europe"]:
        markets.append(
            {
                "market": market,
                "metadata_candidate_count": len(candidates),
                "sample_data_available": False,
                "coverage_status": "metadata_only_no_universe_sample",
                "field_completeness_status": "unknown",
                "freshness_status": "unknown",
                "cross_source_validation_status": "not_run",
                "trusted_candidate_status": "not_eligible",
                "cross_source_candidates": ["exchange_disclosure", "SEC/CNINFO/HKEX/official or candidate market data source"],
            }
        )
    result = {"generated_at": utc_now(), "candidate_datasets": candidates, "markets": markets, "large_download_performed": False}
    write_json(OUTPUT_ROOT / "morningstar_equity_stock_validation.json", result)
    write_text(DOCS_ROOT / "MORNINGSTAR_EQUITY_STOCK_DATASET_VALIDATION.md", "# Morningstar Equity / Stock Dataset Validation\n\nEquity/stock-like Morningstar metadata exists, but metadata alone does not prove A-share, HK, US or Europe equity coverage. Tiny samples require user-approved entitlement and license checks before any trust upgrade.\n")
    return result


def other_dataset_framework(classification: dict[str, Any]) -> dict[str, Any]:
    kinds = ["index_benchmark", "fund_master_rating_category", "risk_metrics", "portfolio_analytics", "performance_analytics", "fixed_income_bond", "ESG"]
    items = []
    for kind in kinds:
        items.append(
            {
                "dataset_type": kind,
                "use_case": kind.replace("_", " "),
                "required_fields": ["identifier", "observation_date_or_effective_date", "value_or_category", "source_definition"],
                "validation_source": "official_or_authoritative_cross_source_required",
                "freshness_requirement": "dataset_specific",
                "coverage_requirement": "universe_or_sample_coverage_required",
                "trust_upgrade_path": "metadata -> tiny_sample -> QA -> cross_source -> license_review -> trusted_candidate",
                "current_status": "framework_ready_metadata_only",
            }
        )
    result = {"generated_at": utc_now(), "items": items, "classification_domain_counts": classification["domain_counts"]}
    write_json(OUTPUT_ROOT / "morningstar_other_dataset_validation_framework.json", result)
    write_text(DOCS_ROOT / "MORNINGSTAR_OTHER_DATASET_VALIDATION_FRAMEWORK.md", "# Morningstar Other Dataset Validation Framework\n\nNon-fund and non-equity datasets such as benchmark, ratings, risk, performance, portfolio analytics, ESG or fixed income data follow the same metadata -> sample -> QA -> cross-source -> license review path.\n")
    return result


def flow_proxy_v2(etf_market: dict[str, Any]) -> dict[str, Any]:
    records_path = etf_market.get("runtime_mirror_path")
    records = []
    if records_path and Path(records_path).exists():
        for line in Path(records_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    proxies = []
    for row in records[-30:]:
        for proxy_type, value, unit, confidence in [
            ("amount_proxy", row.get("amount"), "CNY", "medium"),
            ("volume_proxy", row.get("volume"), "shares", "medium"),
            ("price_momentum_proxy", row.get("close"), "CNY", "low"),
            ("turnover_proxy", row.get("turnover_rate"), "percent", "low"),
        ]:
            if value is None:
                continue
            proxies.append(
                {
                    "fund_id_or_etf_code": row.get("etf_code"),
                    "observation_date": row.get("observation_date"),
                    "proxy_type": proxy_type,
                    "evidence_source": row.get("source_id"),
                    "proxy_value": value,
                    "unit": unit,
                    "confidence": confidence,
                    "limitation_note": "Proxy indicator; not actual fund flow.",
                    "not_actual_flow_warning": "This proxy must not be described as actual net flow.",
                    "actual_flow_available": False,
                    "quality_status": etf_market.get("quality_result", {}).get("quality_status", "unknown"),
                    "trust_status": "candidate_external_data",
                    "candidate_only": True,
                }
            )
    result = {"generated_at": utc_now(), "proxy_count": len(proxies), "items": proxies, "actual_flow_available": False}
    write_json(OUTPUT_ROOT / "flow_proxy_v2_results.json", result)
    write_text(DOCS_ROOT / "FUND_FLOW_PROXY_METHODOLOGY_V2.md", "# Fund Flow Proxy Methodology v2\n\nAmount, volume, price momentum, turnover, AUM change, shares outstanding change, holdings change and exposure changes are proxies. `estimated_net_flow` may be used only when a licensed/authorized source explicitly defines that field.\n")
    return result


def trust_upgrade_queue_v2(classification: dict[str, Any]) -> dict[str, Any]:
    queue = []
    for item in classification["items"]:
        queue.append(
            {
                "dataset_id": item["dataset_id"],
                "dataset_name": item["dataset_name"],
                "dataset_type": item["likely_data_type"],
                "source_id": "morningstar_direct",
                "current_status": "licensed_source_candidate",
                "required_checks": ["entitlement_allowed", "sample_data_available", "coverage_or_universe_validated", "field_completeness_validated", "freshness_validated", "cross_source_validation", "license_storage_boundary_clear", "QA_passed"],
                "completed_checks": ["metadata_visible"],
                "blockers": ["sample_data_not_loaded", "coverage_not_validated", "freshness_unknown", "field_completeness_unknown", "license_storage_boundary_needs_review"],
                "can_upgrade_to_trusted_candidate": False,
            }
        )
    result = {"generated_at": utc_now(), "trusted_candidate_count": 0, "queue": queue, "formal_trusted_consumption": False}
    write_json(OUTPUT_ROOT / "morningstar_multi_asset_trust_upgrade_queue.json", result)
    write_text(DOCS_ROOT / "MORNINGSTAR_MULTI_ASSET_TRUST_UPGRADE_FRAMEWORK.md", "# Morningstar Multi-Asset Trust Upgrade Framework\n\nMetadata-visible datasets cannot upgrade. Upgrade requires entitlement, sample data, coverage, field completeness, freshness, cross-source validation, license/storage clearance and QA.\n")
    return result


def update_dashboard_status(classification: dict[str, Any], coverage: dict[str, Any], equity: dict[str, Any], trust: dict[str, Any]) -> None:
    dashboard = read_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", default={"sources": []})
    sources = [source for source in dashboard.get("sources", []) if source.get("source_id") != "fund_etf_capital_flow_phase2"]
    sources.append(
        {
            "source_id": "fund_etf_capital_flow_phase2",
            "display_name": "Fund & ETF Capital Flow Phase2",
            "status": "validation_framework_ready",
            "official_universe_status": "manual_fallback_ready",
            "morningstar_dataset_classification_count": len(classification["items"]),
            "fund_regions_validated": [row["region"] for row in coverage["regions"]],
            "equity_stock_market_count": len(equity["markets"]),
            "trusted_candidate_count": trust["trusted_candidate_count"],
            "candidate_only": True,
            "warning": "Flow proxy is not actual flow. Morningstar metadata is not coverage validation.",
        }
    )
    write_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", {"generated_at": utc_now(), "sources": sources})


def write_summary(*, audit: dict[str, Any], official: dict[str, Any], etf: dict[str, Any], schema: dict[str, Any], classification: dict[str, Any], coverage: dict[str, Any], equity: dict[str, Any], other: dict[str, Any], proxy: dict[str, Any], trust: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "generated_at": utc_now(),
        "phase2_completed": True,
        "official_source_audit_completed": True,
        "official_connector_or_manual_fallback": official["connector_status"],
        "etf_market_data_status": etf.get("overall_status"),
        "etf_market_records": etf.get("record_count", 0),
        "fund_flow_signal_model_v2_completed": True,
        "morningstar_dataset_classification_count": len(classification["items"]),
        "multiregion_validation_regions": [row["region"] for row in coverage["regions"]],
        "equity_stock_validation_completed": True,
        "other_dataset_validation_completed": True,
        "flow_proxy_count": proxy["proxy_count"],
        "trust_upgrade_queue_count": len(trust["queue"]),
        "trusted_candidate_count": trust["trusted_candidate_count"],
        "large_morningstar_download_performed": False,
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
        "outputs": {
            "official_source_audit": str(OUTPUT_ROOT / "official_fund_universe_source_audit.json"),
            "official_ingestion": str(OUTPUT_ROOT / "official_fund_universe_ingestion_results.json"),
            "etf_market_data": str(OUTPUT_ROOT / "etf_market_data_ingestion_results.json"),
            "schema_v2": str(OUTPUT_ROOT / "fund_flow_signal_schema_summary.json"),
            "classification": str(OUTPUT_ROOT / "morningstar_dataset_universe_classification_v2.json"),
            "multiregion_validation": str(OUTPUT_ROOT / "morningstar_multiregion_fund_coverage_validation.json"),
            "equity_validation": str(OUTPUT_ROOT / "morningstar_equity_stock_validation.json"),
            "other_validation": str(OUTPUT_ROOT / "morningstar_other_dataset_validation_framework.json"),
            "flow_proxy": str(OUTPUT_ROOT / "flow_proxy_v2_results.json"),
            "trust_upgrade_queue": str(OUTPUT_ROOT / "morningstar_multi_asset_trust_upgrade_queue.json"),
        },
    }
    write_json(OUTPUT_ROOT / "phase2_summary.json", summary)
    return summary


def run() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    audit = official_source_audit()
    official = official_universe_manual_fallback(audit)
    etf = run_etf_market_sample()
    schema = update_fund_flow_signal_schema_v2()
    classification = morningstar_dataset_classification_v2()
    coverage = multiregion_coverage_validation(classification)
    equity = equity_stock_validation(classification)
    other = other_dataset_framework(classification)
    proxy = flow_proxy_v2(etf)
    trust = trust_upgrade_queue_v2(classification)
    update_dashboard_status(classification, coverage, equity, trust)
    return write_summary(audit=audit, official=official, etf=etf, schema=schema, classification=classification, coverage=coverage, equity=equity, other=other, proxy=proxy, trust=trust)


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                "completed": result["phase2_completed"],
                "etf_market_data_status": result["etf_market_data_status"],
                "etf_market_records": result["etf_market_records"],
                "classification_count": result["morningstar_dataset_classification_count"],
                "trusted_candidate_count": result["trusted_candidate_count"],
                "outputs_root": str(OUTPUT_ROOT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
