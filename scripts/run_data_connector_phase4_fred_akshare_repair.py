from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services import data_connector_phase2_service as phase2  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "data_connector_phase4"
LOCAL_SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "FRED_AND_AKSHARE_REPAIR_REPORT.md"


def run_phase4() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    context = phase2.load_context()
    key_readiness = check_fred_key_readiness()
    fred_results = run_fred_smoke(context, key_readiness)
    ak_network = inspect_akshare_network()
    ak_results = run_akshare_retries(context)
    validation = run_cross_source_validation(context, ak_results)

    phase2.write_json(OUTPUT_ROOT / "fred_key_readiness_result.json", key_readiness)
    phase2.write_json(OUTPUT_ROOT / "fred_repair_results.json", fred_results)
    phase2.write_json(OUTPUT_ROOT / "akshare_network_diagnosis.json", ak_network)
    phase2.write_json(OUTPUT_ROOT / "akshare_repair_results.json", ak_results)
    phase2.write_json(OUTPUT_ROOT / "market_daily_cross_source_validation_after_akshare.json", validation)
    REPORT_PATH.write_text(render_report(key_readiness, fred_results, ak_network, ak_results, validation), encoding="utf-8")
    return {
        "phase4_completed": True,
        "fred_key_present": key_readiness["key_present"],
        "fred_smoke_status": fred_results["overall_status"],
        "akshare_status": ak_results["overall_status"],
        "baostock_fallback_status": validation["baostock_fallback_status"],
        "outputs": {
            "fred_key_readiness": str(OUTPUT_ROOT / "fred_key_readiness_result.json"),
            "fred_repair_results": str(OUTPUT_ROOT / "fred_repair_results.json"),
            "akshare_network_diagnosis": str(OUTPUT_ROOT / "akshare_network_diagnosis.json"),
            "akshare_repair_results": str(OUTPUT_ROOT / "akshare_repair_results.json"),
            "cross_source_validation": str(OUTPUT_ROOT / "market_daily_cross_source_validation_after_akshare.json"),
            "report": str(REPORT_PATH),
        },
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
    }


def check_fred_key_readiness() -> dict[str, Any]:
    env_key = os.environ.get("FRED_API_KEY", "")
    file_key = ""
    parse_ok = False
    fields_present: list[str] = []
    if LOCAL_SECRETS_PATH.exists():
        payload = json.loads(LOCAL_SECRETS_PATH.read_text(encoding="utf-8"))
        parse_ok = True
        fields_present = sorted(payload.keys())
        file_key = payload.get("FRED_API_KEY") or payload.get("fred_api_key") or ""
    key = env_key or file_key
    return {
        "generated_at": phase2.utc_now(),
        "local_secrets_exists": LOCAL_SECRETS_PATH.exists(),
        "local_secrets_parse_ok": parse_ok,
        "key_source": "environment" if env_key else ("local_secrets" if file_key else "missing"),
        "key_present": bool(key),
        "masked_fred_api_key": mask_secret(key) if key else "",
        "fields_present": fields_present,
        "full_key_logged": False,
    }


def run_fred_smoke(context: phase2.ConnectorContext, readiness: dict[str, Any]) -> dict[str, Any]:
    key = load_fred_key()
    series = [
        {"series_id": "DGS10", "metric_name": "treasury_10y_yield", "unit": "percent"},
        {"series_id": "DCOILWTICO", "metric_name": "wti_crude_oil_spot_price", "unit": "USD_per_barrel"},
        {"series_id": "CPIAUCSL", "metric_name": "cpi_all_urban_consumers", "unit": "index"},
    ]
    items = []
    for item in series:
        if not key:
            items.append(fred_failure_item(item, "missing_fred_api_key"))
            continue
        items.append(fetch_fred_series(context, key, item))
    success_count = sum(1 for item in items if item["status"] == "success")
    return {
        "generated_at": phase2.utc_now(),
        "key_present": readiness["key_present"],
        "masked_fred_api_key": readiness.get("masked_fred_api_key", ""),
        "overall_status": "success" if success_count == len(items) else ("partial_success" if success_count else "failed"),
        "success_count": success_count,
        "failed_count": len(items) - success_count,
        "items": items,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def fetch_fred_series(context: phase2.ConnectorContext, key: str, series: dict[str, str]) -> dict[str, Any]:
    source_id = "fred_public_csv"
    end = date.today()
    start = end - timedelta(days=90)
    params = {
        "series_id": series["series_id"],
        "api_key": key,
        "file_type": "json",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
    }
    safe_reference = f"https://api.stlouisfed.org/fred/series/observations?series_id={series['series_id']}&file_type=json"
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
    last_error = ""
    for attempt in range(1, 4):
        try:
            raw = http_get_limited(url, timeout=12)
            if key.encode("utf-8") in raw:
                raw = raw.replace(key.encode("utf-8"), b"****")
            raw_path, checksum = phase2.save_raw(context, source_id, f"fred_{series['series_id']}_api_smoke.json", raw)
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            records = []
            for row in payload.get("observations", [])[-30:]:
                value = phase2.to_float(row.get("value"))
                if value is None:
                    continue
                records.append(
                    {
                        "date": row.get("date", ""),
                        "series_id": series["series_id"],
                        "metric_name": series["metric_name"],
                        "value": value,
                        "unit": series["unit"],
                        "source_id": source_id,
                        "retrieved_at": phase2.utc_now(),
                        "checksum": checksum,
                    }
                )
            normalized_path = save_structured_and_runtime(context, source_id, f"fred_{series['series_id']}_api_smoke", records)
            quality = phase2.run_quality_gate(records, "macro_timeseries")
            trust_status = "trusted_by_real_external_candidate" if quality["status"] == "quality_passed" else "trusted_source_but_quality_failed"
            return {
                "series_id": series["series_id"],
                "status": "success" if records else "failed",
                "attempts": attempt,
                "record_count": len(records),
                "source_url_or_reference": safe_reference,
                "raw_output_path": str(raw_path),
                "normalized_output_path": str(normalized_path),
                "quality_result": quality,
                "quality_check_status": quality["status"],
                "trust_status": trust_status,
                "candidate_only": True,
                "formal_trusted_consumption": False,
                "error_message": "" if records else "no_records_normalized",
            }
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            time.sleep(attempt)
    return fred_failure_item(series, last_error)


def fred_failure_item(series: dict[str, str], error: str) -> dict[str, Any]:
    return {
        "series_id": series["series_id"],
        "status": "failed",
        "attempts": 3 if error != "missing_fred_api_key" else 0,
        "record_count": 0,
        "source_url_or_reference": f"https://api.stlouisfed.org/fred/series/observations?series_id={series['series_id']}&file_type=json",
        "raw_output_path": "",
        "normalized_output_path": "",
        "quality_result": phase2.quality_result("failed", [], ["fred_api_smoke_failed"], {}, "macro_timeseries"),
        "quality_check_status": "quality_failed",
        "trust_status": "trusted_source_but_quality_failed",
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "error_message": error,
    }


def inspect_akshare_network() -> dict[str, Any]:
    import akshare as ak

    proxy_vars = {key: masked_proxy(os.environ.get(key, "")) for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"]}
    return {
        "generated_at": phase2.utc_now(),
        "akshare_import_ok": True,
        "akshare_version": getattr(ak, "__version__", "unknown"),
        "proxy_environment": proxy_vars,
        "vpn_context_note": "User reported Hong Kong VPN node; script records environment variables only.",
    }


def run_akshare_retries(context: phase2.ConnectorContext) -> dict[str, Any]:
    import akshare as ak

    tests = [
        {
            "name": "stock_zh_a_hist_000001",
            "kind": "a_share_history",
            "call": lambda: ak.stock_zh_a_hist(symbol="000001", period="daily", start_date=(date.today() - timedelta(days=45)).strftime("%Y%m%d"), end_date=date.today().strftime("%Y%m%d"), adjust="").tail(30),
        },
        {
            "name": "stock_zh_a_hist_600519",
            "kind": "a_share_history",
            "call": lambda: ak.stock_zh_a_hist(symbol="600519", period="daily", start_date=(date.today() - timedelta(days=45)).strftime("%Y%m%d"), end_date=date.today().strftime("%Y%m%d"), adjust="").tail(30),
        },
        {
            "name": "stock_zh_a_spot_em",
            "kind": "alternative_dataset",
            "call": lambda: ak.stock_zh_a_spot_em().head(20),
        },
    ]
    items = []
    for test in tests:
        items.append(run_akshare_test(context, test))
    success_count = sum(1 for item in items if item["status"] == "success")
    diagnosis = diagnose_akshare(items)
    return {
        "generated_at": phase2.utc_now(),
        "overall_status": "success" if success_count == len(items) else ("partial_success" if success_count else "failed"),
        "success_count": success_count,
        "failed_count": len(items) - success_count,
        "items": items,
        "diagnosis": diagnosis,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def run_akshare_test(context: phase2.ConnectorContext, test: dict[str, Any]) -> dict[str, Any]:
    source_id = "akshare_traceable_official"
    started = time.time()
    try:
        df = test["call"]()
        raw_bytes = df.to_csv(index=False).encode("utf-8-sig")
        raw_path, checksum = phase2.save_raw(context, source_id, f"akshare_{test['name']}.csv", raw_bytes)
        records = normalize_akshare_frame(df, test["name"], checksum)
        normalized_path = save_structured_and_runtime(context, source_id, f"akshare_{test['name']}", records)
        quality = phase2.run_quality_gate(records, "daily_price" if test["kind"] == "a_share_history" else "market_snapshot")
        return {
            "test_name": test["name"],
            "kind": test["kind"],
            "status": "success" if records else "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "record_count": len(records),
            "raw_output_path": str(raw_path),
            "normalized_output_path": str(normalized_path),
            "quality_check_status": quality["status"],
            "quality_result": quality,
            "trust_status": "candidate_external_data" if quality["status"] != "quality_failed" else "candidate_external_quality_failed",
            "candidate_only": True,
            "formal_trusted_consumption": False,
            "error_message": "" if records else "no_records_normalized",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "test_name": test["name"],
            "kind": test["kind"],
            "status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "record_count": 0,
            "raw_output_path": "",
            "normalized_output_path": "",
            "quality_check_status": "quality_failed",
            "quality_result": phase2.quality_result("failed", [], ["akshare_test_failed"], {}, "market_data"),
            "trust_status": "candidate_external_quality_failed",
            "candidate_only": True,
            "formal_trusted_consumption": False,
            "error_message": f"{type(exc).__name__}: {str(exc)[:500]}",
        }


def normalize_akshare_frame(df: Any, test_name: str, checksum: str) -> list[dict[str, Any]]:
    source_id = "akshare_traceable_official"
    column_aliases = {
        "日期": "date",
        "代码": "symbol",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "最新价": "close",
    }
    records = []
    for _, row in df.iterrows():
        mapped = {column_aliases.get(str(key), str(key)): value for key, value in row.items()}
        record = {
            "date": str(mapped.get("date", ""))[:10],
            "symbol": str(mapped.get("symbol", test_name)).strip(),
            "open": phase2.to_float(mapped.get("open")),
            "high": phase2.to_float(mapped.get("high")),
            "low": phase2.to_float(mapped.get("low")),
            "close": phase2.to_float(mapped.get("close")),
            "volume": phase2.to_float(mapped.get("volume")),
            "amount": phase2.to_float(mapped.get("amount")),
            "currency": "CNY",
            "source_id": source_id,
            "retrieved_at": phase2.utc_now(),
            "checksum": checksum,
        }
        records.append(record)
    return records


def run_cross_source_validation(context: phase2.ConnectorContext, ak_results: dict[str, Any]) -> dict[str, Any]:
    baostock = run_baostock_validation_sample(context)
    ak_success = [item for item in ak_results.get("items", []) if item.get("status") == "success" and item.get("normalized_output_path")]
    comparisons = []
    if baostock["status"] == "success" and ak_success:
        baostock_by_key = {(row["symbol"].split(".")[-1], row["date"]): row for row in baostock["records"]}
        for item in ak_success:
            for row in read_jsonl(Path(item["normalized_output_path"])):
                key = (str(row.get("symbol", "")).replace("sh", "").replace("sz", "").replace(".", "")[-6:], row.get("date"))
                peer = baostock_by_key.get(key)
                if peer and row.get("close") is not None and peer.get("close") is not None:
                    diff = abs(float(row["close"]) - float(peer["close"]))
                    comparisons.append({"symbol_date": key, "akshare_close": row["close"], "baostock_close": peer["close"], "close_abs_diff": diff})
    return {
        "generated_at": phase2.utc_now(),
        "baostock_fallback_status": baostock["status"],
        "baostock_record_count": len(baostock.get("records", [])),
        "akshare_successful_datasets": len(ak_success),
        "comparison_count": len(comparisons),
        "validation_status": "cross_source_compared" if comparisons else ("baostock_available_akshare_unavailable" if baostock["status"] == "success" else "validation_unavailable"),
        "comparisons": comparisons[:20],
        "baostock_raw_output_path": baostock.get("raw_output_path", ""),
        "baostock_normalized_output_path": baostock.get("normalized_output_path", ""),
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def run_baostock_validation_sample(context: phase2.ConnectorContext) -> dict[str, Any]:
    import baostock as bs

    source_id = "baostock_daily"
    end = date.today()
    start = end - timedelta(days=45)
    rows = []
    login = bs.login()
    if login.error_code != "0":
        return {"status": "failed", "records": [], "error_message": login.error_msg}
    try:
        for code in ["sz.000001", "sh.600519"]:
            rs = bs.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,volume,amount",
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency="d",
                adjustflag="3",
            )
            symbol_rows = []
            while rs.error_code == "0" and rs.next():
                symbol_rows.append(dict(zip(rs.fields, rs.get_row_data())))
            rows.extend(symbol_rows[-30:])
    finally:
        bs.logout()
    raw_bytes = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    raw_path, checksum = phase2.save_raw(context, source_id, "baostock_akshare_validation_sample.json", raw_bytes)
    records = [
        {
            "date": row.get("date", ""),
            "symbol": row.get("code", ""),
            "open": phase2.to_float(row.get("open")),
            "high": phase2.to_float(row.get("high")),
            "low": phase2.to_float(row.get("low")),
            "close": phase2.to_float(row.get("close")),
            "volume": phase2.to_float(row.get("volume")),
            "amount": phase2.to_float(row.get("amount")),
            "currency": "CNY",
            "source_id": source_id,
            "retrieved_at": phase2.utc_now(),
            "checksum": checksum,
        }
        for row in rows
    ]
    normalized_path = save_structured_and_runtime(context, source_id, "baostock_akshare_validation_sample", records)
    return {"status": "success" if records else "failed", "records": records, "raw_output_path": str(raw_path), "normalized_output_path": str(normalized_path)}


def diagnose_akshare(items: list[dict[str, Any]]) -> dict[str, Any]:
    errors = " ".join(item.get("error_message", "") for item in items if item.get("status") != "success")
    if not errors:
        likely = "akshare_available_on_current_network"
        action = "Keep AKShare candidate-only until dataset-level provenance is documented."
    elif "ProxyError" in errors or "proxy" in errors.lower() or "RemoteDisconnected" in errors:
        likely = "vpn_or_proxy_or_upstream_disconnect"
        action = "Try disabling VPN, switching to another Hong Kong/mainland-friendly node, clearing HTTP_PROXY/HTTPS_PROXY/ALL_PROXY, or opening the Eastmoney endpoint in a browser."
    elif "timeout" in errors.lower():
        likely = "network_timeout_or_upstream_slow"
        action = "Retry later with short backoff; keep Baostock as the A-share daily fallback."
    else:
        likely = "akshare_wrapper_or_upstream_api_error"
        action = "Check AKShare release notes for endpoint changes; do not trust broad AKShare datasets without provenance."
    return {"likely_cause": likely, "user_next_action": action}


def save_structured_and_runtime(context: phase2.ConnectorContext, source_id: str, name: str, records: list[dict[str, Any]]) -> Path:
    runtime_path = phase2.save_normalized(context, source_id, name, records)
    structured_root = Path(context.storage_paths["structured_data_root"]) / source_id
    try:
        structured_root.mkdir(parents=True, exist_ok=True)
        structured_path = structured_root / f"{phase2.safe_filename(name)}.jsonl"
        structured_path.write_text(runtime_path.read_text(encoding="utf-8"), encoding="utf-8")
        return structured_path
    except OSError:
        return runtime_path


def load_fred_key() -> str:
    env_key = os.environ.get("FRED_API_KEY", "")
    if env_key:
        return env_key
    if not LOCAL_SECRETS_PATH.exists():
        return ""
    payload = json.loads(LOCAL_SECRETS_PATH.read_text(encoding="utf-8"))
    return payload.get("FRED_API_KEY") or payload.get("fred_api_key") or ""


def http_get_limited(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "FinancialResearch FRED API smoke"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_000)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "****" + value[-4:]


def masked_proxy(value: str) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://****@{host}{port}" if parsed.scheme else "****"


def render_report(key_readiness: dict[str, Any], fred_results: dict[str, Any], ak_network: dict[str, Any], ak_results: dict[str, Any], validation: dict[str, Any]) -> str:
    fred_rows = "\n".join(
        f"| {item['series_id']} | {item['status']} | {item['record_count']} | {item['quality_check_status']} | {item['trust_status']} | {item.get('error_message','')} |"
        for item in fred_results["items"]
    )
    ak_rows = "\n".join(
        f"| {item['test_name']} | {item['status']} | {item['record_count']} | {item['quality_check_status']} | {item.get('error_message','')} |"
        for item in ak_results["items"]
    )
    return f"""# FRED and AKShare Repair Report

## Secrets Safety

- local secrets exists: {key_readiness['local_secrets_exists']}
- FRED key present: {key_readiness['key_present']}
- masked FRED key: `{key_readiness.get('masked_fred_api_key', '')}`
- full key logged: {key_readiness['full_key_logged']}

## FRED Smoke

| Series | Status | Records | Quality | Trust | Error |
|---|---:|---:|---|---|---|
{fred_rows}

FRED remains candidate-only and is not connected to formal trusted consumption.

## AKShare Network

- akshare import ok: {ak_network['akshare_import_ok']}
- akshare version: {ak_network['akshare_version']}
- likely cause: {ak_results['diagnosis']['likely_cause']}
- user next action: {ak_results['diagnosis']['user_next_action']}

| Test | Status | Records | Quality | Error |
|---|---:|---:|---|---|
{ak_rows}

## Cross-source Validation

- validation status: {validation['validation_status']}
- Baostock fallback status: {validation['baostock_fallback_status']}
- comparison count: {validation['comparison_count']}

Baostock remains available as the A-share daily fallback. No output enters formal trusted consumption.
"""


def main() -> int:
    summary = run_phase4()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
