from __future__ import annotations

import csv
import json
import re
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
from urllib.parse import urljoin


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

AMAC_PUBLIC_FUND_PAGE = "https://www.amac.org.cn/sjtj/tjbg/gmjj/"
CHINA_FUND_COMPANY_SITES = [
    {"company": "Southern Fund", "company_cn": "南方基金", "url": "https://www.southernfund.com/"},
    {"company": "E Fund", "company_cn": "易方达基金", "url": "https://www.efunds.com.cn/"},
    {"company": "ChinaAMC", "company_cn": "华夏基金", "url": "https://www.chinaamc.com/"},
]
EUROPE_FEASIBILITY_SOURCES = [
    {"source_id": "lse_etf_directory", "source_name": "London Stock Exchange ETF directory", "url": "https://www.londonstockexchange.com/raise-finance/funds-etps-and-investment-trusts/etfs"},
    {"source_id": "euronext_etf_directory", "source_name": "Euronext ETF directory", "url": "https://live.euronext.com/en/products/etfs"},
    {"source_id": "xetra_etf_directory", "source_name": "Xetra ETF directory", "url": "https://www.xetra.com/xetra-en/instruments/etfs"},
    {"source_id": "ishares_europe_etfs", "source_name": "iShares Europe ETF product list", "url": "https://www.ishares.com/uk/individual/en/products/etf-investments"},
    {"source_id": "amundi_etfs", "source_name": "Amundi ETF product list", "url": "https://www.amundietf.lu/en/individual/products/etf"},
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


def fetch_url_to_path(url: str, path: Path, *, accept: str = "*/*", timeout: int = 25) -> dict[str, Any]:
    started = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                "curl.exe",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                str(timeout),
                "--user-agent",
                "FinancialResearch/phase3-controlled-official-source",
                "--header",
                f"Accept: {accept}",
                url,
                "--output",
                str(path),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout + 8,
            check=False,
        )
        if result.returncode == 0 and path.exists() and path.stat().st_size > 0:
            raw = path.read_bytes()
            return {
                "url": url,
                "status": "success",
                "elapsed_seconds": round(time.time() - started, 3),
                "path": str(path),
                "content_length": len(raw),
                "checksum": checksum_bytes(raw),
                "error_type": None,
                "error_message": None,
            }
        return {
            "url": url,
            "status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "path": str(path) if path.exists() else None,
            "content_length": path.stat().st_size if path.exists() else 0,
            "checksum": None,
            "error_type": "curl_failed",
            "error_message": (result.stderr or result.stdout)[-800:],
        }
    except (subprocess.SubprocessError, OSError) as exc:
        return {
            "url": url,
            "status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "path": str(path) if path.exists() else None,
            "content_length": path.stat().st_size if path.exists() else 0,
            "checksum": None,
            "error_type": type(exc).__name__,
            "error_message": sanitize_error(exc, load_morningstar_secret().get("md_auth_token")),
        }


def parse_number(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        return f"PDF_TEXT_EXTRACTION_UNAVAILABLE:{type(exc).__name__}:{exc}"
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        return f"PDF_TEXT_EXTRACTION_FAILED:{type(exc).__name__}:{exc}"


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


def amac_total_benchmark() -> dict[str, Any]:
    html_path = RAW_OFFICIAL_ROOT / "amac_public_fund_page.html"
    page_fetch = fetch_url_to_path(AMAC_PUBLIC_FUND_PAGE, html_path, accept="text/html", timeout=25)
    links: list[dict[str, str]] = []
    if page_fetch["status"] == "success":
        html = html_path.read_text(encoding="utf-8", errors="replace")
        pattern = re.compile(r'<a\s+href="(?P<href>[^"]+\.pdf)">\s*(?P<title>公募基金市场数据（[^<]+）)\s*<i>\s*(?P<publish>[^<]+)\s*</i>', re.I)
        for match in pattern.finditer(html):
            links.append(
                {
                    "title": re.sub(r"\s+", "", match.group("title")),
                    "url": urljoin(AMAC_PUBLIC_FUND_PAGE, match.group("href")),
                    "publish_date": match.group("publish").strip(),
                }
            )
    latest = links[0] if links else None
    pdf_fetch: dict[str, Any] | None = None
    benchmark: dict[str, Any] | None = None
    category_rows: list[dict[str, Any]] = []
    if latest:
        safe_name = re.sub(r"[^0-9A-Za-z_]+", "_", latest["title"])[:80] or "amac_public_fund_market_data"
        pdf_path = RAW_OFFICIAL_ROOT / f"{safe_name}.pdf"
        pdf_fetch = fetch_url_to_path(latest["url"], pdf_path, accept="application/pdf", timeout=35)
        if pdf_fetch["status"] == "success":
            text = extract_pdf_text(pdf_path)
            text_path = OUTPUT_ROOT / "amac_public_fund_market_data_text_extract.txt"
            write_text(text_path, text)
            period_match = re.search(r"公募基金市场数据（(?P<period>[^）]+)）", text)
            asof_match = re.search(r"截至\s*(?P<asof>\d{4}\s*年\s*\d+\s*月(?:底)?)", text)
            manager_match = re.search(r"管理机构共\s*(?P<total>\d+)\s*家.*?基金管理公司\s*(?P<company>\d+)\s*家.*?资产管理机构\s*(?P<asset>\d+)\s*家", text, re.S)
            nav_match = re.search(r"资产净值合计\s*(?P<nav>[\d.]+)\s*万亿元", text)
            total_row = re.search(r"全部\s+(?P<count>[\d,]+)\s+(?P<shares>[\d,.]+)\s+(?P<nav>[\d,.]+)", text)
            for name in ["股票基金", "债券基金", "货币市场基金", "混合基金", "基金中基金", "其他基金"]:
                row_match = re.search(rf"{name}\s+(?P<count>[\d,]+)\s+(?P<shares>[\d,.]+)\s+(?P<nav>[\d,.]+)", text)
                if row_match:
                    category_rows.append(
                        {
                            "category": name,
                            "fund_count": int(row_match.group("count").replace(",", "")),
                            "shares_100m": parse_number(row_match.group("shares")),
                            "nav_100m_cny": parse_number(row_match.group("nav")),
                        }
                    )
            benchmark = {
                "dataset_id": "amac_public_fund_total_benchmark",
                "source_id": "amac_public_fund_market_data",
                "source_name": "Asset Management Association of China - public fund market data",
                "region": "China",
                "benchmark_type": "total_market_benchmark",
                "report_title": latest["title"],
                "report_period": period_match.group("period") if period_match else None,
                "as_of_text": asof_match.group("asof").replace(" ", "") if asof_match else None,
                "publish_date": latest["publish_date"],
                "manager_institution_count": int(manager_match.group("total")) if manager_match else None,
                "fund_management_company_count": int(manager_match.group("company")) if manager_match else None,
                "qualified_asset_manager_count": int(manager_match.group("asset")) if manager_match else None,
                "total_nav_trillion_cny": parse_number(nav_match.group("nav")) if nav_match else None,
                "total_fund_count": int(total_row.group("count").replace(",", "")) if total_row else None,
                "total_shares_100m": parse_number(total_row.group("shares")) if total_row else None,
                "total_nav_100m_cny": parse_number(total_row.group("nav")) if total_row else None,
                "category_rows": category_rows,
                "raw_pdf_path": pdf_fetch["path"],
                "raw_pdf_checksum": pdf_fetch["checksum"],
                "text_extract_path": str(text_path),
                "quality_status": "quality_passed" if total_row and nav_match and manager_match else "quality_warning",
                "trust_status": "official_total_benchmark_candidate",
                "candidate_only": True,
                "limitation_note": "AMAC total benchmark validates aggregate China public-fund market size, not individual fund universe coverage.",
            }
            write_json(OUTPUT_ROOT / "amac_total_benchmark.json", benchmark)
            write_json(STRUCTURED_OFFICIAL_ROOT / "amac_total_benchmark.json", benchmark)
    result = {
        "generated_at": utc_now(),
        "page_fetch": page_fetch,
        "report_links_found": len(links),
        "latest_report": latest,
        "pdf_fetch": pdf_fetch,
        "benchmark_status": "completed" if benchmark else "failed",
        "benchmark": benchmark,
        "category_count": len(category_rows),
        "large_download_performed": False,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "amac_total_benchmark_result.json", result)
    return result


def source_reachability_probe(source: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    try:
        result = subprocess.run(
            [
                "curl.exe",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "15",
                "--range",
                "0-4095",
                "--user-agent",
                "FinancialResearch/phase3-source-feasibility",
                source["url"],
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return {
            **source,
            "attempted": True,
            "status": "reachable" if result.returncode == 0 and (stdout or stderr) else "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "sample_length": len(stdout),
            "error_type": None if result.returncode == 0 else "curl_failed",
            "error_message": stderr[-500:],
            "automated_universe_parse_status": "not_attempted_terms_and_schema_review_required",
            "crawler_allowed": "needs_terms_review",
        }
    except (subprocess.SubprocessError, OSError) as exc:
        return {
            **source,
            "attempted": True,
            "status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "sample_length": 0,
            "error_type": type(exc).__name__,
            "error_message": sanitize_error(exc, load_morningstar_secret().get("md_auth_token")),
            "automated_universe_parse_status": "not_attempted",
            "crawler_allowed": "needs_terms_review",
        }


def china_fund_company_sample_probe() -> dict[str, Any]:
    results = [source_reachability_probe(source) for source in CHINA_FUND_COMPANY_SITES]
    payload = {
        "generated_at": utc_now(),
        "sample_company_count": len(results),
        "reachable_count": sum(1 for row in results if row["status"] == "reachable"),
        "companies": results,
        "fund_product_sample_status": "manual_import_required",
        "reason": "Home-page reachability is not a legal/stable product-list connector. No captcha/login/paywall bypass attempted.",
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "china_fund_company_sample_probe.json", payload)
    return payload


def europe_official_issuer_feasibility() -> dict[str, Any]:
    results = [source_reachability_probe(source) for source in EUROPE_FEASIBILITY_SOURCES]
    payload = {
        "generated_at": utc_now(),
        "source_count": len(results),
        "reachable_count": sum(1 for row in results if row["status"] == "reachable"),
        "sources": results,
        "official_or_issuer_universe_sample_status": "manual_import_required_or_source_specific_review",
        "reason": "Reachability does not imply crawler permission or schema stability. No automated European universe parse was performed without source-specific terms review.",
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "europe_official_issuer_feasibility.json", payload)
    return payload


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

    amac = amac_total_benchmark()
    company_probe = china_fund_company_sample_probe()
    europe = europe_official_issuer_feasibility()

    regions = [
        {
            "region": "China",
            "status": "amac_total_benchmark_completed" if amac["benchmark_status"] == "completed" else "manual_import_required",
            "official_universe_sample_acquired": False,
            "official_count": amac.get("benchmark", {}).get("total_fund_count") if amac.get("benchmark") else None,
            "sources_attempted": ["AMAC", "SSE", "SZSE", "fund_company_official_sites"],
            "reason": "AMAC aggregate benchmark acquired; individual fund universe still needs official list/manual import.",
            "next_action": "user_download_or_prepare_AMAC_exchange_or_issuer_csv",
            "aggregate_benchmark_status": amac["benchmark_status"],
            "fund_company_sample_status": company_probe["fund_product_sample_status"],
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
            "status": "manual_import_required_or_source_specific_review",
            "official_universe_sample_acquired": False,
            "official_count": None,
            "sources_attempted": ["ESMA/UCITS", "LSE", "Euronext", "Xetra", "issuer_lists"],
            "reason": f"Europe source reachability checked ({europe['reachable_count']}/{europe['source_count']} reachable); no automated universe parse without terms/schema review.",
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
        "amac_total_benchmark_status": amac["benchmark_status"],
        "amac_total_fund_count": amac.get("benchmark", {}).get("total_fund_count") if amac.get("benchmark") else None,
        "china_fund_company_reachable_count": company_probe["reachable_count"],
        "europe_reachable_count": europe["reachable_count"],
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


def morningstar_search_child_code(symbols: list[str]) -> str:
    return f"""
import json
import pandas as pd

def clean(value):
    if pd.isna(value):
        return None
    return str(value)

try:
    import morningstar_data as md
    symbols = {symbols!r}
    results = []
    for symbol in symbols:
        try:
            df = md.direct.investments(keyword=symbol, count=3)
            rows = []
            if hasattr(df, 'iterrows'):
                for _, row in df.head(3).iterrows():
                    rows.append({{
                        'Name': clean(row.get('Name')),
                        'SecId': clean(row.get('SecId')),
                        'Ticker': clean(row.get('Ticker')),
                        'ISIN': clean(row.get('ISIN')),
                        'CUSIP': clean(row.get('CUSIP')),
                        'Base Currency': clean(row.get('Base Currency')),
                        'Exchange': clean(row.get('Exchange')),
                        'Country': clean(row.get('Country')),
                        'Security Type': clean(row.get('Security Type')),
                        'Fund Id': clean(row.get('Fund Id')),
                        'Performance Id': clean(row.get('Performance Id')),
                    }})
            results.append({{
                'symbol': symbol,
                'status': 'success',
                'row_count': int(df.shape[0]) if hasattr(df, 'shape') else 0,
                'columns': [str(c) for c in list(df.columns)] if hasattr(df, 'columns') else [],
                'rows': rows,
            }})
        except Exception as exc:
            results.append({{'symbol': symbol, 'status': 'failed', 'error_type': type(exc).__name__, 'error_message': str(exc)[:500]}})
    print(json.dumps({{'status':'success','results':results}}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({{'status':'failed','error_type':type(exc).__name__,'error_message':str(exc)[:1000]}}, ensure_ascii=False))
    raise SystemExit(2)
"""


def run_morningstar_symbol_search(symbols: list[str], token: str | None) -> dict[str, Any]:
    if not token:
        return {"status": "skipped", "reason": "missing_token", "items": [], "attempted": False}
    started = time.time()
    env = dict(**__import__("os").environ)
    env["MD_AUTH_TOKEN"] = token
    try:
        result = subprocess.run(
            [sys.executable, "-c", morningstar_search_child_code(symbols)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        stdout = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"status": "failed", "error_type": "invalid_child_json", "error_message": stdout[:800]}
        return {
            "status": payload.get("status", "failed"),
            "attempted": True,
            "elapsed_seconds": round(time.time() - started, 3),
            "symbols_requested": symbols,
            "items": payload.get("results", []),
            "error_type": payload.get("error_type"),
            "error_message": sanitize_error(payload.get("error_message", result.stderr[-1000:]), token),
            "stderr_tail": sanitize_error(result.stderr[-1000:], token),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "attempted": True,
            "elapsed_seconds": round(time.time() - started, 3),
            "symbols_requested": symbols,
            "items": [],
            "error_type": "timeout",
            "error_message": "Morningstar symbol search exceeded controlled timeout.",
        }


def morningstar_us_etf_matching_pilot(official: dict[str, Any]) -> dict[str, Any]:
    sample_path = official.get("runtime_sample_path")
    official_rows = read_jsonl(Path(sample_path)) if sample_path else []
    symbols = []
    for row in official_rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker not in symbols:
            symbols.append(ticker)
        if len(symbols) >= 20:
            break
    health = token_health_check()
    token = token_for_library(load_morningstar_secret().get("md_auth_token"))
    search = run_morningstar_symbol_search(symbols, token if health.get("token_status") == "available" else None)
    matches = []
    for item in search.get("items", []):
        symbol = item.get("symbol")
        rows = item.get("rows") or []
        exact = [row for row in rows if (row.get("Ticker") or "").upper() == str(symbol).upper()]
        probable = rows[:1] if rows and not exact else []
        status = "exact_match" if exact else "probable_match" if probable else "no_match"
        selected = exact[0] if exact else probable[0] if probable else None
        matches.append(
            {
                "official_symbol": symbol,
                "match_status": status,
                "morningstar_sec_id": selected.get("SecId") if selected else None,
                "morningstar_name": selected.get("Name") if selected else None,
                "ticker": selected.get("Ticker") if selected else None,
                "isin": selected.get("ISIN") if selected else None,
                "exchange": selected.get("Exchange") if selected else None,
                "country": selected.get("Country") if selected else None,
                "currency": selected.get("Base Currency") if selected else None,
                "security_type": selected.get("Security Type") if selected else None,
                "fields_compared": ["ticker", "name", "isin", "exchange", "country", "currency", "security_type"],
                "field_completeness_score": round(sum(1 for value in (selected or {}).values() if value) / max(len(selected or {}), 1), 3) if selected else 0,
                "freshness_status": "unknown_no_time_series_retrieved",
                "candidate_only": True,
            }
        )
    matched = sum(1 for row in matches if row["match_status"] in {"exact_match", "probable_match"})
    result = {
        "generated_at": utc_now(),
        "official_sample_count": len(official_rows),
        "symbols_tested": len(symbols),
        "search_status": search.get("status"),
        "matched_count": matched,
        "exact_match_count": sum(1 for row in matches if row["match_status"] == "exact_match"),
        "probable_match_count": sum(1 for row in matches if row["match_status"] == "probable_match"),
        "coverage_ratio_on_tested_symbols": round(matched / len(symbols), 4) if symbols else None,
        "matches": matches,
        "raw_storage_enabled": False,
        "raw_storage_reason": "Licensed Morningstar search result stored only as normalized tiny match evidence; no full raw dump.",
        "large_download_performed": False,
        "candidate_only": True,
        "not_coverage_claim": True,
        "limitations": "Ticker search over a controlled subset validates matchability only; it is not a full US ETF universe coverage result.",
    }
    write_json(OUTPUT_ROOT / "us_nasdaq_morningstar_matching_pilot.json", result)
    return result


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
        for proxy_type, field, unit, confidence, level, note in [
            ("amount_proxy", "amount", "CNY", "medium", 1, "Trading amount is market activity, not subscription/redemption flow."),
            ("volume_proxy", "volume", "shares", "medium", 1, "Trading volume is activity/liquidity proxy, not net flow."),
            ("price_momentum_proxy", "pct_change", "percent", "low", 2, "Price movement can reflect valuation and liquidity but not net flow."),
            ("turnover_proxy", "turnover_rate", "percent", "low", 1, "Turnover is a trading intensity proxy."),
        ]:
            value = row.get(field)
            proxies.append(
                {
                    **base,
                    "proxy_type": proxy_type,
                    "proxy_value": value,
                    "unit": unit,
                    "confidence": confidence,
                    "proxy_level": level,
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
        level_map = {
            "aum_change_proxy": 3,
            "shares_outstanding_change_proxy": 4,
            "holdings_change_proxy": 5,
            "sector_exposure_change_proxy": 5,
            "country_exposure_change_proxy": 5,
            "currency_exposure_change_proxy": 5,
            "estimated_net_flow": 6,
        }
        unavailable.append(
            {
                "proxy_type": proxy_type,
                "proxy_level": level_map[proxy_type],
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
        "proxy_level_counts": dict(Counter(row["proxy_level"] for row in proxies)),
        "source_record_count": len(phase2_records),
        "items": proxies,
        "unavailable_proxy_types": unavailable,
        "actual_flow_available": False,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "flow_proxy_v3_results.json", result)
    return result


def coverage_validation_phase3(official: dict[str, Any], tiny: dict[str, Any], us_match: dict[str, Any]) -> dict[str, Any]:
    regions = []
    official_by_region = {row["region"]: row for row in official.get("regions", [])}
    for region in ["US", "China", "Europe"]:
        source = official_by_region.get(region, {})
        official_count = source.get("official_count")
        if region == "US" and source.get("official_universe_sample_acquired"):
            validation_status = "sample_matchability_validated" if us_match.get("matched_count") else "official_universe_sample_acquired_morningstar_match_pending"
            blockers = ["freshness_unknown", "field_completeness_partial", "license_boundary_unclear", "full_universe_coverage_not_validated"]
            coverage_ratio = us_match.get("coverage_ratio_on_tested_symbols")
            matched_count = us_match.get("matched_count", 0)
        else:
            validation_status = "blocked"
            blockers = ["official_universe_missing", "manual_import_required", "freshness_unknown", "field_completeness_unknown"]
            coverage_ratio = None
            matched_count = 0
        regions.append(
            {
                "region": region,
                "official_count": official_count,
                "morningstar_candidate_count": None,
                "matched_count": matched_count,
                "unmatched_official_count": official_count if official_count else None,
                "unmatched_morningstar_count": None,
                "coverage_ratio": coverage_ratio,
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
        "us_matching_pilot": {
            "symbols_tested": us_match.get("symbols_tested", 0),
            "matched_count": us_match.get("matched_count", 0),
            "coverage_ratio_on_tested_symbols": us_match.get("coverage_ratio_on_tested_symbols"),
        },
        "coverage_inference_from_metadata": False,
        "candidate_only": True,
    }
    write_json(OUTPUT_ROOT / "coverage_validation_phase3.json", result)
    return result


def trust_upgrade_queue_phase3(classification: dict[str, Any], coverage: dict[str, Any], tiny: dict[str, Any], us_match: dict[str, Any]) -> dict[str, Any]:
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
        current_status = "licensed_source_candidate"
        if item.get("likely_data_type") in {"fund_etf", "equity_stock_or_company_fundamental"} and tiny_item.get("usable_for_fr"):
            current_status = "sample_validated_candidate"
            blockers = [
                "freshness_unknown",
                "field_completeness_partial",
                "license_storage_boundary_unclear",
                "full_universe_coverage_not_validated",
                "cross_source_validation_incomplete",
            ]
        queue.append(
            {
                "dataset_id": item.get("dataset_id"),
                "dataset_name": item.get("dataset_name"),
                "likely_data_type": item.get("likely_data_type"),
                "current_status": current_status,
                "required_checks": ["entitlement", "tiny_sample", "coverage", "field_completeness", "freshness", "cross_source", "license_boundary", "QA"],
                "completed_checks": completed,
                "blockers": blockers,
                "next_action": "larger but controlled official-universe matching plus freshness/field validation" if current_status == "sample_validated_candidate" else "identify callable sample method or keep metadata-only",
                "can_upgrade_to_trusted_candidate": False,
            }
        )
    result = {
        "generated_at": utc_now(),
        "queue": queue,
        "trusted_candidate_count": 0,
        "sample_validated_candidate_count": sum(1 for row in queue if row["current_status"] == "sample_validated_candidate"),
        "us_matching_pilot_coverage_ratio": us_match.get("coverage_ratio_on_tested_symbols"),
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
    text += "\n## Import command\n\n"
    text += "`D:\\workspace\\envs\\financial_research_backend\\Scripts\\python.exe scripts\\run_fund_etf_manual_import.py validate --input <csv> --template <template>`\n\n"
    text += "After import, the system will run field validation, duplicate checks, Morningstar matching, freshness checks, and trust-upgrade queue refresh. Imported files remain candidate until validation passes.\n"
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
- AMAC total benchmark completed: {summary['amac_total_benchmark_completed']} (fund count: {summary.get('amac_total_fund_count')})
- US Nasdaq x Morningstar symbols tested: {summary.get('us_nasdaq_morningstar_symbols_tested')} / matched: {summary.get('us_nasdaq_morningstar_matched_count')}
- Morningstar tiny-sample usable dataset count: {summary['morningstar_tiny_sample_dataset_count']}
- Coverage validation regions: {', '.join(summary['coverage_regions'])}
- Trusted candidate count: {summary['trusted_candidate_count']}
 - Sample validated candidate count: {summary.get('sample_validated_candidate_count')}

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
            "amac_total_benchmark_completed": summary["amac_total_benchmark_completed"],
            "amac_total_fund_count": summary["amac_total_fund_count"],
            "us_nasdaq_morningstar_matched_count": summary["us_nasdaq_morningstar_matched_count"],
            "us_nasdaq_morningstar_match_ratio": summary["us_nasdaq_morningstar_match_ratio"],
            "morningstar_tiny_sample_dataset_count": summary["morningstar_tiny_sample_dataset_count"],
            "trusted_candidate_count": summary["trusted_candidate_count"],
            "sample_validated_candidate_count": summary["sample_validated_candidate_count"],
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
    us_match: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "generated_at": utc_now(),
        "phase3_completed": True,
        "official_universe_sample_records": official.get("sample_record_count", 0),
        "official_universe_regions": {row["region"]: row["status"] for row in official.get("regions", [])},
        "amac_total_benchmark_completed": official.get("amac_total_benchmark_status") == "completed",
        "amac_total_fund_count": official.get("amac_total_fund_count"),
        "china_fund_company_sample_status": "manual_import_required",
        "china_fund_company_reachable_count": official.get("china_fund_company_reachable_count", 0),
        "europe_source_reachable_count": official.get("europe_reachable_count", 0),
        "us_nasdaq_morningstar_symbols_tested": us_match.get("symbols_tested", 0),
        "us_nasdaq_morningstar_matched_count": us_match.get("matched_count", 0),
        "us_nasdaq_morningstar_match_ratio": us_match.get("coverage_ratio_on_tested_symbols"),
        "morningstar_tiny_sample_dataset_count": tiny.get("tiny_sample_dataset_count", 0),
        "morningstar_equity_market_status": {row["market"]: row["coverage_status"] for row in equity.get("markets", [])},
        "flow_proxy_v3_count": proxy.get("proxy_count", 0),
        "coverage_regions": [row["region"] for row in coverage.get("regions", [])],
        "trust_upgrade_queue_count": len(trust.get("queue", [])),
        "trusted_candidate_count": trust.get("trusted_candidate_count", 0),
        "sample_validated_candidate_count": trust.get("sample_validated_candidate_count", 0),
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
            "amac_total_benchmark": str(OUTPUT_ROOT / "amac_total_benchmark_result.json"),
            "china_fund_company_probe": str(OUTPUT_ROOT / "china_fund_company_sample_probe.json"),
            "europe_feasibility": str(OUTPUT_ROOT / "europe_official_issuer_feasibility.json"),
            "us_nasdaq_morningstar_matching": str(OUTPUT_ROOT / "us_nasdaq_morningstar_matching_pilot.json"),
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
    us_match = morningstar_us_etf_matching_pilot(official)
    tiny = tiny_sample_validation(classification)
    equity = equity_stock_validation_phase3(tiny, classification)
    proxy = flow_proxy_v3()
    coverage = coverage_validation_phase3(official, tiny, us_match)
    trust = trust_upgrade_queue_phase3(classification, coverage, tiny, us_match)
    actions = user_action_package()
    summary = write_summary(official, tiny, equity, proxy, coverage, trust, actions, us_match)
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
