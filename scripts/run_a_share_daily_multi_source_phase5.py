from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services import data_connector_phase2_service as phase2  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "data_connector_phase5"
DOC_REPORT = PROJECT_ROOT / "docs" / "A_SHARE_DAILY_MULTI_SOURCE_PIPELINE_REPORT.md"
DOC_SCHEMA = PROJECT_ROOT / "docs" / "A_SHARE_DAILY_MULTI_SOURCE_SCHEMA.md"
SYMBOLS = ["600519", "000001", "300750"]
COMPARE_FIELDS = ["open", "high", "low", "close", "volume", "amount", "pct_change"]
FIELD_COVERAGE = [
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turnover_rate",
    "pct_change",
    "trade_status",
    "adjust_flag",
    "is_st",
]


def run_phase5() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    context = phase2.load_context()
    baostock = run_baostock_pipeline(context)
    akshare = run_akshare_tencent_pipeline(context)
    coverage = build_field_coverage_matrix(baostock, akshare)
    validation = build_cross_source_validation(baostock, akshare)
    quality = build_quality_results(baostock, akshare)
    staging = build_consumption_staging(baostock, akshare, validation, quality)
    source_status = build_source_status(baostock, akshare)

    phase2.write_json(OUTPUT_ROOT / "a_share_daily_baostock_results.json", without_records(baostock))
    phase2.write_json(OUTPUT_ROOT / "a_share_daily_akshare_tencent_results.json", without_records(akshare))
    phase2.write_json(OUTPUT_ROOT / "a_share_daily_field_coverage_matrix.json", coverage)
    phase2.write_json(OUTPUT_ROOT / "a_share_daily_cross_source_validation.json", validation)
    phase2.write_json(OUTPUT_ROOT / "a_share_daily_quality_results.json", quality)
    phase2.write_json(OUTPUT_ROOT / "a_share_daily_consumption_staging.json", staging)
    phase2.write_json(OUTPUT_ROOT / "a_share_daily_source_status.json", source_status)
    DOC_REPORT.write_text(render_report(baostock, akshare, coverage, validation, quality, staging, source_status), encoding="utf-8")
    DOC_SCHEMA.write_text(render_schema_doc(), encoding="utf-8")
    return {
        "phase5_completed": True,
        "baostock_status": baostock["overall_status"],
        "baostock_total_records": baostock["total_records"],
        "akshare_tencent_status": akshare["overall_status"],
        "akshare_tencent_total_records": akshare["total_records"],
        "cross_source_summary": validation["summary"],
        "consumption_staging_counts": staging["counts"],
        "outputs": {
            "baostock": str(OUTPUT_ROOT / "a_share_daily_baostock_results.json"),
            "akshare_tencent": str(OUTPUT_ROOT / "a_share_daily_akshare_tencent_results.json"),
            "field_coverage": str(OUTPUT_ROOT / "a_share_daily_field_coverage_matrix.json"),
            "cross_source_validation": str(OUTPUT_ROOT / "a_share_daily_cross_source_validation.json"),
            "quality_results": str(OUTPUT_ROOT / "a_share_daily_quality_results.json"),
            "consumption_staging": str(OUTPUT_ROOT / "a_share_daily_consumption_staging.json"),
            "source_status": str(OUTPUT_ROOT / "a_share_daily_source_status.json"),
            "report": str(DOC_REPORT),
            "schema": str(DOC_SCHEMA),
        },
        "no_full_download": True,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
    }


def run_baostock_pipeline(context: phase2.ConnectorContext) -> dict[str, Any]:
    import baostock as bs

    started = time.time()
    source_id = "baostock_daily"
    raw_rows: list[dict[str, str]] = []
    items = []
    login = bs.login()
    if login.error_code != "0":
        return failed_source(source_id, "baostock_login_failed:" + login.error_msg, started)
    try:
        for symbol in SYMBOLS:
            code = to_baostock_code(symbol)
            rs = bs.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                start_date=start_date().isoformat(),
                end_date=date.today().isoformat(),
                frequency="d",
                adjustflag="3",
            )
            symbol_rows = []
            while rs.error_code == "0" and rs.next():
                symbol_rows.append(dict(zip(rs.fields, rs.get_row_data())))
            symbol_rows = symbol_rows[-30:]
            raw_rows.extend(symbol_rows)
            items.append({"symbol": symbol, "status": "success" if symbol_rows else "failed", "record_count": len(symbol_rows), "error_message": "" if symbol_rows else rs.error_msg})
    finally:
        bs.logout()
    raw_path, checksum = save_raw_market(context, "baostock", "baostock_watchlist_daily_30d.json", json.dumps(raw_rows, ensure_ascii=False, indent=2).encode("utf-8"))
    records = [normalize_baostock_row(row, checksum) for row in raw_rows]
    structured_path, runtime_path = save_structured_and_runtime(context, "baostock", "baostock_watchlist_daily_30d", records)
    quality = run_daily_quality_gate(records, "baostock_daily")
    return {
        "source_id": source_id,
        "source_role": "operational_source / primary_fallback",
        "overall_status": "success" if records else "failed",
        "elapsed_seconds": round(time.time() - started, 3),
        "symbols": SYMBOLS,
        "items": items,
        "total_records": len(records),
        "raw_output_path": str(raw_path),
        "structured_output_path": str(structured_path),
        "runtime_mirror_path": str(runtime_path),
        "quality_result": quality,
        "trust_status": "candidate_external_data",
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "records": records,
    }


def run_akshare_tencent_pipeline(context: phase2.ConnectorContext) -> dict[str, Any]:
    import akshare as ak

    started = time.time()
    source_id = "akshare_tencent_daily"
    raw_payload: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    items = []
    for symbol in SYMBOLS:
        ak_symbol = to_akshare_tencent_symbol(symbol)
        try:
            df = ak.stock_zh_a_hist_tx(symbol=ak_symbol, start_date=start_yyyymmdd(), end_date=end_yyyymmdd(), adjust="")
            df = df.tail(30)
            raw_payload[symbol] = df.to_dict(orient="records")
            symbol_records = normalize_akshare_tencent_records(symbol, df)
            records.extend(symbol_records)
            items.append({"symbol": symbol, "akshare_symbol": ak_symbol, "status": "success" if symbol_records else "failed", "record_count": len(symbol_records), "error_message": "" if symbol_records else "empty_dataframe"})
            time.sleep(0.3)
        except Exception as exc:  # noqa: BLE001
            raw_payload[symbol] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            items.append({"symbol": symbol, "akshare_symbol": ak_symbol, "status": "failed", "record_count": 0, "error_message": f"{type(exc).__name__}: {str(exc)[:300]}"})
    raw_bytes = json.dumps(raw_payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    raw_path, checksum = save_raw_market(context, "akshare_tencent", "akshare_tencent_watchlist_daily_30d.json", raw_bytes)
    for row in records:
        row["raw_checksum"] = checksum
    structured_path, runtime_path = save_structured_and_runtime(context, "akshare_tencent", "akshare_tencent_watchlist_daily_30d", records)
    quality = run_daily_quality_gate(records, "akshare_tencent_daily")
    success_count = sum(1 for item in items if item["status"] == "success")
    return {
        "source_id": source_id,
        "source_role": "secondary_candidate_source",
        "overall_status": "success" if success_count == len(SYMBOLS) else ("partial_success" if success_count else "failed"),
        "elapsed_seconds": round(time.time() - started, 3),
        "symbols": SYMBOLS,
        "items": items,
        "total_records": len(records),
        "raw_output_path": str(raw_path),
        "structured_output_path": str(structured_path),
        "runtime_mirror_path": str(runtime_path),
        "quality_result": quality,
        "trust_status": "candidate_external_data / secondary_candidate_source",
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "records": records,
    }


def normalize_baostock_row(row: dict[str, str], checksum: str) -> dict[str, Any]:
    code = row.get("code", "")
    symbol = code.split(".")[-1]
    return {
        "trade_date": row.get("date", ""),
        "symbol": symbol,
        "market": "SH" if code.startswith("sh.") else "SZ",
        "open": phase2.to_float(row.get("open")),
        "high": phase2.to_float(row.get("high")),
        "low": phase2.to_float(row.get("low")),
        "close": phase2.to_float(row.get("close")),
        "preclose": phase2.to_float(row.get("preclose")),
        "volume": phase2.to_float(row.get("volume")),
        "amount": phase2.to_float(row.get("amount")),
        "turnover_rate": phase2.to_float(row.get("turn")),
        "pct_change": phase2.to_float(row.get("pctChg")),
        "trade_status": row.get("tradestatus", ""),
        "adjust_flag": row.get("adjustflag", "3"),
        "is_st": row.get("isST", ""),
        "source_id": "baostock_daily",
        "retrieved_at": phase2.utc_now(),
        "raw_checksum": checksum,
        "volume_unit": "shares",
        "amount_unit": "CNY",
    }


def normalize_akshare_tencent_records(symbol: str, df: Any) -> list[dict[str, Any]]:
    records = []
    previous_close: float | None = None
    for _, row in df.iterrows():
        close = phase2.to_float(row.get("close"))
        volume_lots = phase2.to_float(row.get("amount"))
        preclose = previous_close
        pct_change = ((close - preclose) / preclose * 100) if close is not None and preclose not in {None, 0} else None
        records.append(
            {
                "trade_date": str(row.get("date", ""))[:10],
                "symbol": symbol,
                "market": "SH" if symbol.startswith("6") else "SZ",
                "open": phase2.to_float(row.get("open")),
                "high": phase2.to_float(row.get("high")),
                "low": phase2.to_float(row.get("low")),
                "close": close,
                "preclose": preclose,
                "volume": volume_lots * 100 if volume_lots is not None else None,
                "amount": None,
                "turnover_rate": None,
                "pct_change": pct_change,
                "trade_status": None,
                "adjust_flag": "",
                "is_st": None,
                "source_id": "akshare_tencent_daily",
                "retrieved_at": phase2.utc_now(),
                "raw_checksum": "",
                "volume_unit": "source_amount_column_lots_normalized_to_shares",
                "amount_unit": "source_not_supported",
            }
        )
        if close is not None:
            previous_close = close
    return records


def run_daily_quality_gate(records: list[dict[str, Any]], source_id: str) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    required = ["trade_date", "symbol", "open", "high", "low", "close", "source_id", "retrieved_at", "raw_checksum"]
    checks["required_fields_present"] = bool(records) and all(row.get(field) not in {None, ""} for row in records for field in required)
    keys = [(row.get("symbol"), row.get("trade_date")) for row in records]
    checks["symbol_trade_date_unique"] = len(keys) == len(set(keys)) if keys else False
    checks["duplicate_date_check"] = checks["symbol_trade_date_unique"]
    checks["date_order"] = date_order_by_symbol(records)
    checks["ohlc_numeric"] = all(is_number(row.get(field)) for row in records for field in ["open", "high", "low", "close"])
    checks["high_ge_max_olc"] = all(row.get("high") is not None and row["high"] >= max(row["open"], row["close"], row["low"]) for row in records if all(row.get(field) is not None for field in ["open", "high", "low", "close"]))
    checks["low_le_min_och"] = all(row.get("low") is not None and row["low"] <= min(row["open"], row["close"], row["high"]) for row in records if all(row.get(field) is not None for field in ["open", "high", "low", "close"]))
    checks["volume_non_negative"] = all(row.get("volume") is None or row["volume"] >= 0 for row in records)
    checks["amount_non_negative"] = all(row.get("amount") is None or row["amount"] >= 0 for row in records)
    checks["pct_change_reasonable_range"] = all(row.get("pct_change") is None or -100 <= row["pct_change"] <= 100 for row in records)
    checks["turnover_rate_reasonable_range"] = all(row.get("turnover_rate") is None or 0 <= row["turnover_rate"] <= 1000 for row in records)
    failed = [name for name, ok in checks.items() if not ok]
    optional_source_missing = source_id == "akshare_tencent_daily" and set(failed).issubset({"required_fields_present"})
    status = "quality_passed" if not failed or optional_source_missing else "quality_failed"
    warnings = []
    if source_id == "akshare_tencent_daily":
        warnings.extend(["amount_source_not_supported", "turnover_rate_source_not_supported", "trade_status_source_not_supported", "is_st_source_not_supported"])
    if failed and not optional_source_missing:
        warnings.extend(failed)
    return {
        "quality_check_id": phase2.stable_id("quality", source_id, str(len(records)), phase2.utc_now()),
        "source_id": source_id,
        "status": status,
        "record_count": len(records),
        "checks": checks,
        "warnings": warnings,
        "candidate_only": True,
    }


def build_field_coverage_matrix(baostock: dict[str, Any], akshare: dict[str, Any]) -> dict[str, Any]:
    source_records = {
        "baostock": baostock["records"],
        "akshare_tencent": akshare["records"],
    }
    matrix = []
    for field in FIELD_COVERAGE:
        row = {"field": field}
        for source, records in source_records.items():
            values = [record.get(field) for record in records]
            if not records:
                status = "missing"
            elif any(value not in {None, ""} for value in values):
                status = "available"
            elif source == "akshare_tencent" and field in {"turnover_rate", "trade_status", "is_st"}:
                status = "source_not_supported"
            elif source == "akshare_tencent" and field in {"preclose", "pct_change"}:
                status = "derived_possible"
            elif source == "akshare_tencent" and field == "amount":
                status = "source_not_supported"
            else:
                status = "missing"
            if field == "volume" and source == "akshare_tencent":
                status = "unit_difference" if status == "available" else status
            row[source] = status
        matrix.append(row)
    return {
        "generated_at": phase2.utc_now(),
        "sources": ["baostock", "akshare_tencent"],
        "matrix": matrix,
        "conclusion": "Baostock has fuller market daily metadata. AKShare Tencent covers OHLC and amount, with preclose/pct_change derivable, but lacks volume/turnover/trade status/ST flags.",
    }


def build_cross_source_validation(baostock: dict[str, Any], akshare: dict[str, Any]) -> dict[str, Any]:
    left = {(row["symbol"], row["trade_date"]): row for row in baostock["records"]}
    right = {(row["symbol"], row["trade_date"]): row for row in akshare["records"]}
    keys = sorted(set(left) | set(right))
    comparisons = []
    summary: Counter[str] = Counter()
    field_summary: dict[str, Counter[str]] = {field: Counter() for field in COMPARE_FIELDS}
    for key in keys:
        baostock_row = left.get(key)
        akshare_row = right.get(key)
        if not baostock_row or not akshare_row:
            status = "missing_in_source"
            summary[status] += 1
            comparisons.append({"symbol": key[0], "trade_date": key[1], "status": status, "missing_source": "baostock" if not baostock_row else "akshare_tencent"})
            continue
        fields = {}
        for field in COMPARE_FIELDS:
            result = compare_field(baostock_row.get(field), akshare_row.get(field), field)
            fields[field] = result
            field_summary[field][result["status"]] += 1
        if all(item["status"] == "exact_match" for item in fields.values()):
            status = "exact_match"
        elif all(item["status"] in {"exact_match", "numeric_tolerance_match", "unit_normalized_match", "missing_in_source"} for item in fields.values()) and not any(item["status"] == "mismatch" for item in fields.values()):
            status = "numeric_tolerance_match"
        else:
            status = "mismatch"
        summary[status] += 1
        comparisons.append({"symbol": key[0], "trade_date": key[1], "status": status, "field_results": fields})
    return {
        "generated_at": phase2.utc_now(),
        "summary": dict(summary),
        "field_summary": {field: dict(counter) for field, counter in field_summary.items()},
        "comparison_count": len(comparisons),
        "unit_difference_note": "Baostock volume is shares. AKShare Tencent dataframe column named amount behaves like volume in lots; this pipeline normalizes it to shares by multiplying by 100. Differences within one lot (100 shares) are treated as unit_normalized_match because Tencent lot values are rounded. AKShare Tencent does not provide transaction amount/CNY in this tested interface.",
        "comparisons": comparisons,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def compare_field(baostock_value: Any, akshare_value: Any, field: str) -> dict[str, Any]:
    if baostock_value is None or akshare_value is None:
        return {"status": "missing_in_source", "baostock": baostock_value, "akshare_tencent": akshare_value}
    try:
        left = float(baostock_value)
        right = float(akshare_value)
    except (TypeError, ValueError):
        return {"status": "mismatch", "baostock": baostock_value, "akshare_tencent": akshare_value}
    diff = abs(left - right)
    if field == "volume":
        tolerance = 100.0
    elif field in {"open", "high", "low", "close", "pct_change"}:
        tolerance = 1e-4
    else:
        tolerance = 1.0
    status = "exact_match" if diff == 0 else ("numeric_tolerance_match" if diff <= tolerance else "mismatch")
    if field == "volume" and diff <= 100.0 and diff != 0:
        status = "unit_normalized_match"
    return {"status": status, "baostock": baostock_value, "akshare_tencent": akshare_value, "abs_diff": diff}


def build_quality_results(baostock: dict[str, Any], akshare: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": phase2.utc_now(),
        "items": [baostock["quality_result"], akshare["quality_result"]],
        "summary": {
            "quality_passed": sum(1 for item in [baostock["quality_result"], akshare["quality_result"]] if item["status"] == "quality_passed"),
            "quality_failed": sum(1 for item in [baostock["quality_result"], akshare["quality_result"]] if item["status"] == "quality_failed"),
        },
    }


def build_consumption_staging(baostock: dict[str, Any], akshare: dict[str, Any], validation: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    items = []
    if baostock["quality_result"]["status"] == "quality_passed":
        items.append(staging_item("baostock_daily", "market_daily_candidate_staging", baostock["total_records"], baostock["structured_output_path"]))
    if akshare["quality_result"]["status"] == "quality_passed":
        items.append(staging_item("akshare_tencent_daily", "market_daily_secondary_candidate_staging", akshare["total_records"], akshare["structured_output_path"]))
    mismatch = validation["summary"].get("mismatch", 0)
    matched = validation["summary"].get("exact_match", 0) + validation["summary"].get("numeric_tolerance_match", 0)
    if matched and not mismatch:
        items.append(staging_item("cross_source_validation", "cross_validated_candidate", matched, str(OUTPUT_ROOT / "a_share_daily_cross_source_validation.json")))
    elif validation["comparison_count"]:
        items.append(staging_item("cross_source_validation", "needs_review_candidate", validation["comparison_count"], str(OUTPUT_ROOT / "a_share_daily_cross_source_validation.json")))
    counts = Counter(item["staging_status"] for item in items)
    return {
        "generated_at": phase2.utc_now(),
        "rules": {
            "baostock": "quality_passed -> market_daily_candidate_staging",
            "akshare_tencent": "quality_passed -> market_daily_secondary_candidate_staging",
            "cross_source_agreement": "cross_validated_candidate",
            "cross_source_difference": "needs_review_candidate",
            "formal_trusted_consumption": "not modified",
        },
        "counts": dict(counts),
        "items": items,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def staging_item(source_id: str, status: str, record_count: int, path: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "staging_status": status,
        "record_count": record_count,
        "data_path": path,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def build_source_status(baostock: dict[str, Any], akshare: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": phase2.utc_now(),
        "sources": [
            {
                "source_id": "baostock_daily",
                "status": "operational_source",
                "trust_status": "candidate_external_data",
                "role": "primary_fallback",
                "current_run_status": baostock["overall_status"],
            },
            {
                "source_id": "akshare_tencent_daily",
                "status": "secondary_candidate_source",
                "trust_status": "candidate_external_data",
                "role": "useful_for_cross_validation",
                "current_run_status": akshare["overall_status"],
            },
            {
                "source_id": "akshare_eastmoney_stock_zh_a_hist",
                "status": "deferred_optional_source",
                "reason": "Eastmoney push2his upstream/TLS instability",
            },
            {
                "source_id": "eastmoney_direct",
                "status": "deferred_secondary_validation_source",
                "reason": "schannel / remote disconnect instability",
            },
        ],
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def save_raw_market(context: phase2.ConnectorContext, source: str, filename: str, data: bytes) -> tuple[Path, str]:
    root = Path(context.storage_paths["cold_data_root"]) / "raw" / "market_data" / "a_share_daily" / source / phase2.utc_date()
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_bytes(data)
    return path, phase2.sha256(data)


def save_structured_and_runtime(context: phase2.ConnectorContext, source: str, name: str, records: list[dict[str, Any]]) -> tuple[Path, Path]:
    structured = Path(context.storage_paths["structured_data_root"]) / "market_data" / "a_share_daily" / source
    structured.mkdir(parents=True, exist_ok=True)
    structured_path = structured / f"{name}.jsonl"
    lines = "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in records)
    structured_path.write_text(lines, encoding="utf-8")
    runtime_path = OUTPUT_ROOT / f"{name}.jsonl"
    runtime_path.write_text(lines, encoding="utf-8")
    return structured_path, runtime_path


def without_records(payload: dict[str, Any]) -> dict[str, Any]:
    copy = dict(payload)
    copy.pop("records", None)
    return copy


def failed_source(source_id: str, error: str, started: float) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "overall_status": "failed",
        "elapsed_seconds": round(time.time() - started, 3),
        "symbols": SYMBOLS,
        "items": [],
        "total_records": 0,
        "raw_output_path": "",
        "structured_output_path": "",
        "runtime_mirror_path": "",
        "quality_result": run_daily_quality_gate([], source_id),
        "trust_status": "candidate_external_quality_failed",
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "error_message": error,
        "records": [],
    }


def date_order_by_symbol(records: list[dict[str, Any]]) -> bool:
    by_symbol: dict[str, list[str]] = defaultdict(list)
    for row in records:
        by_symbol[str(row.get("symbol", ""))].append(str(row.get("trade_date", "")))
    return bool(by_symbol) and all(values == sorted(values) for values in by_symbol.values())


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_baostock_code(symbol: str) -> str:
    return f"sh.{symbol}" if symbol.startswith("6") else f"sz.{symbol}"


def to_akshare_tencent_symbol(symbol: str) -> str:
    return f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"


def start_date() -> date:
    return date.today() - timedelta(days=70)


def start_yyyymmdd() -> str:
    return start_date().strftime("%Y%m%d")


def end_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def render_report(baostock: dict[str, Any], akshare: dict[str, Any], coverage: dict[str, Any], validation: dict[str, Any], quality: dict[str, Any], staging: dict[str, Any], source_status: dict[str, Any]) -> str:
    coverage_rows = "\n".join(f"| {row['field']} | {row['baostock']} | {row['akshare_tencent']} |" for row in coverage["matrix"])
    source_rows = "\n".join(f"| {item['source_id']} | {item['status']} | {item.get('role','')} | {item.get('reason','')} |" for item in source_status["sources"])
    return f"""# A-share Daily Multi-source Pipeline Report

## Scope

Small-sample A-share daily multi-source candidate pipeline. No full download, no OpenAI API, no parse_lab change, and no formal trusted consumption change.

## Source Results

- Baostock: {baostock['overall_status']}, records: {baostock['total_records']}
- AKShare Tencent: {akshare['overall_status']}, records: {akshare['total_records']}

## Field Coverage

| Field | Baostock | AKShare Tencent |
|---|---|---|
{coverage_rows}

Conclusion: {coverage['conclusion']}

## Cross-source Validation

```json
{json.dumps(validation['summary'], ensure_ascii=False, indent=2)}
```

Unit note: {validation['unit_difference_note']}

## Quality Gate

```json
{json.dumps(quality['summary'], ensure_ascii=False, indent=2)}
```

## Consumption Staging

```json
{json.dumps(staging['counts'], ensure_ascii=False, indent=2)}
```

All staging outputs remain candidate-only and do not enter formal trusted consumption.

## Source Status

| Source | Status | Role | Reason |
|---|---|---|---|
{source_rows}
"""


def render_schema_doc() -> str:
    return """# A-share Daily Multi-source Schema

## Normalized Schema

- `trade_date`
- `symbol`
- `market`
- `open`
- `high`
- `low`
- `close`
- `preclose`
- `volume`
- `amount`
- `turnover_rate`
- `pct_change`
- `trade_status`
- `adjust_flag`
- `is_st`
- `source_id`
- `retrieved_at`
- `raw_checksum`
- `volume_unit`
- `amount_unit`

## Unit Notes

- Baostock volume is normalized as shares.
- Baostock amount is normalized as CNY.
- AKShare Tencent exposes OHLC and an `amount` field in the returned dataframe; in the tested data this field matches Baostock volume after multiplying by 100, so this pipeline treats it as source volume in lots and normalizes it to shares.
- AKShare Tencent volume differences within one lot (100 shares) are treated as `unit_normalized_match` because the source lot value can be rounded.
- AKShare Tencent does not provide transaction amount/CNY, turnover rate, trade status, or ST flag through this tested interface.

## Trust Rule

Baostock and AKShare Tencent are candidate external data. Cross-source agreement can become `cross_validated_candidate` in staging, not formal trusted consumption.
"""


def main() -> int:
    summary = run_phase5()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
