from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[5]
STORAGE_CONFIG_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
SOURCE_REGISTRY_PATH = PROJECT_ROOT / "runtime" / "data_connector_feasibility" / "source_registry.json"
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "data_connector_phase2"
METADATA_DB_PATH = OUTPUT_ROOT / "connector_phase2_metadata.sqlite"

CONNECTOR_SOURCE_BY_FUNCTION = {
    "run_akshare_a_share_daily": "akshare_traceable_official",
    "run_baostock_a_share_daily": "baostock_daily",
    "run_cninfo_discovery": "cninfo_disclosure",
    "run_bls_cpi": "bls_public_api",
    "run_treasury_debt_to_penny": "treasury_fiscaldata",
    "run_sec_companyconcept_revenue": "sec_edgar_companyfacts",
    "run_world_bank_pink_sheet": "world_bank_pink_sheet",
    "run_fred_probe": "fred_public_csv",
}


@dataclass
class ConnectorContext:
    storage_paths: dict[str, str]
    source_registry: dict[str, dict[str, Any]]

    @property
    def raw_api_root(self) -> Path:
        return Path(self.storage_paths["raw_api_response_root"])

    @property
    def normalized_root(self) -> Path:
        return Path(self.storage_paths["normalized_data_root"])

    @property
    def normalized_cold_root(self) -> Path:
        return Path(self.storage_paths["normalized_cold_root"])

    @property
    def financial_report_pdf_root(self) -> Path:
        return Path(self.storage_paths["financial_report_pdf_root"])


def run_data_connector_phase2(output_root: Path | str = OUTPUT_ROOT) -> dict[str, Any]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    context = load_context()
    ensure_output_dirs(context, output_root)
    init_metadata_db(METADATA_DB_PATH)
    index_source_registry(METADATA_DB_PATH, context)

    connector_fns: list[Callable[[ConnectorContext], dict[str, Any]]] = [
        run_akshare_a_share_daily,
        run_baostock_a_share_daily,
        run_cninfo_discovery,
        run_bls_cpi,
        run_treasury_debt_to_penny,
        run_sec_companyconcept_revenue,
        run_world_bank_pink_sheet,
        run_fred_probe,
    ]
    results = [run_guarded(fn, context) for fn in connector_fns]
    quality_results = [result["quality_result"] for result in results if result.get("quality_result")]
    trust_results = [result["trust_resolution"] for result in results if result.get("trust_resolution")]
    storage_estimate = build_storage_estimate_refresh(results)

    connector_run_results = {
        "generated_at": utc_now(),
        "connector_count": len(results),
        "success_count": sum(1 for item in results if item["status"] == "success"),
        "failed_count": sum(1 for item in results if item["status"] == "failed"),
        "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
        "no_full_download": True,
        "no_openai_api_called": True,
        "paid_source_used": False,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "default_v1_1_replaced": False,
        "items": results,
    }
    write_json(output_root / "connector_run_results.json", connector_run_results)
    write_json(output_root / "quality_check_results.json", {"generated_at": utc_now(), "items": quality_results})
    write_json(output_root / "trust_resolution_results.json", {"generated_at": utc_now(), "items": trust_results})
    write_json(output_root / "storage_estimate_refresh.json", storage_estimate)
    return {
        "connector_run_results": connector_run_results,
        "quality_check_results": quality_results,
        "trust_resolution_results": trust_results,
        "storage_estimate_refresh": storage_estimate,
    }


def load_context() -> ConnectorContext:
    storage = read_json(STORAGE_CONFIG_PATH)
    registry_payload = read_json(SOURCE_REGISTRY_PATH)
    registry = {entry["source_id"]: entry for entry in registry_payload.get("entries", [])}
    return ConnectorContext(storage_paths=storage["paths"], source_registry=registry)


def run_guarded(fn: Callable[[ConnectorContext], dict[str, Any]], context: ConnectorContext) -> dict[str, Any]:
    started = time.time()
    try:
        result = fn(context)
        result.setdefault("elapsed_seconds", round(time.time() - started, 3))
        log_connector_run(METADATA_DB_PATH, result)
        return result
    except Exception as exc:
        source_id = CONNECTOR_SOURCE_BY_FUNCTION.get(fn.__name__, "unknown")
        result = connector_result(
            context=context,
            source_id=source_id,
            connector_name=fn.__name__,
            status="failed",
            records=[],
            raw_output_path="",
            normalized_output_path="",
            quality_result=quality_result("failed", [], ["connector_exception"], {}, data_type="unknown"),
            error_message=f"{type(exc).__name__}: {str(exc)[:500]}",
        )
        result["elapsed_seconds"] = round(time.time() - started, 3)
        log_connector_run(METADATA_DB_PATH, result)
        return result


def run_akshare_a_share_daily(context: ConnectorContext) -> dict[str, Any]:
    import akshare as ak

    source_id = "akshare_traceable_official"
    end = date.today()
    start = end - timedelta(days=70)
    df = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), adjust="")
    df = df.tail(30)
    raw_bytes = df.to_csv(index=False).encode("utf-8-sig")
    raw_path, checksum = save_raw(context, source_id, "akshare_000001_daily_30d.csv", raw_bytes)
    records = []
    for _, row in df.iterrows():
        records.append(
            {
                "date": str(row.get("日期", "")),
                "symbol": "000001.SZ",
                "open": to_float(row.get("开盘")),
                "high": to_float(row.get("最高")),
                "low": to_float(row.get("最低")),
                "close": to_float(row.get("收盘")),
                "volume": to_float(row.get("成交量")),
                "source_id": source_id,
                "retrieved_at": utc_now(),
                "checksum": checksum,
            }
        )
    return finish_connector(context, source_id, "akshare_a_share_daily_000001", records, raw_path, checksum, data_type="daily_price", source_url="akshare.stock_zh_a_hist:000001")


def run_baostock_a_share_daily(context: ConnectorContext) -> dict[str, Any]:
    import baostock as bs

    source_id = "baostock_daily"
    end = date.today()
    start = end - timedelta(days=70)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            "sh.600000",
            "date,code,open,high,low,close,volume,amount",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="3",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(dict(zip(rs.fields, rs.get_row_data())))
        rows = rows[-30:]
    finally:
        bs.logout()
    raw_bytes = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    raw_path, checksum = save_raw(context, source_id, "baostock_sh600000_daily_30d.json", raw_bytes)
    records = [
        {
            "date": row.get("date", ""),
            "symbol": row.get("code", "sh.600000"),
            "open": to_float(row.get("open")),
            "high": to_float(row.get("high")),
            "low": to_float(row.get("low")),
            "close": to_float(row.get("close")),
            "volume": to_float(row.get("volume")),
            "amount": to_float(row.get("amount")),
            "source_id": source_id,
            "retrieved_at": utc_now(),
            "checksum": checksum,
        }
        for row in rows
    ]
    return finish_connector(context, source_id, "baostock_a_share_daily_sh600000", records, raw_path, checksum, data_type="daily_price", source_url="baostock.query_history_k_data_plus:sh.600000")


def run_cninfo_discovery(context: ConnectorContext) -> dict[str, Any]:
    source_id = "cninfo_disclosure"
    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
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
    raw = http_post(url, data, headers={"Referer": "http://www.cninfo.com.cn/new/index"})
    raw_path, checksum = save_raw(context, source_id, "cninfo_000001_annual_report_discovery.json", raw)
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    announcements = (payload.get("announcements") or [])[:2]
    records = []
    for item in announcements:
        adjunct = item.get("adjunctUrl") or ""
        download_url = f"http://static.cninfo.com.cn/{adjunct}" if adjunct and not adjunct.startswith("http") else adjunct
        pdf_path = ""
        if download_url and len(records) == 0:
            pdf_path = download_pdf_smoke(context, download_url, item.get("announcementTitle") or "cninfo_report.pdf")
        records.append(
            {
                "date": item.get("announcementTime", ""),
                "symbol": item.get("secCode", "000001"),
                "report_title": item.get("announcementTitle", ""),
                "download_url": download_url,
                "pdf_path": pdf_path,
                "source_id": source_id,
                "retrieved_at": utc_now(),
                "checksum": checksum,
            }
        )
    return finish_connector(context, source_id, "cninfo_financial_report_discovery_000001", records, raw_path, checksum, data_type="report_discovery", source_url=url)


def run_bls_cpi(context: ConnectorContext) -> dict[str, Any]:
    source_id = "bls_public_api"
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0"
    raw = http_get(url)
    raw_path, checksum = save_raw(context, source_id, "bls_cpi_cuur0000sa0.json", raw)
    payload = json.loads(raw.decode("utf-8"))
    series = payload.get("Results", {}).get("series", [])
    records = []
    for item in series:
        for row in item.get("data", [])[:24]:
            records.append(
                {
                    "date": f"{row.get('year')}-{period_to_month(row.get('period'))}-01",
                    "series_id": item.get("seriesID", "CUUR0000SA0"),
                    "metric_name": "cpi_all_urban_consumers",
                    "value": to_float(row.get("value")),
                    "unit": "index",
                    "source_id": source_id,
                    "retrieved_at": utc_now(),
                    "checksum": checksum,
                }
            )
    return finish_connector(context, source_id, "bls_cpi_public_api", records, raw_path, checksum, data_type="macro_timeseries", source_url=url)


def run_treasury_debt_to_penny(context: ConnectorContext) -> dict[str, Any]:
    source_id = "treasury_fiscaldata"
    url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?sort=-record_date&page[size]=10"
    raw = http_get(url)
    raw_path, checksum = save_raw(context, source_id, "treasury_debt_to_penny_latest.json", raw)
    payload = json.loads(raw.decode("utf-8"))
    records = [
        {
            "date": row.get("record_date", ""),
            "metric_name": "us_debt_held_by_public",
            "value": to_float(row.get("debt_held_public_amt")),
            "unit": "USD",
            "currency": "USD",
            "source_id": source_id,
            "retrieved_at": utc_now(),
            "checksum": checksum,
        }
        for row in payload.get("data", [])
    ]
    return finish_connector(context, source_id, "treasury_debt_to_penny", records, raw_path, checksum, data_type="macro_timeseries", source_url=url)


def run_sec_companyconcept_revenue(context: ConnectorContext) -> dict[str, Any]:
    source_id = "sec_edgar_companyfacts"
    url = "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Revenues.json"
    raw = http_get(url, headers={"User-Agent": "FinancialResearch local connector prototype contact@example.com"})
    raw_path, checksum = save_raw(context, source_id, "sec_aapl_revenues_companyconcept.json", raw)
    payload = json.loads(raw.decode("utf-8"))
    units = payload.get("units", {}).get("USD", [])
    latest = sorted([row for row in units if row.get("fy") and row.get("val")], key=lambda row: str(row.get("end", "")))[-5:]
    records = [
        {
            "date": row.get("end", ""),
            "symbol": "AAPL",
            "metric_name": "revenue",
            "value": to_float(row.get("val")),
            "unit": "USD",
            "currency": "USD",
            "fiscal_year": row.get("fy"),
            "form": row.get("form"),
            "source_id": source_id,
            "retrieved_at": utc_now(),
            "checksum": checksum,
        }
        for row in latest
    ]
    return finish_connector(context, source_id, "sec_aapl_revenue_companyconcept", records, raw_path, checksum, data_type="fundamental_fact", source_url=url)


def run_world_bank_pink_sheet(context: ConnectorContext) -> dict[str, Any]:
    source_id = "world_bank_pink_sheet"
    url = "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
    raw = http_get(url, limit=8_000_000)
    raw_path, checksum = save_raw(context, source_id, "world_bank_pink_sheet_monthly.xlsx", raw)
    records = parse_world_bank_pink_sheet(raw_path, source_id, checksum)
    return finish_connector(context, source_id, "world_bank_pink_sheet_monthly_sample", records, raw_path, checksum, data_type="commodity_timeseries", source_url=url)


def run_fred_probe(context: ConnectorContext) -> dict[str, Any]:
    source_id = "fred_public_csv"
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2026-01-01&coed=2026-05-18"
    try:
        raw = http_get(url, timeout=8, limit=500_000)
    except Exception as exc:
        return connector_result(
            context=context,
            source_id=source_id,
            connector_name="fred_dgs10_probe",
            status="failed",
            records=[],
            raw_output_path="",
            normalized_output_path="",
            quality_result=quality_result("failed", [], ["fred_timeout_or_network_error"], {}, data_type="macro_timeseries"),
            error_message=f"{type(exc).__name__}: {str(exc)[:300]}",
            source_url=url,
        )
    raw_path, checksum = save_raw(context, source_id, "fred_dgs10_probe.csv", raw)
    rows = list(csv.DictReader(raw.decode("utf-8", errors="replace").splitlines()))
    records = [
        {
            "date": row.get("observation_date", ""),
            "metric_name": "DGS10",
            "value": to_float(row.get("DGS10")),
            "unit": "percent",
            "source_id": source_id,
            "retrieved_at": utc_now(),
            "checksum": checksum,
        }
        for row in rows
        if row.get("DGS10") not in {"", "."}
    ]
    return finish_connector(context, source_id, "fred_dgs10_probe", records, raw_path, checksum, data_type="macro_timeseries", source_url=url)


def parse_world_bank_pink_sheet(raw_path: Path, source_id: str, checksum: str) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_excel(raw_path, sheet_name="Monthly Prices", header=None)
    headers = list(df.iloc[4])
    units = list(df.iloc[5])
    codes = list(df.iloc[6])
    data = df.iloc[7:].tail(12)
    target_codes = {"CRUDE_WTI", "COPPER", "GOLD"}
    records = []
    for col_idx, code in enumerate(codes):
        if code not in target_codes:
            continue
        for _, row in data.iterrows():
            value = to_float(row.iloc[col_idx])
            if value is None:
                continue
            records.append(
                {
                    "date": month_label_to_date(str(row.iloc[0])),
                    "metric_name": str(code),
                    "commodity_name": str(headers[col_idx]),
                    "value": value,
                    "unit": str(units[col_idx]),
                    "currency": "USD" if "$" in str(units[col_idx]) else "",
                    "source_id": source_id,
                    "retrieved_at": utc_now(),
                    "checksum": checksum,
                }
            )
    return records


def finish_connector(
    context: ConnectorContext,
    source_id: str,
    connector_name: str,
    records: list[dict[str, Any]],
    raw_path: Path,
    checksum: str,
    data_type: str,
    source_url: str,
) -> dict[str, Any]:
    normalized_path = save_normalized(context, source_id, connector_name, records)
    quality = run_quality_gate(records, data_type=data_type)
    entry = context.source_registry.get(source_id, {})
    trust = resolve_external_trust(entry, quality)
    result = connector_result(
        context=context,
        source_id=source_id,
        connector_name=connector_name,
        status="success" if records else "failed",
        records=records,
        raw_output_path=str(raw_path),
        normalized_output_path=str(normalized_path),
        quality_result=quality,
        source_url=source_url,
        checksum=checksum,
        trust_resolution=trust,
        error_message="" if records else "no_records_normalized",
    )
    log_normalized_dataset(METADATA_DB_PATH, result)
    log_quality(METADATA_DB_PATH, result)
    return result


def connector_result(
    context: ConnectorContext,
    source_id: str,
    connector_name: str,
    status: str,
    records: list[dict[str, Any]],
    raw_output_path: str | Path,
    normalized_output_path: str | Path,
    quality_result: dict[str, Any],
    source_url: str = "",
    checksum: str = "",
    trust_resolution: dict[str, Any] | None = None,
    error_message: str = "",
) -> dict[str, Any]:
    entry = context.source_registry.get(source_id, {})
    trust_resolution = trust_resolution or resolve_external_trust(entry, quality_result)
    return {
        "source_id": source_id,
        "source_name": entry.get("source_name", source_id),
        "connector_name": connector_name,
        "status": status,
        "provider_type": entry.get("provider_type", ""),
        "official_source": bool(entry.get("official_source", False)),
        "trusted_external_eligible": bool(entry.get("trusted_external_eligible", False)),
        "retrieved_at": utc_now(),
        "source_url_or_reference": source_url,
        "raw_output_path": str(raw_output_path),
        "normalized_output_path": str(normalized_output_path),
        "record_count": len(records),
        "quality_check_status": quality_result["status"],
        "trust_status": trust_resolution["trust_status"],
        "candidate_only": trust_resolution["candidate_only"],
        "consumption_eligible": False,
        "error_message": error_message,
        "quality_result": quality_result,
        "trust_resolution": trust_resolution,
    }


def run_quality_gate(records: list[dict[str, Any]], data_type: str) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "source_id_present": all(row.get("source_id") for row in records),
        "retrieved_at_present": all(row.get("retrieved_at") for row in records),
        "checksum_present": all(row.get("checksum") for row in records),
        "missing_value_check": bool(records) and all(row.get("value") is not None for row in records if "value" in row),
        "field_mapping_ok": bool(records),
    }
    date_values = [row.get("date") for row in records if row.get("date")]
    checks["date_format_ok"] = bool(date_values) and all(is_date_like(value) for value in date_values)
    checks["duplicate_check"] = len({json.dumps(row, sort_keys=True, default=str) for row in records}) == len(records)
    numeric_values = [row.get("value") for row in records if "value" in row]
    price_values = [row.get("close") for row in records if "close" in row]
    volume_values = [row.get("volume") for row in records if "volume" in row]
    checks["numeric_format_ok"] = all(isinstance(value, (int, float)) for value in [*numeric_values, *price_values, *volume_values] if value is not None)
    checks["duplicate_date_check"] = len(date_values) == len(set(date_values)) if date_values else False
    checks["date_order_ok"] = date_values == sorted(date_values) or date_values == sorted(date_values, reverse=True) if date_values else False
    checks["frequency_consistency_check"] = bool(date_values)
    checks["suspicious_gap_check"] = True
    if data_type == "daily_price":
        checks["price_non_negative"] = all((row.get(field) is None or row.get(field) >= 0) for row in records for field in ["open", "high", "low", "close"])
        checks["volume_non_negative"] = all((row.get("volume") is None or row.get("volume") >= 0) for row in records)
    if data_type in {"macro_timeseries", "commodity_timeseries", "fundamental_fact"}:
        checks["rate_reasonable_range"] = all((value is None or -1000 < value < 1e16) for value in numeric_values)
        checks["unit_present_if_required"] = all(row.get("unit") for row in records if "value" in row)
        checks["currency_present_if_required"] = True
    failed = [key for key, passed in checks.items() if not passed]
    warnings = []
    status = "quality_passed"
    if failed:
        status = "quality_failed" if any(key in failed for key in ["source_id_present", "retrieved_at_present", "checksum_present", "field_mapping_ok", "numeric_format_ok"]) else "quality_warning"
        warnings.extend(failed)
    return quality_result(status, records, warnings, checks, data_type=data_type)


def quality_result(status: str, records: list[dict[str, Any]], warnings: list[str], checks: dict[str, bool], data_type: str) -> dict[str, Any]:
    normalized_status = "quality_failed" if status == "failed" else status
    return {
        "quality_check_id": stable_id("quality", data_type, str(len(records)), utc_now()[:19]),
        "data_type": data_type,
        "status": normalized_status,
        "record_count": len(records),
        "checks": checks,
        "warnings": warnings,
    }


def resolve_external_trust(entry: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    open_source_wrapper = entry.get("source_id") in {"akshare_traceable_official", "baostock_daily"} or entry.get("provider_type") in {"open_source_wrapper", "open_source_data_interface"}
    if quality["status"] == "quality_failed":
        trust_status = "candidate_external_quality_failed" if open_source_wrapper else ("trusted_source_but_quality_failed" if entry.get("trusted_external_eligible") else "candidate_external_quality_failed")
        candidate_only = True
    elif quality["status"] == "quality_warning":
        trust_status = "candidate_external_quality_warning" if open_source_wrapper else ("trusted_source_quality_warning_candidate" if entry.get("trusted_external_eligible") else "candidate_external_quality_warning")
        candidate_only = True
    elif open_source_wrapper:
        trust_status = "candidate_external_data"
        candidate_only = True
    elif entry.get("trusted_external_eligible") and (entry.get("official_source") or entry.get("provider_type") in {"official_public_api", "official_public_dataset", "official_regulator_api", "official_exchange", "exchange_designated_disclosure_platform"}):
        trust_status = "trusted_by_real_external_candidate"
        candidate_only = True
    else:
        trust_status = "candidate_external_data"
        candidate_only = True
    return {
        "trust_status": trust_status,
        "candidate_only": candidate_only,
        "consumption_eligible": False,
        "reason": "phase2_prototype_external_data_not_connected_to_consumption_layer",
        "quality_status": quality["status"],
    }


def save_raw(context: ConnectorContext, source_id: str, filename: str, data: bytes) -> tuple[Path, str]:
    root = context.raw_api_root / source_id / utc_date()
    root.mkdir(parents=True, exist_ok=True)
    path = root / safe_filename(filename)
    path.write_bytes(data)
    checksum = sha256(data)
    return path, checksum


def save_normalized(context: ConnectorContext, source_id: str, connector_name: str, records: list[dict[str, Any]]) -> Path:
    root = context.normalized_root / source_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_filename(connector_name)}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    cold_root = context.normalized_cold_root / source_id
    try:
        cold_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, cold_root / path.name)
    except OSError:
        pass
    return path


def download_pdf_smoke(context: ConnectorContext, url: str, title: str) -> str:
    try:
        data = http_get(url, timeout=20, limit=20_000_000)
        if not data.startswith(b"%PDF") and len(data) < 1000:
            return ""
        root = context.financial_report_pdf_root / "cninfo" / utc_date()
        root.mkdir(parents=True, exist_ok=True)
        path = root / (safe_filename(title)[:80] + ".pdf")
        path.write_bytes(data)
        return str(path)
    except Exception:
        return ""


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 15, limit: int = 2_000_000) -> bytes:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "FinancialResearch Data Connector Phase2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit)


def http_post(url: str, data: bytes, headers: dict[str, str] | None = None, timeout: int = 15) -> bytes:
    merged_headers = {"User-Agent": "FinancialResearch Data Connector Phase2", "Content-Type": "application/x-www-form-urlencoded"}
    merged_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=merged_headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_000)


def ensure_output_dirs(context: ConnectorContext, output_root: Path) -> None:
    for path in [context.raw_api_root, context.normalized_root, context.normalized_cold_root, output_root]:
        path.mkdir(parents=True, exist_ok=True)


def init_metadata_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS source_registry_index (source_id TEXT PRIMARY KEY, payload_json TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS connector_run_log (run_id TEXT PRIMARY KEY, source_id TEXT, connector_name TEXT, status TEXT, retrieved_at TEXT, raw_output_path TEXT, normalized_output_path TEXT, trust_status TEXT, quality_status TEXT, record_count INTEGER, error_message TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS normalized_dataset_index (dataset_id TEXT PRIMARY KEY, source_id TEXT, connector_name TEXT, normalized_output_path TEXT, record_count INTEGER, created_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS quality_check_log (quality_check_id TEXT PRIMARY KEY, source_id TEXT, connector_name TEXT, status TEXT, payload_json TEXT)")


def index_source_registry(db_path: Path, context: ConnectorContext) -> None:
    with sqlite3.connect(db_path) as conn:
        for source_id, entry in context.source_registry.items():
            conn.execute("INSERT OR REPLACE INTO source_registry_index VALUES (?, ?)", (source_id, json.dumps(entry, ensure_ascii=False)))


def log_connector_run(db_path: Path, result: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO connector_run_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                stable_id("run", result["source_id"], result["connector_name"], result["retrieved_at"]),
                result["source_id"],
                result["connector_name"],
                result["status"],
                result["retrieved_at"],
                result["raw_output_path"],
                result["normalized_output_path"],
                result["trust_status"],
                result["quality_check_status"],
                result["record_count"],
                result["error_message"],
            ),
        )


def log_normalized_dataset(db_path: Path, result: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO normalized_dataset_index VALUES (?, ?, ?, ?, ?, ?)",
            (
                stable_id("dataset", result["source_id"], result["connector_name"], result["normalized_output_path"]),
                result["source_id"],
                result["connector_name"],
                result["normalized_output_path"],
                result["record_count"],
                result["retrieved_at"],
            ),
        )


def log_quality(db_path: Path, result: dict[str, Any]) -> None:
    quality = result["quality_result"]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO quality_check_log VALUES (?, ?, ?, ?, ?)",
            (
                quality["quality_check_id"],
                result["source_id"],
                result["connector_name"],
                quality["status"],
                json.dumps(quality, ensure_ascii=False),
            ),
        )


def build_storage_estimate_refresh(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_raw = sum(Path(row["raw_output_path"]).stat().st_size for row in results if row.get("raw_output_path") and Path(row["raw_output_path"]).exists())
    total_normalized = sum(Path(row["normalized_output_path"]).stat().st_size for row in results if row.get("normalized_output_path") and Path(row["normalized_output_path"]).exists())
    return {
        "generated_at": utc_now(),
        "sample_raw_bytes": total_raw,
        "sample_normalized_bytes": total_normalized,
        "a_share_daily_10y_estimate": "2-8 GB Parquet for OHLCV core fields; raw API response archive may be larger if every query is retained",
        "macro_30y_estimate": "<1 GB for curated official series",
        "commodity_30y_estimate": "1-5 GB for curated monthly/daily commodity series",
        "financial_report_pdf_estimate": "targeted companies: tens of GB; full A-share history can reach hundreds of GB",
        "raw_api_response_policy": "retain official raw responses with checksum; deduplicate repeated smoke/full runs",
        "hot_d_e_z_fit": "D hot runtime + E local bulk + Z cold data remain suitable for Phase 2 and curated Phase 3",
    }


def period_to_month(period: str) -> str:
    match = re.match(r"M(\d{2})", period or "")
    return match.group(1) if match else "01"


def month_label_to_date(label: str) -> str:
    match = re.match(r"(\d{4})M(\d{2})", label)
    return f"{match.group(1)}-{match.group(2)}-01" if match else label


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", "")
        if not text or text in {"бн", "...", "nan", "NaN"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def is_date_like(value: Any) -> bool:
    text = str(value)
    return bool(re.match(r"\d{4}-\d{2}-\d{2}$", text) or re.match(r"\d{4}M\d{2}$", text) or text.isdigit())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "output"


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:16]}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")
