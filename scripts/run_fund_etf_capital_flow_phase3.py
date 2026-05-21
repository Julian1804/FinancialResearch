from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_morningstar_connector_pilot import (  # noqa: E402
    load_morningstar_secret,
    token_for_library,
    token_health_check,
    run_limited_call,
)
from scripts.run_morningstar_safe_access_audit import (  # noqa: E402
    mask_token,
    read_json,
    sanitize_error,
    write_json,
    write_text,
)


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "fund_etf_capital_flow_phase3"
DOCS_ROOT = PROJECT_ROOT / "docs"
PHASE2_ROOT = PROJECT_ROOT / "runtime" / "fund_etf_capital_flow_phase2"
AUTHORITATIVE_RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "authoritative_crawler_framework"
RAW_OFFICIAL_ROOT = Path("Z:/data_lake_master/raw/fund_etf/official_universe_phase3")
STRUCTURED_OFFICIAL_ROOT = Path("Z:/data_lake_master/structured/fund_etf/official_universe_phase3")

NASDAQ_FILES = [
    {
        "source_id": "nasdaq_trader_nasdaqlisted",
        "region": "US",
        "source_name": "Nasdaq Trader Symbol Directory - nasdaqlisted",
        "url": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        "role": "exchange_market_operator_candidate",
    },
    {
        "source_id": "nasdaq_trader_otherlisted",
        "region": "US",
        "source_name": "Nasdaq Trader Symbol Directory - otherlisted",
        "url": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
        "role": "exchange_market_operator_candidate",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows), encoding="utf-8")


def checksum_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def fetch_text_file(source: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    req = urllib.request.Request(
        source["url"],
        headers={
            "User-Agent": "FinancialResearch/phase3-official-universe-small-sample",
            "Accept": "text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            status = getattr(response, "status", 200)
            headers = dict(response.headers.items())
        raw_path = RAW_OFFICIAL_ROOT / f"{source['source_id']}.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        return {
            **source,
            "attempted": True,
            "status": "success" if status == 200 and raw else "failed",
            "http_status": status,
            "elapsed_seconds": round(time.time() - started, 3),
            "raw_path": str(raw_path),
            "raw_checksum": checksum_bytes(raw),
            "content_length": len(raw),
            "content_type": headers.get("Content-Type"),
            "error_type": None,
            "error_message": None,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fallback = fetch_text_file_with_curl(source)
        if fallback["status"] == "success":
            fallback["primary_error_type"] = type(exc).__name__
            fallback["primary_error_message"] = sanitize_error(exc, load_morningstar_secret().get("md_auth_token"))
            fallback["fallback_method"] = "curl.exe"
            return fallback
        return {
            **source,
            "attempted": True,
            "status": "failed",
            "http_status": None,
            "elapsed_seconds": round(time.time() - started, 3),
            "raw_path": None,
            "raw_checksum": None,
            "content_length": 0,
            "content_type": None,
            "error_type": type(exc).__name__,
            "error_message": sanitize_error(exc, load_morningstar_secret().get("md_auth_token")),
            "fallback_method": "curl.exe",
            "fallback_status": fallback["status"],
            "fallback_error_type": fallback.get("error_type"),
            "fallback_error_message": fallback.get("error_message"),
        }


def fetch_text_file_with_curl(source: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    raw_path = RAW_OFFICIAL_ROOT / f"{source['source_id']}.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                "curl.exe",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "20",
                "--user-agent",
                "FinancialResearch/phase3-official-universe-small-sample",
                source["url"],
                "--output",
                str(raw_path),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        if result.returncode == 0 and raw_path.exists() and raw_path.stat().st_size > 0:
            raw = raw_path.read_bytes()
            return {
                **source,
                "attempted": True,
                "status": "success",
                "http_status": 200,
                "elapsed_seconds": round(time.time() - started, 3),
                "raw_path": str(raw_path),
                "raw_checksum": checksum_bytes(raw),
                "content_length": len(raw),
                "content_type": "text/plain",
                "error_type": None,
                "error_message": None,
            }
        return {
            **source,
            "attempted": True,
            "status": "failed",
            "http_status": None,
            "elapsed_seconds": round(time.time() - started, 3),
            "raw_path": str(raw_path) if raw_path.exists() else None,
            "raw_checksum": None,
            "content_length": raw_path.stat().st_size if raw_path.exists() else 0,
            "content_type": None,
            "error_type": "curl_failed",
            "error_message": (result.stderr or result.stdout)[-800:],
        }
    except (subprocess.SubprocessError, OSError) as exc:
        return {
            **source,
            "attempted": True,
            "status": "failed",
            "http_status": None,
            "elapsed_seconds": round(time.time() - started, 3),
            "raw_path": str(raw_path) if raw_path.exists() else None,
            "raw_checksum": None,
            "content_length": raw_path.stat().st_size if raw_path.exists() else 0,
            "content_type": None,
            "error_type": type(exc).__name__,
            "error_message": sanitize_error(exc, load_morningstar_secret().get("md_auth_token")),
        }


def parse_nasdaq_rows(fetch_result: dict[str, Any], sample_limit: int = 25) -> list[dict[str, Any]]:
    raw_path = fetch_result.get("raw_path")
    if not raw_path or not Path(raw_path).exists():
        return []
    lines = [
        line
        for line in Path(raw_path).read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.startswith("File Creation Time:")
    ]
    if not lines:
        return []
    reader = csv.DictReader(lines, delimiter="|")
    rows = []
    for row in reader:
        if row.get("ETF", "").upper() != "Y":
            continue
        symbol = row.get("Symbol") or row.get("ACT Symbol") or row.get("CQS Symbol")
        name = row.get("Security Name") or row.get("Security Name")
        market_category = row.get("Market Category") or row.get("Listing Exchange")
        rows.append(
            {
                "dataset_id": "official_universe_us_etf_nasdaq_trader_sample",
                "source_id": fetch_result["source_id"],
                "source_name": fetch_result["source_name"],
                "region": "US",
                "country": "US",
                "fund_code": symbol,
                "ticker": symbol,
                "fund_name": name,
                "fund_type": "ETF",
                "asset_class": "unknown_from_symbol_directory",
                "exchange": market_category or "unknown",
                "currency": "USD",
                "listing_date": None,
                "tracking_index": None,
                "isin": None,
                "publish_date": None,
                "source_observation_date": utc_now()[:10],
                "retrieved_at": utc_now(),
                "raw_path": fetch_result["raw_path"],
                "raw_checksum": fetch_result["raw_checksum"],
                "quality_status": "quality_warning",
                "trust_status": "official_or_market_operator_universe_sample_candidate",
                "candidate_only": True,
                "limitation_note": "Nasdaq Trader symbol directory is a public market-operator list; source terms and complete ETF universe role still need review before trusted use.",
            }
        )
        if len(rows) >= sample_limit:
            break
    return rows


def official_universe_acquisition() -> dict[str, Any]:
    fetched = [fetch_text_file(source) for source in NASDAQ_FILES]
    samples: list[dict[str, Any]] = []
    for result in fetched:
        samples.extend(parse_nasdaq_rows(result, sample_limit=25))

    structured_path = STRUCTURED_OFFICIAL_ROOT / "us_etf_nasdaq_trader_symbol_directory_sample.jsonl"
    runtime_path = OUTPUT_ROOT / "official_universe_us_etf_sample.jsonl"
    if samples:
        write_jsonl(structured_path, samples)
        write_jsonl(runtime_path, samples)

    regions = [
        {
            "region": "China",
            "status": "manual_import_required",
            "official_universe_sample_acquired": False,
            "official_count": None,
            "sources_attempted": ["AMAC", "SSE", "SZSE", "fund_company_official_sites"],
            "reason": "No stable official no-login/no-captcha endpoint has been cleared for automated retrieval; manual CSV/Excel import remains the safe path.",
            "next_action": "user_download_or_prepare_AMAC_exchange_or_issuer_csv",
        },
        {
            "region": "US",
            "status": "official_universe_sample_acquired" if samples else "manual_import_required",
            "official_universe_sample_acquired": bool(samples),
            "official_count": len(samples) if samples else None,
            "sources_attempted": [item["source_id"] for item in fetched],
            "reason": "Nasdaq Trader public symbol directory sample acquired." if samples else "Nasdaq Trader symbol directory fetch failed or returned no ETF sample.",
            "next_action": "review source terms and extend to issuer/SEC validation before coverage claim" if samples else "manual import or alternate official source required",
        },
        {
            "region": "Europe",
            "status": "manual_import_required",
            "official_universe_sample_acquired": False,
            "official_count": None,
            "sources_attempted": ["ESMA/UCITS", "LSE", "Euronext", "Xetra", "issuer_lists"],
            "reason": "No pan-European official universe file has been cleared for automated retrieval in this phase.",
            "next_action": "manual import or source-specific exchange/issuer endpoint review",
        },
    ]
    result = {
        "generated_at": utc_now(),
        "phase": "fund_etf_capital_flow_phase3",
        "large_download_performed": False,
        "high_frequency_requests": False,
        "fetch_results": fetched,
        "sample_record_count": len(samples),
        "structured_sample_path": str(structured_path) if samples else None,
        "runtime_sample_path": str(runtime_path) if samples else None,
        "regions": regions,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "official_universe_acquisition_results.json", result)
    return result


def safe_morningstar_calls() -> dict[str, Any]:
    health = token_health_check()
    token = load_morningstar_secret().get("md_auth_token")
    library_token = token_for_library(token)
    allowed = bool(library_token) and health.get("token_status") == "available"
    calls = []
    for call_name in ["data_point_settings", "investment_search_spy", "user_investment_lists"]:
        if allowed:
            calls.append(run_limited_call(call_name, library_token))
        else:
            calls.append(
                {
                    "call_name": call_name,
                    "attempted": False,
                    "status": "skipped",
                    "error_type": "token_not_available",
                    "error_message": "Morningstar token missing or expired; user action required.",
                    "elapsed_seconds": 0,
                }
            )
    return {
        "token_health": {
            "token_present": health.get("token_present"),
            "token_status": health.get("token_status"),
            "masked_token": health.get("masked_token"),
            "token_leaked": False,
            "no_auto_login": True,
            "no_password_saved": True,
        },
        "calls": calls,
    }


def tiny_sample_validation(classification: dict[str, Any]) -> dict[str, Any]:
    safe_calls = safe_morningstar_calls()
    call_status = {call["call_name"]: call for call in safe_calls["calls"]}
    field_call = call_status.get("data_point_settings", {})
    search_call = call_status.get("investment_search_spy", {})
    list_call = call_status.get("user_investment_lists", {})

    items = []
    for item in classification.get("items", []):
        dtype = item.get("likely_data_type", "other")
        sample_status = "metadata_visible_sample_not_requested"
        sample_evidence = []
        if dtype in {"performance_nav_flow_proxy", "equity_stock_or_company_fundamental"} and field_call.get("status") == "success":
            sample_status = "tiny_field_metadata_available"
            sample_evidence.append("data_point_settings")
        if dtype in {"fund_etf", "equity_stock_or_company_fundamental"} and search_call.get("status") == "success":
            sample_status = "tiny_investment_search_available"
            sample_evidence.append("investment_search_spy")
        if dtype == "holdings_portfolio":
            sample_status = "method_unavailable_without_user_approved_dataset_query"
        items.append(
            {
                "dataset_id": item.get("dataset_id"),
                "dataset_name": item.get("dataset_name"),
                "likely_data_type": dtype,
                "priority": item.get("priority"),
                "metadata_visible": True,
                "tiny_sample_status": sample_status,
                "sample_evidence": sample_evidence,
                "fields_or_shape_observed": {
                    "data_point_settings_columns": (field_call.get("payload") or {}).get("columns", []) if field_call.get("status") == "success" else [],
                    "investment_search_shape": search_call.get("payload") if search_call.get("status") == "success" else None,
                    "user_list_shape": list_call.get("payload") if list_call.get("status") == "success" else None,
                },
                "usable_for_fr": sample_status in {"tiny_field_metadata_available", "tiny_investment_search_available"},
                "limitations": "Tiny sample validates method reachability only; it does not validate regional coverage, field completeness, freshness, or license/storage boundary.",
                "candidate_only": True,
            }
        )

    result = {
        "generated_at": utc_now(),
        "token_status": safe_calls["token_health"]["token_status"],
        "masked_token": safe_calls["token_health"]["masked_token"],
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "large_morningstar_download_performed": False,
        "call_results": safe_calls["calls"],
        "items": items,
        "tiny_sample_dataset_count": sum(1 for item in items if item["usable_for_fr"]),
    }
    write_json(OUTPUT_ROOT / "morningstar_tiny_sample_validation_results.json", result)
    return result


def equity_stock_validation_phase3(tiny: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    equity_candidates = [item for item in classification.get("items", []) if "equity_stock" in item.get("detected_asset_domains", [])]
    investment_search = next((call for call in tiny.get("call_results", []) if call.get("call_name") == "investment_search_spy"), {})
    search_success = investment_search.get("status") == "success"
    markets = []
    for market in ["A-share", "Hong Kong", "US", "Europe"]:
        if market == "US" and search_success:
            status = "tiny_search_method_reachable_not_coverage_validated"
            evidence = "SPY keyword search returned a shape/count summary; no full universe or dataset-row coverage inference."
        else:
            status = "metadata_or_framework_only"
            evidence = "No market-specific tiny equity universe sample acquired in Phase 3."
        markets.append(
            {
                "market": market,
                "coverage_status": status,
                "field_completeness_status": "unknown",
                "freshness_status": "unknown",
                "cross_source_validation_status": "not_run",
                "evidence": evidence,
                "can_upgrade_to_trusted_candidate": False,
                "blockers": ["coverage_unknown", "field_completeness_unknown", "freshness_unknown", "license_boundary_unclear"],
            }
        )
    result = {
        "generated_at": utc_now(),
        "equity_candidate_dataset_count": len(equity_candidates),
        "equity_candidate_datasets": equity_candidates[:15],
        "markets": markets,
        "large_download_performed": False,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "morningstar_equity_stock_validation_phase3.json", result)
    return result


def flow_proxy_v3() -> dict[str, Any]:
    phase2_records = read_jsonl(PHASE2_ROOT / "etf_market_data_normalized_sample.jsonl")
    proxies = []
    for row in phase2_records:
        base = {
            "dataset_id": "fund_etf_flow_proxy_v3_market_activity",
            "source_id": row.get("source_id", "baostock_etf_daily_sample"),
            "fund_id_or_etf_code": row.get("etf_code"),
            "observation_date": row.get("trade_date"),
            "quality_status": row.get("quality_status", "quality_passed"),
            "trust_status": "candidate_external_data",
            "candidate_only": True,
            "actual_flow_available": False,
            "not_actual_flow_warning": "This is a flow proxy only and must not be described as actual net fund flow.",
        }
        for proxy_type, field, unit, confidence, note in [
            ("amount_proxy", "amount", "CNY", "medium", "Trading amount is market activity, not subscription/redemption flow."),
            ("volume_proxy", "volume", "shares", "medium", "Trading volume is activity/liquidity proxy, not net flow."),
            ("price_momentum_proxy", "pct_change", "percent", "low", "Price movement can reflect valuation and liquidity but not net flow."),
            ("turnover_proxy", "turnover_rate", "percent", "low", "Turnover is a trading intensity proxy."),
        ]:
            value = row.get(field)
            proxies.append(
                {
                    **base,
                    "proxy_type": proxy_type,
                    "proxy_value": value,
                    "unit": unit,
                    "confidence": confidence,
                    "limitation_note": note,
                }
            )

    unavailable = []
    for proxy_type in [
        "aum_change_proxy",
        "shares_outstanding_change_proxy",
        "holdings_change_proxy",
        "sector_exposure_change_proxy",
        "country_exposure_change_proxy",
        "currency_exposure_change_proxy",
        "estimated_net_flow",
    ]:
        unavailable.append(
            {
                "proxy_type": proxy_type,
                "status": "data_not_available_yet",
                "actual_flow_available": False,
                "not_actual_flow_warning": "Proxy requires AUM/shares/holdings/exposure or explicit flow source; do not infer from price/volume alone.",
                "next_action": "Morningstar or official/issuer source tiny sample plus license boundary review",
            }
        )
    result = {
        "generated_at": utc_now(),
        "proxy_version": "v3",
        "proxy_count": len(proxies),
        "source_record_count": len(phase2_records),
        "items": proxies,
        "unavailable_proxy_types": unavailable,
        "actual_flow_available": False,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "flow_proxy_v3_results.json", result)
    return result


def coverage_validation_phase3(official: dict[str, Any], tiny: dict[str, Any]) -> dict[str, Any]:
    regions = []
    official_by_region = {row["region"]: row for row in official.get("regions", [])}
    for region in ["US", "China", "Europe"]:
        source = official_by_region.get(region, {})
        official_count = source.get("official_count")
        if region == "US" and source.get("official_universe_sample_acquired"):
            validation_status = "official_universe_sample_acquired_morningstar_match_pending"
            blockers = ["morningstar_identifier_match_not_run", "freshness_unknown", "license_boundary_unclear"]
        else:
            validation_status = "blocked"
            blockers = ["official_universe_missing", "manual_import_required", "freshness_unknown", "field_completeness_unknown"]
        regions.append(
            {
                "region": region,
                "official_count": official_count,
                "morningstar_candidate_count": None,
                "matched_count": 0,
                "unmatched_official_count": official_count if official_count else None,
                "unmatched_morningstar_count": None,
                "coverage_ratio": None,
                "match_accuracy_sample_rate": None,
                "field_completeness_score": None,
                "freshness_gap_days": None,
                "update_frequency_status": "unknown",
                "cross_source_match_rate": None,
                "validation_status": validation_status,
                "trust_upgrade_status": "blocked",
                "blockers": blockers,
                "next_action": source.get("next_action") or "official_connector_or_manual_import_required",
            }
        )
    result = {
        "generated_at": utc_now(),
        "regions": regions,
        "tiny_sample_dataset_count": tiny.get("tiny_sample_dataset_count", 0),
        "coverage_inference_from_metadata": False,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "coverage_validation_phase3.json", result)
    return result


def trust_upgrade_queue_phase3(classification: dict[str, Any], coverage: dict[str, Any], tiny: dict[str, Any]) -> dict[str, Any]:
    tiny_by_dataset = {item.get("dataset_id"): item for item in tiny.get("items", [])}
    queue = []
    for item in classification.get("items", []):
        tiny_item = tiny_by_dataset.get(item.get("dataset_id"), {})
        completed = ["metadata_visible"] + (["tiny_method_reachable"] if tiny_item.get("usable_for_fr") else [])
        blockers = [
            "coverage_validation_missing",
            "freshness_unknown",
            "field_completeness_not_verified",
            "license_storage_boundary_unclear",
            "cross_source_validation_missing",
        ]
        queue.append(
            {
                "dataset_id": item.get("dataset_id"),
                "dataset_name": item.get("dataset_name"),
                "likely_data_type": item.get("likely_data_type"),
                "current_status": "licensed_source_candidate",
                "required_checks": ["entitlement", "tiny_sample", "coverage", "field_completeness", "freshness", "cross_source", "license_boundary", "QA"],
                "completed_checks": completed,
                "blockers": blockers,
                "next_action": "official universe matching and user-approved tiny dataset retrieval" if tiny_item.get("usable_for_fr") else "identify callable sample method or keep metadata-only",
                "can_upgrade_to_trusted_candidate": False,
            }
        )
    result = {
        "generated_at": utc_now(),
        "queue": queue,
        "trusted_candidate_count": 0,
        "ready_for_trusted_candidate_count": 0,
        "coverage_regions": coverage.get("regions", []),
        "formal_trusted_consumption": False,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "trust_upgrade_queue_phase3.json", result)
    return result


def user_action_package() -> dict[str, Any]:
    actions = [
        {
            "region": "China",
            "needed_file": "AMAC / SSE / SZSE / fund-company official fund or ETF list CSV/XLSX",
            "target_template": "runtime/fund_etf_capital_flow/manual_import_templates/china_public_fund_official_list_template.csv",
            "reason": "Automated official universe acquisition is not cleared; Morningstar China coverage validation needs authoritative baseline.",
        },
        {
            "region": "Europe",
            "needed_file": "LSE/Euronext/Xetra or issuer official ETF list CSV/XLSX",
            "target_template": "runtime/fund_etf_capital_flow/manual_import_templates/exchange_etf_list_template.csv",
            "reason": "No pan-European no-login official universe sample acquired.",
        },
        {
            "region": "US",
            "needed_file": "Issuer official ETF list or SEC/market operator validation file",
            "target_template": "runtime/fund_etf_capital_flow/manual_import_templates/exchange_etf_list_template.csv",
            "reason": "Nasdaq Trader sample is useful but not sufficient for full coverage validation.",
        },
    ]
    text = "# Fund / ETF Phase 3 User Action Package\n\n"
    for action in actions:
        text += f"- {action['region']}: provide {action['needed_file']} using `{action['target_template']}`. Reason: {action['reason']}\n"
    path = OUTPUT_ROOT / "user_action_required.md"
    write_text(path, text)
    result = {"generated_at": utc_now(), "actions": actions, "path": str(path)}
    write_json(OUTPUT_ROOT / "user_action_required.json", result)
    return result


def write_docs(summary: dict[str, Any]) -> None:
    write_text(
        DOCS_ROOT / "FUND_ETF_CAPITAL_FLOW_PHASE3_REPORT.md",
        f"""# Fund / ETF Capital Flow Phase 3 Report

Generated at: {summary['generated_at']}

## Scope

Phase 3 attempted low-frequency official/authoritative universe acquisition and Morningstar tiny-sample validation. Morningstar remains a licensed data candidate source; metadata visibility is not treated as coverage validation.

## Results

- Official universe sample records: {summary['official_universe_sample_records']}
- Morningstar tiny-sample usable dataset count: {summary['morningstar_tiny_sample_dataset_count']}
- Coverage validation regions: {', '.join(summary['coverage_regions'])}
- Trusted candidate count: {summary['trusted_candidate_count']}

## Boundaries

- Auto Morningstar login: no.
- Password saved: no.
- Token leaked: no.
- Large Morningstar download: no.
- OpenAI API called: no.
- Formal trusted consumption affected: no.
""",
    )
    write_text(
        DOCS_ROOT / "MORNINGSTAR_TINY_SAMPLE_VALIDATION_PHASE3.md",
        "# Morningstar Tiny Sample Validation Phase 3\n\nTiny calls only validate method reachability and shape. They do not validate coverage, freshness, or license/storage boundaries.\n",
    )
    write_text(
        DOCS_ROOT / "FUND_ETF_COVERAGE_VALIDATION_PHASE3.md",
        "# Fund / ETF Coverage Validation Phase 3\n\nUS obtained a small Nasdaq Trader ETF symbol-directory sample when available. China and Europe remain manual-import-first until official stable endpoints are reviewed. No Morningstar dataset is upgraded to trusted_candidate.\n",
    )
    write_text(
        DOCS_ROOT / "FUND_FLOW_PROXY_METHODOLOGY_V3.md",
        "# Fund Flow Proxy Methodology v3\n\nTrading amount, volume, price momentum, turnover, AUM change, shares outstanding change, holdings change, allocation/exposure change and estimated net flow are distinct. Unless a source explicitly defines actual net flow, every item is a proxy and must carry `not_actual_flow_warning`.\n",
    )


def update_dashboard_status(summary: dict[str, Any]) -> None:
    dashboard = read_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", default={"sources": []})
    sources = [source for source in dashboard.get("sources", []) if source.get("source_id") != "fund_etf_capital_flow_phase3"]
    sources.append(
        {
            "source_id": "fund_etf_capital_flow_phase3",
            "display_name": "Fund & ETF Capital Flow Phase3",
            "status": "pilot_completed",
            "official_universe_sample_records": summary["official_universe_sample_records"],
            "morningstar_tiny_sample_dataset_count": summary["morningstar_tiny_sample_dataset_count"],
            "trusted_candidate_count": summary["trusted_candidate_count"],
            "candidate_only": True,
            "warning": "Morningstar tiny sample is not coverage validation. Flow proxy is not actual flow.",
        }
    )
    write_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", {"generated_at": utc_now(), "sources": sources})


def write_summary(
    official: dict[str, Any],
    tiny: dict[str, Any],
    equity: dict[str, Any],
    proxy: dict[str, Any],
    coverage: dict[str, Any],
    trust: dict[str, Any],
    user_actions: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "generated_at": utc_now(),
        "phase3_completed": True,
        "official_universe_sample_records": official.get("sample_record_count", 0),
        "official_universe_regions": {row["region"]: row["status"] for row in official.get("regions", [])},
        "morningstar_tiny_sample_dataset_count": tiny.get("tiny_sample_dataset_count", 0),
        "morningstar_equity_market_status": {row["market"]: row["coverage_status"] for row in equity.get("markets", [])},
        "flow_proxy_v3_count": proxy.get("proxy_count", 0),
        "coverage_regions": [row["region"] for row in coverage.get("regions", [])],
        "trust_upgrade_queue_count": len(trust.get("queue", [])),
        "trusted_candidate_count": trust.get("trusted_candidate_count", 0),
        "user_action_required_count": len(user_actions.get("actions", [])),
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "large_morningstar_download_performed": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
        "outputs": {
            "official_universe_acquisition": str(OUTPUT_ROOT / "official_universe_acquisition_results.json"),
            "morningstar_tiny_sample_validation": str(OUTPUT_ROOT / "morningstar_tiny_sample_validation_results.json"),
            "morningstar_equity_stock_validation": str(OUTPUT_ROOT / "morningstar_equity_stock_validation_phase3.json"),
            "flow_proxy_v3": str(OUTPUT_ROOT / "flow_proxy_v3_results.json"),
            "coverage_validation_phase3": str(OUTPUT_ROOT / "coverage_validation_phase3.json"),
            "trust_upgrade_queue_phase3": str(OUTPUT_ROOT / "trust_upgrade_queue_phase3.json"),
            "user_action_required": str(OUTPUT_ROOT / "user_action_required.md"),
        },
    }
    write_json(OUTPUT_ROOT / "phase3_summary.json", summary)
    return summary


def run() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    classification = read_json(PHASE2_ROOT / "morningstar_dataset_universe_classification_v2.json", default={"items": []})
    official = official_universe_acquisition()
    tiny = tiny_sample_validation(classification)
    equity = equity_stock_validation_phase3(tiny, classification)
    proxy = flow_proxy_v3()
    coverage = coverage_validation_phase3(official, tiny)
    trust = trust_upgrade_queue_phase3(classification, coverage, tiny)
    actions = user_action_package()
    summary = write_summary(official, tiny, equity, proxy, coverage, trust, actions)
    write_docs(summary)
    update_dashboard_status(summary)
    return summary


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                "completed": result["phase3_completed"],
                "official_universe_sample_records": result["official_universe_sample_records"],
                "morningstar_tiny_sample_dataset_count": result["morningstar_tiny_sample_dataset_count"],
                "trusted_candidate_count": result["trusted_candidate_count"],
                "outputs_root": str(OUTPUT_ROOT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
