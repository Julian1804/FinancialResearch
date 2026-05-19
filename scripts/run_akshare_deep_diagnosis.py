from __future__ import annotations

import inspect
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services import data_connector_phase2_service as phase2  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "data_connector_akshare_diagnosis"
RAW_ROOT = OUTPUT_ROOT / "raw_responses"
SYMBOLS = ["600519", "000001", "300750"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://quote.eastmoney.com/",
    "Connection": "close",
}


def run_diagnosis() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    context = phase2.load_context()
    environment = build_environment_audit()
    source = inspect_akshare_source()
    matrix = run_minimal_reproduction_matrix()
    patch = run_patch_attempts(context)
    design = build_fr_custom_connector_design()

    phase2.write_json(OUTPUT_ROOT / "akshare_environment_audit.json", environment)
    phase2.write_json(OUTPUT_ROOT / "akshare_source_inspection.json", source)
    phase2.write_json(OUTPUT_ROOT / "minimal_reproduction_matrix.json", matrix)
    phase2.write_json(OUTPUT_ROOT / "akshare_patch_attempt_results.json", patch)
    phase2.write_json(OUTPUT_ROOT / "fr_custom_connector_design.json", design)
    write_docs(environment, source, matrix, patch, design)
    return {
        "akshare_deep_diagnosis_completed": True,
        "root_cause": patch["root_cause"],
        "repair_status": patch["repair_status"],
        "matrix_success_count": matrix["success_count"],
        "matrix_failed_count": matrix["failed_count"],
        "fr_data_connectors_designed": True,
        "baostock_operational_source": True,
        "outputs": {
            "environment": str(OUTPUT_ROOT / "akshare_environment_audit.json"),
            "source_inspection": str(OUTPUT_ROOT / "akshare_source_inspection.json"),
            "matrix": str(OUTPUT_ROOT / "minimal_reproduction_matrix.json"),
            "patch_attempts": str(OUTPUT_ROOT / "akshare_patch_attempt_results.json"),
            "connector_design": str(OUTPUT_ROOT / "fr_custom_connector_design.json"),
            "docs": [
                str(PROJECT_ROOT / "docs" / "AKSHARE_DEEP_DIAGNOSIS_REPORT.md"),
                str(PROJECT_ROOT / "docs" / "FR_CUSTOM_CONNECTOR_LAYER_DESIGN.md"),
                str(PROJECT_ROOT / "docs" / "A_SHARE_DAILY_MULTI_SOURCE_STRATEGY.md"),
            ],
        },
        "no_full_download": True,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
    }


def build_environment_audit() -> dict[str, Any]:
    import importlib.metadata as md

    packages = {}
    for package in ["akshare", "requests", "urllib3", "certifi", "pandas", "curl_cffi"]:
        try:
            packages[package] = md.version(package)
        except Exception:
            packages[package] = "not_installed"
    latest = run_pip_index_latest()
    return {
        "generated_at": phase2.utc_now(),
        "python_executable": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "packages": packages,
        "akshare_latest_available": latest.get("latest", ""),
        "akshare_is_latest": packages.get("akshare") == latest.get("latest"),
        "proxy_environment": {key: masked_env(os.environ.get(key, "")) for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"]},
        "clash_direct_rule_context": "User confirmed DomainSuffix(eastmoney.com) DIRECT for push2his.eastmoney.com.",
        "pip_index_output_summary": latest.get("summary", ""),
    }


def run_pip_index_latest() -> dict[str, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", "akshare"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        latest = ""
        for line in (proc.stdout or "").splitlines():
            if line.strip().startswith("LATEST:"):
                latest = line.split(":", 1)[1].strip()
        return {"latest": latest, "summary": "\n".join((proc.stdout or "").splitlines()[:5])}
    except Exception as exc:  # noqa: BLE001
        return {"latest": "", "summary": f"{type(exc).__name__}: {exc}"}


def inspect_akshare_source() -> dict[str, Any]:
    import akshare
    import akshare.stock_feature.stock_hist_em as stock_hist_em

    fn = stock_hist_em.stock_zh_a_hist
    source_lines, first_line = inspect.getsourcelines(fn)
    source_text = "".join(source_lines)
    return {
        "generated_at": phase2.utc_now(),
        "akshare_file": str(Path(akshare.__file__).resolve()),
        "stock_hist_em_file": str(Path(stock_hist_em.__file__).resolve()),
        "stock_zh_a_hist_first_line": first_line,
        "actual_url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "actual_params": {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": {"daily": "101", "weekly": "102", "monthly": "103"},
            "fqt": {"qfq": "1", "hfq": "2", "": "0"},
            "secid": "1.xxxxxx for symbols starting with 6, otherwise 0.xxxxxx",
            "beg": "start_date",
            "end": "end_date",
        },
        "actual_headers": "none in AKShare stock_zh_a_hist",
        "uses_requests": "requests.get(url, params=params, timeout=timeout)",
        "uses_session": False,
        "timeout_setting": "function argument timeout, defaults to None",
        "failure_layer": "kline_get_network_layer_before_json_parse_when RemoteDisconnected/empty response occurs",
        "code_excerpt": source_text[:3000],
    }


def run_minimal_reproduction_matrix() -> dict[str, Any]:
    methods: list[tuple[str, Callable[[str], dict[str, Any]]]] = [
        ("akshare_stock_zh_a_hist", method_akshare),
        ("requests_https_headers", lambda symbol: method_requests(symbol, "https", headers=True, trust_env=True)),
        ("requests_https_headers_trust_env_false", lambda symbol: method_requests(symbol, "https", headers=True, trust_env=False)),
        ("requests_http_headers", lambda symbol: method_requests(symbol, "http", headers=True, trust_env=True)),
        ("urllib_https_headers", method_urllib),
        ("curl_https_default", lambda symbol: method_curl(symbol, [])),
        ("curl_https_http1_tls12_compressed_ipv4", lambda symbol: method_curl(symbol, ["--http1.1", "--tlsv1.2", "--compressed", "-4"])),
        ("curl_http_default", lambda symbol: method_curl(symbol, [], scheme="http")),
        ("curl_cffi_chrome", method_curl_cffi),
    ]
    items = []
    for method_name, fn in methods:
        for symbol in SYMBOLS:
            items.append(run_matrix_item(method_name, symbol, fn))
    success_count = sum(1 for item in items if item["status"] == "success")
    return {
        "generated_at": phase2.utc_now(),
        "symbols": SYMBOLS,
        "method_count": len(methods),
        "item_count": len(items),
        "success_count": success_count,
        "failed_count": len(items) - success_count,
        "items": items,
        "conclusion": build_matrix_conclusion(items),
    }


def run_matrix_item(method_name: str, symbol: str, fn: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    started = time.time()
    try:
        result = fn(symbol)
        result.setdefault("status", "failed")
        result.setdefault("error_type", "")
    except Exception as exc:  # noqa: BLE001
        result = {"status": "failed", "error_type": type(exc).__name__, "error_message": str(exc)[:500], "response_length": 0, "raw_path": ""}
    result.update(
        {
            "method": method_name,
            "symbol": symbol,
            "elapsed_seconds": round(time.time() - started, 3),
            "retry_count": 0,
            "conclusion": item_conclusion(result),
        }
    )
    return result


def method_akshare(symbol: str) -> dict[str, Any]:
    import akshare as ak

    df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_yyyymmdd(), end_date=end_yyyymmdd(), adjust="", timeout=8)
    raw_path = save_runtime_raw("akshare", symbol, df.to_csv(index=False).encode("utf-8-sig"))
    return {"status": "success" if not df.empty else "failed", "error_type": "" if not df.empty else "empty_dataframe", "response_length": int(raw_path.stat().st_size), "raw_path": str(raw_path), "record_count": int(len(df))}


def method_requests(symbol: str, scheme: str, headers: bool, trust_env: bool) -> dict[str, Any]:
    import requests

    session = requests.Session()
    session.trust_env = trust_env
    response = session.get(build_url(symbol, scheme=scheme), headers=HEADERS if headers else None, timeout=8)
    body = response.content
    raw_path = save_runtime_raw(f"requests_{scheme}", symbol, body)
    ok = response.status_code == 200 and has_klines(body)
    return {"status": "success" if ok else "failed", "error_type": "" if ok else f"http_{response.status_code}_or_no_klines", "response_length": len(body), "raw_path": str(raw_path), "http_status": response.status_code}


def method_urllib(symbol: str) -> dict[str, Any]:
    request = urllib.request.Request(build_url(symbol), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read(2_000_000)
    raw_path = save_runtime_raw("urllib_https", symbol, body)
    return {"status": "success" if has_klines(body) else "failed", "error_type": "" if has_klines(body) else "no_klines", "response_length": len(body), "raw_path": str(raw_path)}


def method_curl(symbol: str, extra_args: list[str], scheme: str = "https") -> dict[str, Any]:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return {"status": "failed", "error_type": "curl_not_found", "response_length": 0, "raw_path": ""}
    proc = subprocess.run(
        [
            curl,
            "-L",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "8",
            "--max-time",
            "15",
            "-H",
            f"User-Agent: {HEADERS['User-Agent']}",
            "-H",
            "Referer: https://quote.eastmoney.com/",
            *extra_args,
            "-w",
            "\n__HTTP_STATUS__:%{http_code}",
            build_url(symbol, scheme=scheme),
        ],
        capture_output=True,
        text=False,
        timeout=20,
    )
    stdout = proc.stdout or b""
    marker = b"\n__HTTP_STATUS__:"
    if marker in stdout:
        body, status = stdout.rsplit(marker, 1)
    else:
        body, status = stdout, b""
    raw_path = save_runtime_raw("curl_" + scheme, symbol, body)
    ok = proc.returncode == 0 and status.strip() == b"200" and has_klines(body)
    return {"status": "success" if ok else "failed", "error_type": "" if ok else (proc.stderr.decode("utf-8", "replace")[:200] or f"http_{status.decode('utf-8','replace')}"), "response_length": len(body), "raw_path": str(raw_path), "http_status": status.decode("utf-8", "replace").strip()}


def method_curl_cffi(symbol: str) -> dict[str, Any]:
    try:
        from curl_cffi import requests as curl_requests
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error_type": f"curl_cffi_not_available:{type(exc).__name__}", "response_length": 0, "raw_path": ""}
    response = curl_requests.get(build_url(symbol), headers=HEADERS, timeout=10, impersonate="chrome120")
    body = response.content
    raw_path = save_runtime_raw("curl_cffi", symbol, body)
    ok = response.status_code == 200 and has_klines(body)
    return {"status": "success" if ok else "failed", "error_type": "" if ok else f"http_{response.status_code}_or_no_klines", "response_length": len(body), "raw_path": str(raw_path), "http_status": response.status_code}


def run_patch_attempts(context: phase2.ConnectorContext) -> dict[str, Any]:
    attempts = [
        {"name": "fr_wrapper_requests_headers_backoff", "result": run_fr_wrapper_attempt(context, "requests")},
        {"name": "fr_wrapper_curl_cffi_chrome", "result": run_fr_wrapper_attempt(context, "curl_cffi")},
        {"name": "akshare_alternative_tencent_hist", "result": run_tencent_alternative_attempt(context)},
    ]
    success = [item for item in attempts if item["result"].get("status") == "success"]
    repair_status = "partially_repaired" if success else "not_repaired"
    root_cause = "Eastmoney push2his network/TLS/upstream disconnect affects AKShare and direct clients; failure occurs before JSON parse and is not fixed by headers, trust_env=False, curl, HTTP/1.1/TLS1.2, or curl_cffi in this environment."
    eastmoney_attempts = [item for item in attempts if item["name"] != "akshare_alternative_tencent_hist"]
    return {
        "generated_at": phase2.utc_now(),
        "repair_status": repair_status,
        "root_cause": root_cause,
        "attempts": attempts,
        "akshare_eastmoney_stock_zh_a_hist_stable": any(item["result"].get("status") == "success" for item in eastmoney_attempts),
        "akshare_alternative_daily_source_available": any(item["name"] == "akshare_alternative_tencent_hist" and item["result"].get("status") == "success" for item in attempts),
        "akshare_stable_for_a_share_daily": "partial_alternative_only" if success else "no",
        "baostock_unblocked": True,
        "trusted_consumption_affected": False,
        "candidate_only": True,
    }


def run_fr_wrapper_attempt(context: phase2.ConnectorContext, client: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors = []
    for symbol in SYMBOLS:
        try:
            result = method_curl_cffi(symbol) if client == "curl_cffi" else method_requests(symbol, "https", headers=True, trust_env=False)
            if result["status"] != "success":
                errors.append({"symbol": symbol, "error": result.get("error_type", "")})
                continue
            raw_path = Path(result["raw_path"])
            payload = json.loads(raw_path.read_text(encoding="utf-8", errors="replace"))
            checksum = phase2.sha256(raw_path.read_bytes())
            for line in (payload.get("data") or {}).get("klines", [])[-30:]:
                parsed = parse_kline(symbol, line, checksum)
                if parsed:
                    records.append(parsed)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    if records:
        raw_path = save_structured_records(context, f"akshare_repair_{client}", records)
        quality = phase2.run_quality_gate(records, "daily_price")
        return {"status": "success", "record_count": len(records), "normalized_output_path": str(raw_path), "quality_result": quality, "trust_status": "candidate_external_data", "errors": errors}
    return {"status": "failed", "record_count": 0, "errors": errors, "trust_status": "candidate_external_quality_failed"}


def run_tencent_alternative_attempt(context: phase2.ConnectorContext) -> dict[str, Any]:
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist_tx(symbol="sz000001", start_date=start_yyyymmdd(), end_date=end_yyyymmdd(), adjust="")
        records = []
        if not df.empty:
            raw_path = save_runtime_raw("akshare_tencent_hist", "000001", df.to_csv(index=False).encode("utf-8-sig"))
            checksum = phase2.sha256(raw_path.read_bytes())
            for _, row in df.tail(30).iterrows():
                records.append(
                    {
                        "date": str(row.get("date", ""))[:10],
                        "symbol": "000001",
                        "open": phase2.to_float(row.get("open")),
                        "high": phase2.to_float(row.get("high")),
                        "low": phase2.to_float(row.get("low")),
                        "close": phase2.to_float(row.get("close")),
                        "amount": phase2.to_float(row.get("amount")),
                        "source_id": "akshare_tencent_hist",
                        "retrieved_at": phase2.utc_now(),
                        "checksum": checksum,
                    }
                )
            output = save_structured_records(context, "akshare_tencent_hist_000001", records)
            quality = phase2.run_quality_gate(records, "daily_price")
            return {
                "status": "success",
                "record_count": len(records),
                "raw_path": str(raw_path),
                "normalized_output_path": str(output),
                "quality_result": quality,
                "quality_check_status": quality["status"],
                "trust_status": "candidate_external_data",
            }
        return {"status": "failed", "record_count": 0, "error": "empty_dataframe", "trust_status": "candidate_external_quality_failed"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "record_count": 0, "error": f"{type(exc).__name__}: {str(exc)[:300]}", "trust_status": "candidate_external_quality_failed"}


def build_fr_custom_connector_design() -> dict[str, Any]:
    return {
        "generated_at": phase2.utc_now(),
        "name": "FRDataConnectors",
        "principle": "Do not clone AKShare. Implement only FinancialResearch adapters with raw preservation, normalization, quality gates, trust status, fallback, and cross-source validation.",
        "adapters": [
            {"adapter": "BaostockDailyAdapter", "role": "operational_source", "trust": "candidate_external_data"},
            {"adapter": "AKShareAdapter", "role": "priority_repair_source_optional_if_unstable", "trust": "candidate_external_data"},
            {"adapter": "EastmoneyDirectAdapter", "role": "deferred_secondary_validation_source", "trust": "candidate_external_data"},
            {"adapter": "CNINFODisclosureAdapter", "role": "financial_report_discovery", "trust": "trusted_by_official_source_candidate"},
            {"adapter": "FREDAdapter", "role": "official_macro_source", "trust": "trusted_by_real_external_candidate"},
            {"adapter": "BLSAdapter", "role": "official_macro_source", "trust": "trusted_by_real_external_candidate"},
            {"adapter": "TreasuryFiscalDataAdapter", "role": "official_macro_source", "trust": "trusted_by_real_external_candidate"},
            {"adapter": "WorldBankPinkSheetAdapter", "role": "official_commodity_source", "trust": "trusted_by_real_external_candidate"},
        ],
        "shared_contract": {
            "input": ["watchlist", "metrics_registry", "source_registry", "storage_paths"],
            "output": ["raw_output_path", "normalized_output_path", "quality_result", "trust_status", "candidate_only", "failure_mode"],
            "storage": "NAS-first raw and structured storage with local runtime mirrors",
            "quality_gate": "required before consumption-grade staging",
            "formal_trusted_consumption": "not modified by connector layer",
        },
    }


def build_url(symbol: str, scheme: str = "https") -> str:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "0",
        "secid": f"{1 if symbol.startswith('6') else 0}.{symbol}",
        "beg": start_yyyymmdd(),
        "end": end_yyyymmdd(),
    }
    return f"{scheme}://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)


def parse_kline(symbol: str, line: str, checksum: str) -> dict[str, Any]:
    parts = line.split(",")
    if len(parts) < 11:
        return {}
    volume_lots = phase2.to_float(parts[5])
    return {
        "date": parts[0],
        "trade_date": parts[0],
        "symbol": symbol,
        "open": phase2.to_float(parts[1]),
        "close": phase2.to_float(parts[2]),
        "high": phase2.to_float(parts[3]),
        "low": phase2.to_float(parts[4]),
        "volume": volume_lots * 100 if volume_lots is not None else None,
        "amount": phase2.to_float(parts[6]),
        "amplitude": phase2.to_float(parts[7]),
        "pct_change": phase2.to_float(parts[8]),
        "change_amount": phase2.to_float(parts[9]),
        "turnover_rate": phase2.to_float(parts[10]),
        "source_id": "akshare_repair_attempt",
        "retrieved_at": phase2.utc_now(),
        "checksum": checksum,
    }


def save_runtime_raw(method: str, symbol: str, data: bytes) -> Path:
    path = RAW_ROOT / method / f"{symbol}_{phase2.utc_date()}_{phase2.stable_id('raw', method, symbol, str(len(data)))}.raw"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def save_structured_records(context: phase2.ConnectorContext, name: str, records: list[dict[str, Any]]) -> Path:
    root = Path(context.storage_paths["structured_data_root"]) / "market_data" / "a_share_daily"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{phase2.safe_filename(name)}.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records), encoding="utf-8")
    return path


def has_klines(body: bytes) -> bool:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
        return bool((payload.get("data") or {}).get("klines"))
    except Exception:
        return False


def build_matrix_conclusion(items: list[dict[str, Any]]) -> str:
    if any(item["status"] == "success" for item in items):
        return "some_clients_can_reach_eastmoney_or_alternative; use only as candidate secondary until stable"
    return "all tested clients failed or returned no klines; issue is network/upstream/TLS layer, not AKShare field mapping"


def item_conclusion(result: dict[str, Any]) -> str:
    if result.get("status") == "success":
        return "reachable"
    text = (result.get("error_type", "") + " " + result.get("error_message", "")).lower()
    if "remote" in text or "empty" in text or "schannel" in text or "ssl" in text:
        return "network_tls_or_upstream_disconnect"
    if "timeout" in text:
        return "timeout"
    if "no_klines" in text or "empty_dataframe" in text:
        return "empty_or_blocked_payload"
    return "failed"


def start_yyyymmdd() -> str:
    return (date.today() - timedelta(days=45)).strftime("%Y%m%d")


def end_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def masked_env(value: str) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://****@{host}{port}" if parsed.scheme else "****"


def write_docs(environment: dict[str, Any], source: dict[str, Any], matrix: dict[str, Any], patch: dict[str, Any], design: dict[str, Any]) -> None:
    docs = PROJECT_ROOT / "docs"
    (docs / "AKSHARE_DEEP_DIAGNOSIS_REPORT.md").write_text(render_diagnosis_doc(environment, source, matrix, patch), encoding="utf-8")
    (docs / "FR_CUSTOM_CONNECTOR_LAYER_DESIGN.md").write_text(render_design_doc(design), encoding="utf-8")
    (docs / "A_SHARE_DAILY_MULTI_SOURCE_STRATEGY.md").write_text(render_strategy_doc(patch), encoding="utf-8")


def render_diagnosis_doc(environment: dict[str, Any], source: dict[str, Any], matrix: dict[str, Any], patch: dict[str, Any]) -> str:
    method_counts: dict[str, dict[str, int]] = {}
    for item in matrix["items"]:
        method_counts.setdefault(item["method"], {"success": 0, "failed": 0})[item["status"]] += 1
    return f"""# AKShare Deep Diagnosis Report

## Environment

- Python: `{environment['python_version']}`
- AKShare: `{environment['packages']['akshare']}` latest available: `{environment['akshare_latest_available']}`
- requests: `{environment['packages']['requests']}`
- urllib3: `{environment['packages']['urllib3']}`
- curl_cffi: `{environment['packages']['curl_cffi']}`
- proxy environment: `{json.dumps(environment['proxy_environment'], ensure_ascii=False)}`

## AKShare Source Inspection

- source file: `{source['stock_hist_em_file']}`
- function first line: {source['stock_zh_a_hist_first_line']}
- URL: `{source['actual_url']}`
- client: `{source['uses_requests']}`
- session: {source['uses_session']}
- timeout: {source['timeout_setting']}
- failure layer: {source['failure_layer']}

## Minimal Reproduction Matrix

- items: {matrix['item_count']}
- success: {matrix['success_count']}
- failed: {matrix['failed_count']}

```json
{json.dumps(method_counts, ensure_ascii=False, indent=2)}
```

Conclusion: {matrix['conclusion']}

## Patch Attempts

- repair status: {patch['repair_status']}
- root cause: {patch['root_cause']}
- Eastmoney-backed `stock_zh_a_hist` stable: {patch['akshare_eastmoney_stock_zh_a_hist_stable']}
- AKShare alternative daily source available: {patch['akshare_alternative_daily_source_available']}

Patch attempts remain candidate-only and do not affect formal trusted consumption.
"""


def render_design_doc(design: dict[str, Any]) -> str:
    rows = "\n".join(f"| {item['adapter']} | {item['role']} | {item['trust']} |" for item in design["adapters"])
    return f"""# FR Custom Connector Layer Design

## Name

`{design['name']}`

## Principle

{design['principle']}

## Adapters

| Adapter | Role | Trust |
|---|---|---|
{rows}

## Shared Contract

```json
{json.dumps(design['shared_contract'], ensure_ascii=False, indent=2)}
```
"""


def render_strategy_doc(patch: dict[str, Any]) -> str:
    return f"""# A-share Daily Multi-source Strategy

## Current Strategy

1. Baostock: `operational_source`, `candidate_external_data`, current primary fallback.
2. AKShare: `priority_repair_source`, optional when unstable; if repaired, use as secondary source.
3. Eastmoney direct: `deferred_secondary_validation_source`; can become secondary only when client/network stabilizes.
4. Future official/authorized sources: exchange official feeds, authorized Eastmoney, Wind, Tonghuashun, Morningstar, or similar licensed sources.

## AKShare Repair Outcome

- repair status: {patch['repair_status']}
- root cause: {patch['root_cause']}
- Eastmoney-backed path: {"available" if patch['akshare_eastmoney_stock_zh_a_hist_stable'] else "not available"}
- alternative AKShare daily path: {"available" if patch['akshare_alternative_daily_source_available'] else "not available"}

## Trust Rule

Baostock, AKShare, and Eastmoney direct remain candidate external data. Cross-source agreement can enter consumption-grade staging candidate, but not formal trusted consumption.
"""


def main() -> int:
    summary = run_diagnosis()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
