from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services import data_connector_phase2_service as phase2  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "data_connector_phase4"
REPORT_PATH = PROJECT_ROOT / "docs" / "EASTMONEY_DIRECT_CONNECTOR_FALLBACK_REPORT.md"
SYMBOLS = ["600519", "000001", "300750"]


def run_eastmoney_direct_fallback() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    context = phase2.load_context()
    curl_path = shutil.which("curl.exe") or shutil.which("curl")
    eastmoney = run_eastmoney_connector(context, curl_path)
    baostock = run_baostock_sample(context)
    validation = validate_eastmoney_vs_baostock(eastmoney, baostock)
    akshare_final = build_akshare_final_status()

    phase2.write_json(OUTPUT_ROOT / "eastmoney_direct_connector_results.json", eastmoney)
    phase2.write_json(OUTPUT_ROOT / "eastmoney_direct_normalized_sample.json", {"generated_at": phase2.utc_now(), "items": eastmoney["normalized_records"]})
    phase2.write_json(OUTPUT_ROOT / "market_daily_cross_source_validation_eastmoney_baostock.json", validation)
    phase2.write_json(OUTPUT_ROOT / "akshare_final_status.json", akshare_final)
    REPORT_PATH.write_text(render_report(eastmoney, validation, akshare_final), encoding="utf-8")
    return {
        "eastmoney_direct_completed": True,
        "curl_path": curl_path,
        "eastmoney_overall_status": eastmoney["overall_status"],
        "eastmoney_total_records": eastmoney["total_normalized_records"],
        "validation_summary": validation["summary"],
        "akshare_status": akshare_final["status"],
        "outputs": {
            "eastmoney_results": str(OUTPUT_ROOT / "eastmoney_direct_connector_results.json"),
            "eastmoney_normalized_sample": str(OUTPUT_ROOT / "eastmoney_direct_normalized_sample.json"),
            "cross_source_validation": str(OUTPUT_ROOT / "market_daily_cross_source_validation_eastmoney_baostock.json"),
            "akshare_final_status": str(OUTPUT_ROOT / "akshare_final_status.json"),
            "report": str(REPORT_PATH),
        },
        "no_full_download": True,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
    }


def run_eastmoney_connector(context: phase2.ConnectorContext, curl_path: str | None) -> dict[str, Any]:
    items = []
    normalized_records: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        item = fetch_eastmoney_symbol(context, symbol, curl_path)
        items.append(item)
        normalized_records.extend(item.get("normalized_records", []))
    normalized_output_path = save_eastmoney_normalized(context, normalized_records)
    runtime_mirror = OUTPUT_ROOT / "eastmoney_direct_normalized_sample.jsonl"
    runtime_mirror.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in normalized_records), encoding="utf-8")
    success_count = sum(1 for item in items if item["status"] == "success")
    return {
        "generated_at": phase2.utc_now(),
        "source_id": "eastmoney_direct",
        "source_role": "secondary_validation_source",
        "curl_path": curl_path or "",
        "overall_status": "success" if success_count == len(items) else ("partial_success" if success_count else "failed"),
        "success_count": success_count,
        "failed_count": len(items) - success_count,
        "symbols": SYMBOLS,
        "total_normalized_records": len(normalized_records),
        "normalized_output_path": str(normalized_output_path),
        "runtime_mirror_path": str(runtime_mirror),
        "items": items,
        "normalized_records": normalized_records,
        "trust_status": "candidate_external_data",
        "trust_role": "secondary_validation_source",
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def fetch_eastmoney_symbol(context: phase2.ConnectorContext, symbol: str, curl_path: str | None) -> dict[str, Any]:
    started = time.time()
    if not curl_path:
        return failed_symbol(context, symbol, "curl_not_found", started)
    url = build_eastmoney_url(symbol)
    last_error = ""
    for attempt in range(1, 4):
        try:
            response = run_curl(curl_path, url)
            status = response["http_status"]
            body = response["body"]
            if status != "200":
                last_error = f"non_200_http_status:{status}"
                time.sleep(attempt)
                continue
            if not body.strip():
                last_error = "empty_response"
                time.sleep(attempt)
                continue
            payload = json.loads(body)
            klines = (payload.get("data") or {}).get("klines") or []
            raw_path, checksum = save_eastmoney_raw(context, symbol, body.encode("utf-8"))
            records = [parse_kline(symbol, line, checksum) for line in klines[-30:]]
            records = [row for row in records if row]
            return {
                "symbol": symbol,
                "secid": secid_for_symbol(symbol),
                "status": "success" if records else "failed",
                "attempts": attempt,
                "elapsed_seconds": round(time.time() - started, 3),
                "http_status": status,
                "raw_output_path": str(raw_path),
                "record_count": len(records),
                "normalized_records": records,
                "failure_mode": "" if records else "no_klines_or_parse_empty",
                "source_url_or_reference": sanitize_url(url),
            }
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            time.sleep(attempt)
    return failed_symbol(context, symbol, last_error, started, sanitize_url(url))


def run_curl(curl_path: str, url: str) -> dict[str, str]:
    proc = subprocess.run(
        [
            curl_path,
            "-L",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "8",
            "--max-time",
            "15",
            "-H",
            "User-Agent: Mozilla/5.0 FinancialResearch Eastmoney direct smoke",
            "-w",
            "\n__HTTP_STATUS__:%{http_code}",
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    output = proc.stdout or ""
    if "__HTTP_STATUS__:" in output:
        body, status = output.rsplit("__HTTP_STATUS__:", 1)
    else:
        body, status = output, ""
    if proc.returncode != 0 and not body.strip():
        raise RuntimeError((proc.stderr or f"curl_exit_{proc.returncode}")[:500])
    return {"body": body.strip(), "http_status": status.strip(), "stderr": proc.stderr[:500] if proc.stderr else ""}


def build_eastmoney_url(symbol: str) -> str:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "0",
        "secid": secid_for_symbol(symbol),
        "beg": (date.today() - timedelta(days=70)).strftime("%Y%m%d"),
        "end": date.today().strftime("%Y%m%d"),
    }
    return "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)


def secid_for_symbol(symbol: str) -> str:
    return f"1.{symbol}" if symbol.startswith("6") else f"0.{symbol}"


def parse_kline(symbol: str, line: str, checksum: str) -> dict[str, Any]:
    # Eastmoney fields2 order used above:
    # f51 trade_date, f52 open, f53 close, f54 high, f55 low,
    # f56 volume in lots (1 lot = 100 shares), f57 amount in yuan,
    # f58 amplitude %, f59 pct_change %, f60 change_amount, f61 turnover_rate %.
    parts = line.split(",")
    if len(parts) < 11:
        return {}
    volume_lots = phase2.to_float(parts[5])
    change_amount = phase2.to_float(parts[9])
    close = phase2.to_float(parts[2])
    preclose = close - change_amount if close is not None and change_amount is not None else None
    return {
        "trade_date": parts[0],
        "date": parts[0],
        "symbol": symbol,
        "market": "SH" if symbol.startswith("6") else "SZ",
        "open": phase2.to_float(parts[1]),
        "high": phase2.to_float(parts[3]),
        "low": phase2.to_float(parts[4]),
        "close": close,
        "preclose": preclose,
        "volume": volume_lots * 100 if volume_lots is not None else None,
        "amount": phase2.to_float(parts[6]),
        "turnover_rate": phase2.to_float(parts[10]),
        "pct_change": phase2.to_float(parts[8]),
        "amplitude": phase2.to_float(parts[7]),
        "change_amount": change_amount,
        "source_id": "eastmoney_direct",
        "retrieved_at": phase2.utc_now(),
        "raw_checksum": checksum,
        "volume_unit_original": "lot_100_shares",
        "volume_unit_normalized": "shares",
        "amount_unit_normalized": "CNY",
    }


def save_eastmoney_raw(context: phase2.ConnectorContext, symbol: str, raw: bytes) -> tuple[Path, str]:
    root = Path(context.storage_paths["raw_api_response_root"]) / "eastmoney_direct" / phase2.utc_date()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"eastmoney_push2his_{symbol}_daily_30d.json"
    path.write_bytes(raw)
    return path, phase2.sha256(raw)


def save_eastmoney_normalized(context: phase2.ConnectorContext, records: list[dict[str, Any]]) -> Path:
    root = Path(context.storage_paths["structured_data_root"]) / "market_data" / "a_share_daily"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "eastmoney_direct_daily_30d_sample.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records), encoding="utf-8")
    return path


def failed_symbol(context: phase2.ConnectorContext, symbol: str, failure_mode: str, started: float, source_url: str = "") -> dict[str, Any]:
    raw_path = save_eastmoney_failure_raw(context, symbol, failure_mode, source_url)
    return {
        "symbol": symbol,
        "secid": secid_for_symbol(symbol),
        "status": "failed",
        "attempts": 3,
        "elapsed_seconds": round(time.time() - started, 3),
        "http_status": "",
        "raw_output_path": str(raw_path),
        "record_count": 0,
        "normalized_records": [],
        "failure_mode": failure_mode,
        "source_url_or_reference": source_url,
    }


def save_eastmoney_failure_raw(context: phase2.ConnectorContext, symbol: str, failure_mode: str, source_url: str) -> Path:
    root = Path(context.storage_paths["raw_api_response_root"]) / "eastmoney_direct" / phase2.utc_date()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"eastmoney_push2his_{symbol}_daily_30d_failure.json"
    payload = {
        "generated_at": phase2.utc_now(),
        "symbol": symbol,
        "secid": secid_for_symbol(symbol),
        "source_url_or_reference": source_url,
        "failure_mode": failure_mode,
        "raw_response_available": False,
        "candidate_only": True,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_baostock_sample(context: phase2.ConnectorContext) -> dict[str, Any]:
    import baostock as bs

    source_id = "baostock_daily"
    rows = []
    login = bs.login()
    if login.error_code != "0":
        return {"status": "failed", "records": [], "error_message": login.error_msg}
    try:
        for symbol in SYMBOLS:
            code = f"sh.{symbol}" if symbol.startswith("6") else f"sz.{symbol}"
            rs = bs.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,preclose,volume,amount,pctChg",
                start_date=(date.today() - timedelta(days=70)).isoformat(),
                end_date=date.today().isoformat(),
                frequency="d",
                adjustflag="3",
            )
            symbol_rows = []
            while rs.error_code == "0" and rs.next():
                symbol_rows.append(dict(zip(rs.fields, rs.get_row_data())))
            rows.extend(symbol_rows[-30:])
    finally:
        bs.logout()
    raw = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    raw_path, checksum = phase2.save_raw(context, source_id, "baostock_eastmoney_validation_daily_30d.json", raw)
    records = []
    for row in rows:
        code = row.get("code", "")
        records.append(
            {
                "trade_date": row.get("date", ""),
                "date": row.get("date", ""),
                "symbol": code.split(".")[-1],
                "market": "SH" if code.startswith("sh.") else "SZ",
                "open": phase2.to_float(row.get("open")),
                "high": phase2.to_float(row.get("high")),
                "low": phase2.to_float(row.get("low")),
                "close": phase2.to_float(row.get("close")),
                "preclose": phase2.to_float(row.get("preclose")),
                "volume": phase2.to_float(row.get("volume")),
                "amount": phase2.to_float(row.get("amount")),
                "pct_change": phase2.to_float(row.get("pctChg")),
                "source_id": source_id,
                "retrieved_at": phase2.utc_now(),
                "raw_checksum": checksum,
                "volume_unit_normalized": "shares",
                "amount_unit_normalized": "CNY",
            }
        )
    path = Path(context.storage_paths["structured_data_root"]) / "market_data" / "a_share_daily" / "baostock_daily_30d_validation_sample.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records), encoding="utf-8")
    return {"status": "success" if records else "failed", "records": records, "raw_output_path": str(raw_path), "normalized_output_path": str(path)}


def validate_eastmoney_vs_baostock(eastmoney: dict[str, Any], baostock: dict[str, Any]) -> dict[str, Any]:
    east_by_key = {(row["symbol"], row["trade_date"]): row for row in eastmoney.get("normalized_records", [])}
    bao_by_key = {(row["symbol"], row["trade_date"]): row for row in baostock.get("records", [])}
    all_keys = sorted(set(east_by_key) | set(bao_by_key))
    comparisons = []
    summary = CounterLike()
    for key in all_keys:
        east = east_by_key.get(key)
        bao = bao_by_key.get(key)
        if not east or not bao:
            status = "missing_in_source"
            summary.add(status)
            comparisons.append({"symbol": key[0], "trade_date": key[1], "status": status, "missing_source": "eastmoney" if not east else "baostock"})
            continue
        field_results = {}
        for field in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
            field_results[field] = compare_number(east.get(field), bao.get(field), field)
        if all(result["status"] == "exact_match" for result in field_results.values()):
            status = "exact_match"
        elif all(result["status"] in {"exact_match", "numeric_tolerance_match", "unit_difference_note"} for result in field_results.values()):
            status = "numeric_tolerance_match"
        else:
            status = "mismatch"
        summary.add(status)
        comparisons.append({"symbol": key[0], "trade_date": key[1], "status": status, "field_results": field_results})
    staging_status = "consumption_grade_staging_candidate" if summary.counts.get("mismatch", 0) == 0 and summary.counts.get("numeric_tolerance_match", 0) else "review_candidate"
    return {
        "generated_at": phase2.utc_now(),
        "baostock_status": baostock.get("status", ""),
        "eastmoney_status": eastmoney.get("overall_status", ""),
        "summary": summary.counts,
        "comparison_count": len(comparisons),
        "staging_status": staging_status,
        "trust_status": {
            "baostock": "candidate_external_data / operational_fallback",
            "eastmoney_direct": "candidate_external_data / secondary_validation_source",
            "akshare": "optional_retry_source",
            "cross_validated": "consumption_grade_staging_candidate_not_formal_trusted",
        },
        "unit_difference_note": "Eastmoney f56 volume is lots; connector normalizes to shares by multiplying by 100 before comparison. Amount is treated as CNY/yuan in both sources.",
        "comparisons": comparisons,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def compare_number(left: Any, right: Any, field: str) -> dict[str, Any]:
    if left is None or right is None:
        return {"status": "missing_in_source", "eastmoney": left, "baostock": right}
    left_f = float(left)
    right_f = float(right)
    diff = abs(left_f - right_f)
    tolerance = 1e-4 if field != "amount" else 1.0
    if diff == 0:
        status = "exact_match"
    elif diff <= tolerance:
        status = "numeric_tolerance_match"
    elif field == "volume" and abs(left_f / 100 - right_f) <= 1:
        status = "unit_difference_note"
    else:
        status = "mismatch"
    return {"status": status, "eastmoney": left, "baostock": right, "abs_diff": diff}


class CounterLike:
    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)

    def add(self, key: str) -> None:
        self.counts[key] += 1


def build_akshare_final_status() -> dict[str, Any]:
    prior_path = OUTPUT_ROOT / "akshare_repair_results.json"
    prior = phase2.read_json(prior_path) if prior_path.exists() else {}
    return {
        "generated_at": phase2.utc_now(),
        "status": "optional_retry_source",
        "pipeline_role": "non_blocking_optional_retry",
        "reason": "Manual network diagnosis confirmed Eastmoney DIRECT routing but upstream still returns empty/remote-disconnected responses; AKShare depends on Eastmoney upstream and is not suitable as the sole A-share daily path.",
        "last_known_akshare_status": prior.get("overall_status", "unknown"),
        "blocks_a_share_daily_pipeline": False,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def sanitize_url(url: str) -> str:
    return url


def render_report(eastmoney: dict[str, Any], validation: dict[str, Any], akshare: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {item['symbol']} | {item['status']} | {item['record_count']} | {item.get('http_status','')} | {item.get('failure_mode','')} | {item.get('raw_output_path','')} |"
        for item in eastmoney["items"]
    )
    return f"""# Eastmoney Direct Connector Fallback Report

## Scope

Small-sample A-share daily connector fallback only. No full download, no OpenAI API, no parse_lab change, and no formal trusted-consumption integration.

## Eastmoney Direct Connector

| Symbol | Status | Records | HTTP | Failure mode | Raw output |
|---|---:|---:|---|---|---|
{rows}

- total normalized records: {eastmoney['total_normalized_records']}
- normalized output: `{eastmoney['normalized_output_path']}`
- runtime mirror: `{eastmoney['runtime_mirror_path']}`

## Kline Field Order

The connector requests `fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61` and parses:

1. f51 trade_date
2. f52 open
3. f53 close
4. f54 high
5. f55 low
6. f56 volume, original unit lots where 1 lot = 100 shares
7. f57 amount, CNY/yuan
8. f58 amplitude percent
9. f59 pct_change percent
10. f60 change_amount
11. f61 turnover_rate percent

## Baostock vs Eastmoney Validation

```json
{json.dumps(validation['summary'], ensure_ascii=False, indent=2)}
```

- staging status: {validation['staging_status']}
- unit note: {validation['unit_difference_note']}

## AKShare Final Status

- status: {akshare['status']}
- role: {akshare['pipeline_role']}
- reason: {akshare['reason']}

## Trust Status

- Baostock: candidate_external_data / operational_fallback
- Eastmoney direct: candidate_external_data / secondary_validation_source
- AKShare: optional_retry_source
- Cross-validated data: consumption_grade_staging_candidate only, not formal trusted consumption
"""


def main() -> int:
    summary = run_eastmoney_direct_fallback()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
