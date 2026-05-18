from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[5]
REGISTRY_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "data_connector_feasibility"
CONNECTOR_SMOKE_TIMEOUT_SECONDS = 15


@dataclass
class SourceRegistryEntry:
    source_id: str
    source_name: str
    category: str
    official_source: bool
    provider_type: str
    free_level: str
    requires_account: bool
    requires_api_key: bool
    requires_points_or_paid_quota: bool
    terms_risk: str
    update_frequency: str
    data_frequency: str
    coverage: str
    status: str
    connector_module: str
    raw_storage_policy: str
    normalized_schema: str
    trusted_external_eligible: bool
    data_quality_checks: list[str] = field(default_factory=list)
    consumption_eligibility: str = "quality_gate_required"
    source_url: str = ""
    notes: str = ""


def build_source_registry(output_dir: Path | str = REGISTRY_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = [_entry_dict(entry) for entry in _registry_entries()]
    payload = {
        "generated_at": _utc_now(),
        "registry_version": "fr_data_foundation_phase1",
        "source_count": len(entries),
        "official_source_only_policy": (
            "trusted_by_real_external requires official institutions, official exchanges, "
            "official authorized APIs, or open-source wrappers with traceable official upstream data."
        ),
        "not_trusted_sources": ["media_repost", "forums", "wechat_public_accounts", "second_hand_commentary"],
        "entries": entries,
    }
    _write_json(output_dir / "source_registry.json", payload)
    return payload


def run_connector_smoke_tests(output_dir: Path | str = REGISTRY_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tests = [
        _smoke_fred_csv("fred_dgs10", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", "macro"),
        _smoke_fred_csv("fred_wti_oil", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO", "commodity"),
        _smoke_treasury_fiscaldata(),
        _smoke_bls_cpi(),
        _smoke_sec_companyfacts(),
        _smoke_python_package("baostock", "a_share_daily_price"),
        _smoke_python_package("akshare", "a_share_daily_price"),
        _smoke_cninfo_query(output_dir),
        _smoke_world_bank_pink_sheet_page(),
        _smoke_world_bank_file(
            "world_bank_pink_sheet_monthly_xlsx",
            "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx",
        ),
        _smoke_world_bank_file(
            "world_bank_pink_sheet_annual_xlsx",
            "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Annual.xlsx",
        ),
    ]
    success = [item for item in tests if item["status"] == "success"]
    failed = [item for item in tests if item["status"] == "failed"]
    skipped = [item for item in tests if item["status"] == "skipped"]
    payload = {
        "generated_at": _utc_now(),
        "smoke_scope": "small_sample_only_no_full_download",
        "test_count": len(tests),
        "success_count": len(success),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "tests": tests,
        "no_openai_api_called": True,
        "no_paid_source_used": True,
        "no_full_crawler_started": True,
    }
    _write_json(output_dir / "connector_smoke_results.json", payload)
    return payload


def build_storage_estimate() -> dict[str, Any]:
    return {
        "generated_at": _utc_now(),
        "estimates": {
            "a_share_daily_10y": {
                "rows": "about 12-16 million rows for all A-share symbols",
                "parquet_gb": "2-8 GB depending on fields/compression",
                "sqlite_duckdb_gb": "5-20 GB with indexes",
            },
            "macro_30y": {
                "rows": "usually below a few million rows for selected series",
                "parquet_gb": "<1 GB for curated series",
            },
            "asset_class_30y": {
                "rows": "daily/monthly selected commodities/rates/FX/indexes",
                "parquet_gb": "1-5 GB for curated coverage",
            },
            "financial_report_pdfs": {
                "a_share_10y": "hundreds of GB if all PDFs are retained",
                "targeted_company_set": "tens of GB",
            },
            "parser_raw_output": {
                "html_json_images_tables": "can exceed PDF size; keep hot subset and archive cold outputs",
            },
        },
        "hot_storage_2tb_desktop": "enough for curated equities, macro, commodities, sample PDFs, and active parser outputs",
        "cold_storage_8tb_nas": "enough for broader PDF/archive retention if deduplicated and compressed",
        "retention_policy": {
            "keep_forever": ["source metadata", "checksums", "normalized parquet", "quality/trust decisions", "analysis packets/reports"],
            "hot_cache": ["recent raw API responses", "active parser raw outputs", "review packs"],
            "cold_archive": ["PDF originals", "large parser raw output bundles"],
            "do_not_keep_long_term_by_default": ["duplicated HTML mirrors", "temporary page images", "failed partial downloads"],
        },
    }


def build_data_foundation_phase1_outputs(output_dir: Path | str = REGISTRY_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = Path(output_dir)
    registry = build_source_registry(output_dir)
    smoke = run_connector_smoke_tests(output_dir)
    storage = build_storage_estimate()
    _write_json(output_dir / "storage_estimate.json", storage)
    summary = {
        "generated_at": _utc_now(),
        "registry_path": str(output_dir / "source_registry.json"),
        "smoke_results_path": str(output_dir / "connector_smoke_results.json"),
        "storage_estimate_path": str(output_dir / "storage_estimate.json"),
        "source_count": registry["source_count"],
        "smoke_success_count": smoke["success_count"],
        "smoke_failed_count": smoke["failed_count"],
        "smoke_skipped_count": smoke["skipped_count"],
    }
    _write_json(output_dir / "data_connector_feasibility_summary.json", summary)
    return {"registry": registry, "smoke": smoke, "storage": storage, "summary": summary}


def _registry_entries() -> list[SourceRegistryEntry]:
    checks = [
        "numeric_format_ok",
        "date_format_ok",
        "missing_value_check",
        "duplicate_check",
        "unit_currency_check",
        "range_check",
        "time_series_continuity_check",
        "field_mapping_ok",
        "source_url_retrieved_at_checksum",
    ]
    return [
        SourceRegistryEntry(
            source_id="sse_official_disclosure",
            source_name="Shanghai Stock Exchange disclosures",
            category="a_share_financial_report_pdf",
            official_source=True,
            provider_type="official_exchange",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="medium",
            update_frequency="event_driven",
            data_frequency="filing",
            coverage="Shanghai-listed company announcements and reports",
            status="audit_first_connector_later",
            connector_module="future.sse_disclosure_connector",
            raw_storage_policy="store_pdf_original_and_metadata_checksum",
            normalized_schema="financial_report_document",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://www.sse.com.cn/disclosure/listedinfo/announcement/",
        ),
        SourceRegistryEntry(
            source_id="szse_official_disclosure",
            source_name="Shenzhen Stock Exchange disclosures",
            category="a_share_financial_report_pdf",
            official_source=True,
            provider_type="official_exchange",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="medium",
            update_frequency="event_driven",
            data_frequency="filing",
            coverage="Shenzhen-listed company announcements and reports",
            status="audit_first_connector_later",
            connector_module="future.szse_disclosure_connector",
            raw_storage_policy="store_pdf_original_and_metadata_checksum",
            normalized_schema="financial_report_document",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://www.szse.cn/disclosure/listed/notice/",
        ),
        SourceRegistryEntry(
            source_id="cninfo_disclosure",
            source_name="CNINFO disclosures",
            category="a_share_financial_report_pdf",
            official_source=False,
            provider_type="exchange_designated_disclosure_platform",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="medium",
            update_frequency="event_driven",
            data_frequency="filing",
            coverage="A-share announcements and annual/interim reports",
            status="candidate_connector_small_smoke_only",
            connector_module="future.cninfo_disclosure_connector",
            raw_storage_policy="store_pdf_original_metadata_and_query_response",
            normalized_schema="financial_report_document",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="http://www.cninfo.com.cn/new/index",
            notes="Eligible only when original announcement URL and checksum are preserved.",
        ),
        SourceRegistryEntry(
            source_id="sec_edgar_companyfacts",
            source_name="SEC EDGAR companyfacts",
            category="us_filing_fundamentals",
            official_source=True,
            provider_type="official_regulator_api",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="low",
            update_frequency="filing_driven",
            data_frequency="quarterly_annual",
            coverage="US public company XBRL facts",
            status="ready_for_connector",
            connector_module="future.sec_companyfacts_connector",
            raw_storage_policy="store_raw_json_with_checksum",
            normalized_schema="fundamental_fact_timeseries",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        ),
        SourceRegistryEntry(
            source_id="baostock_daily",
            source_name="Baostock daily A-share prices",
            category="a_share_daily_price",
            official_source=False,
            provider_type="open_source_data_interface",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="medium",
            update_frequency="daily",
            data_frequency="daily",
            coverage="A-share daily OHLCV and factors",
            status="install_then_test",
            connector_module="future.baostock_daily_price_connector",
            raw_storage_policy="store_raw_csv_response_and_query_params",
            normalized_schema="daily_price_bar",
            trusted_external_eligible=False,
            data_quality_checks=checks,
            source_url="http://baostock.com/",
            notes="Candidate until upstream provenance and terms are documented per dataset.",
        ),
        SourceRegistryEntry(
            source_id="akshare_traceable_official",
            source_name="AKShare traceable official interfaces",
            category="multi_asset_data",
            official_source=False,
            provider_type="open_source_wrapper",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="medium",
            update_frequency="varies",
            data_frequency="varies",
            coverage="A-share, macro, funds, futures and more",
            status="use_only_traceable_official_upstreams",
            connector_module="future.akshare_connector",
            raw_storage_policy="store_raw_response_query_params_upstream_url_checksum",
            normalized_schema="source_specific",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://akshare.akfamily.xyz/",
            notes="Only datasets traceable to official/exchange upstream are trusted eligible.",
        ),
        SourceRegistryEntry(
            source_id="fred_public_csv",
            source_name="FRED public CSV",
            category="macro_data",
            official_source=True,
            provider_type="official_public_data_portal",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="low",
            update_frequency="varies",
            data_frequency="daily_monthly_quarterly",
            coverage="US macro, rates, commodities via FRED series",
            status="ready_for_connector",
            connector_module="future.fred_csv_connector",
            raw_storage_policy="store_raw_csv_and_series_metadata",
            normalized_schema="macro_timeseries",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://fred.stlouisfed.org/",
        ),
        SourceRegistryEntry(
            source_id="bls_public_api",
            source_name="BLS public data API",
            category="macro_data",
            official_source=True,
            provider_type="official_public_api",
            free_level="free_public_limited",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="low",
            update_frequency="scheduled",
            data_frequency="monthly",
            coverage="US labor and CPI series",
            status="ready_for_small_connector",
            connector_module="future.bls_public_api_connector",
            raw_storage_policy="store_raw_json_and_query",
            normalized_schema="macro_timeseries",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://www.bls.gov/developers/",
        ),
        SourceRegistryEntry(
            source_id="treasury_fiscaldata",
            source_name="U.S. Treasury FiscalData API",
            category="macro_fiscal_data",
            official_source=True,
            provider_type="official_public_api",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="low",
            update_frequency="daily_monthly",
            data_frequency="daily_monthly",
            coverage="US Treasury fiscal datasets",
            status="ready_for_connector",
            connector_module="future.treasury_fiscaldata_connector",
            raw_storage_policy="store_raw_json_and_query",
            normalized_schema="macro_timeseries",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://fiscaldata.treasury.gov/api-documentation/",
        ),
        SourceRegistryEntry(
            source_id="world_bank_pink_sheet",
            source_name="World Bank Pink Sheet commodity prices",
            category="commodity_data",
            official_source=True,
            provider_type="official_public_dataset",
            free_level="free_public",
            requires_account=False,
            requires_api_key=False,
            requires_points_or_paid_quota=False,
            terms_risk="low",
            update_frequency="monthly",
            data_frequency="monthly",
            coverage="Commodity prices",
            status="ready_for_connector",
            connector_module="future.world_bank_pink_sheet_connector",
            raw_storage_policy="store_raw_xlsx_csv_and_checksum",
            normalized_schema="commodity_timeseries",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://www.worldbank.org/en/research/commodity-markets",
        ),
        SourceRegistryEntry(
            source_id="eia_open_data",
            source_name="EIA Open Data",
            category="energy_data",
            official_source=True,
            provider_type="official_public_api",
            free_level="free_public_with_key_policy_check",
            requires_account=False,
            requires_api_key=True,
            requires_points_or_paid_quota=False,
            terms_risk="low",
            update_frequency="varies",
            data_frequency="daily_weekly_monthly",
            coverage="US and global energy statistics",
            status="defer_if_api_key_required",
            connector_module="future.eia_connector",
            raw_storage_policy="store_raw_json_query_and_series_metadata",
            normalized_schema="energy_timeseries",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://www.eia.gov/opendata/",
            notes="Do not block Phase 1 on API key setup.",
        ),
        SourceRegistryEntry(
            source_id="wind_terminal",
            source_name="Wind",
            category="commercial_financial_data",
            official_source=False,
            provider_type="authorized_commercial_provider",
            free_level="paid_or_institutional",
            requires_account=True,
            requires_api_key=True,
            requires_points_or_paid_quota=True,
            terms_risk="medium",
            update_frequency="varies",
            data_frequency="varies",
            coverage="Broad China and global financial data",
            status="defer_paid_source",
            connector_module="future.wind_connector",
            raw_storage_policy="store_raw_response_subject_to_license",
            normalized_schema="source_specific",
            trusted_external_eligible=True,
            data_quality_checks=checks,
            source_url="https://www.wind.com.cn/",
            notes="Trusted eligible only under valid license; not Phase 1 mainline.",
        ),
    ]


def _entry_dict(entry: SourceRegistryEntry) -> dict[str, Any]:
    return {
        "source_id": entry.source_id,
        "source_name": entry.source_name,
        "category": entry.category,
        "official_source": entry.official_source,
        "provider_type": entry.provider_type,
        "free_level": entry.free_level,
        "requires_account": entry.requires_account,
        "requires_api_key": entry.requires_api_key,
        "requires_points_or_paid_quota": entry.requires_points_or_paid_quota,
        "terms_risk": entry.terms_risk,
        "update_frequency": entry.update_frequency,
        "data_frequency": entry.data_frequency,
        "coverage": entry.coverage,
        "status": entry.status,
        "connector_module": entry.connector_module,
        "raw_storage_policy": entry.raw_storage_policy,
        "normalized_schema": entry.normalized_schema,
        "trusted_external_eligible": entry.trusted_external_eligible,
        "data_quality_checks": entry.data_quality_checks,
        "consumption_eligibility": entry.consumption_eligibility,
        "source_url": entry.source_url,
        "notes": entry.notes,
    }


def _smoke_fred_csv(test_id: str, url: str, category: str) -> dict[str, Any]:
    started = time.time()
    try:
        body = _http_get(url)
        rows = list(csv.reader(body.decode("utf-8", errors="replace").splitlines()))
        data_rows = [row for row in rows[1:] if len(row) >= 2 and row[1] not in {"", "."}]
        return _smoke_result(test_id, "success", category, url, started, row_count=len(data_rows), checksum=_sha256(body))
    except Exception as exc:
        return _smoke_result(test_id, "failed", category, url, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _smoke_treasury_fiscaldata() -> dict[str, Any]:
    url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?sort=-record_date&page[size]=5"
    started = time.time()
    try:
        data = json.loads(_http_get(url).decode("utf-8"))
        row_count = len(data.get("data", []))
        return _smoke_result("treasury_fiscaldata", "success", "macro_fiscal_data", url, started, row_count=row_count)
    except Exception as exc:
        return _smoke_result("treasury_fiscaldata", "failed", "macro_fiscal_data", url, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _smoke_bls_cpi() -> dict[str, Any]:
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0"
    started = time.time()
    try:
        data = json.loads(_http_get(url).decode("utf-8"))
        series = data.get("Results", {}).get("series", [])
        row_count = sum(len(item.get("data", [])) for item in series)
        status = "success" if row_count else "failed"
        return _smoke_result("bls_cpi_public", status, "macro_data", url, started, row_count=row_count, failure_mode="" if row_count else "empty_series")
    except Exception as exc:
        return _smoke_result("bls_cpi_public", "failed", "macro_data", url, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _smoke_sec_companyfacts() -> dict[str, Any]:
    url = "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Revenues.json"
    started = time.time()
    try:
        body = _http_get(url, headers={"User-Agent": "FinancialResearch local feasibility audit contact@example.com"})
        data = json.loads(body.decode("utf-8"))
        units = data.get("units", {})
        row_count = sum(len(values) for values in units.values())
        return _smoke_result("sec_companyfacts_aapl", "success", "us_filing_fundamentals", url, started, row_count=row_count, checksum=_sha256(body))
    except Exception as exc:
        return _smoke_result("sec_companyfacts_aapl", "failed", "us_filing_fundamentals", url, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _smoke_python_package(package_name: str, category: str) -> dict[str, Any]:
    started = time.time()
    available = importlib.util.find_spec(package_name) is not None
    if not available:
        return _smoke_result(
            f"{package_name}_import",
            "skipped",
            category,
            package_name,
            started,
            failure_mode="optional_package_not_installed",
        )
    try:
        __import__(package_name)
        return _smoke_result(f"{package_name}_import", "success", category, package_name, started, row_count=0)
    except Exception as exc:
        return _smoke_result(f"{package_name}_import", "failed", category, package_name, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _smoke_cninfo_query(output_dir: Path) -> dict[str, Any]:
    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    started = time.time()
    data = urllib.parse.urlencode(
        {
            "stock": "000001,gssz0000001",
            "tabName": "fulltext",
            "pageSize": "5",
            "pageNum": "1",
            "column": "szse",
            "category": "category_ndbg_szsh",
            "plate": "sz",
            "seDate": "2024-01-01~2026-05-18",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
    ).encode("utf-8")
    try:
        body = _http_post(url, data, headers={"Referer": "http://www.cninfo.com.cn/new/index"})
        payload = json.loads(body.decode("utf-8", errors="replace"))
        announcements = payload.get("announcements") or []
        if announcements:
            _write_json(output_dir / "cninfo_discovery_smoke_sample.json", {"announcements": announcements[:2]})
        return _smoke_result("cninfo_annual_report_discovery", "success" if announcements else "failed", "a_share_financial_report_pdf", url, started, row_count=len(announcements), failure_mode="" if announcements else "empty_announcements")
    except Exception as exc:
        return _smoke_result("cninfo_annual_report_discovery", "failed", "a_share_financial_report_pdf", url, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _smoke_world_bank_pink_sheet_page() -> dict[str, Any]:
    url = "https://www.worldbank.org/en/research/commodity-markets"
    started = time.time()
    try:
        body = _http_get(url)
        ok = b"Commodity" in body or b"Pink Sheet" in body
        return _smoke_result("world_bank_pink_sheet_page", "success" if ok else "failed", "commodity_data", url, started, row_count=1 if ok else 0, checksum=_sha256(body[:65536]), failure_mode="" if ok else "marker_text_missing")
    except Exception as exc:
        return _smoke_result("world_bank_pink_sheet_page", "failed", "commodity_data", url, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _smoke_world_bank_file(test_id: str, url: str) -> dict[str, Any]:
    started = time.time()
    try:
        body = _http_get(url, headers={"User-Agent": "FinancialResearch local data audit", "Range": "bytes=0-199999"})
        ok = body.startswith(b"PK") or len(body) > 10000
        return _smoke_result(
            test_id,
            "success" if ok else "failed",
            "commodity_data",
            url,
            started,
            row_count=1 if ok else 0,
            checksum=_sha256(body),
            failure_mode="" if ok else "file_probe_too_small",
        )
    except Exception as exc:
        return _smoke_result(test_id, "failed", "commodity_data", url, started, failure_mode=type(exc).__name__, error=str(exc)[:300])


def _http_get(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "FinancialResearch local data audit"})
    with urllib.request.urlopen(request, timeout=CONNECTOR_SMOKE_TIMEOUT_SECONDS) as response:
        return response.read(2_000_000)


def _http_post(url: str, data: bytes, headers: dict[str, str] | None = None) -> bytes:
    merged_headers = {
        "User-Agent": "FinancialResearch local data audit",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    merged_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=merged_headers, method="POST")
    with urllib.request.urlopen(request, timeout=CONNECTOR_SMOKE_TIMEOUT_SECONDS) as response:
        return response.read(2_000_000)


def _smoke_result(
    test_id: str,
    status: str,
    category: str,
    source_reference: str,
    started: float,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "status": status,
        "category": category,
        "source_reference": source_reference,
        "elapsed_seconds": round(time.time() - started, 3),
        "candidate_only": True,
        "trusted_consumption_affected": False,
        **extra,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
