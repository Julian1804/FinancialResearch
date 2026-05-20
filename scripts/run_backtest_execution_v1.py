from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


REPORT_ROOT = PROJECT_ROOT / "runtime" / "analysis_reports"
BACKTEST_QUEUE_ROOT = PROJECT_ROOT / "runtime" / "backtest_queue"
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "backtest_execution_v1"
WORKSPACE_ROOT = PROJECT_ROOT / "runtime" / "research_workspace"
PHASE6_ROOT = PROJECT_ROOT / "runtime" / "frdata_connectors_phase6"
BAOSTOCK_DAILY_PATH = Path("Z:/data_lake_master/structured/market_data/a_share_daily/baostock_daily/baostock_watchlist_controlled_30d.jsonl")
AKSHARE_TENCENT_DAILY_PATH = Path("Z:/data_lake_master/structured/market_data/a_share_daily/akshare_tencent_daily/akshare_tencent_watchlist_controlled_30d.jsonl")

DOC_BACKTEST = PROJECT_ROOT / "docs" / "BACKTEST_EXECUTION_V1_REPORT.md"
DOC_WORKSPACE = PROJECT_ROOT / "docs" / "RESEARCH_WORKSPACE_INDEX.md"
DOC_REVISION = PROJECT_ROOT / "docs" / "FORECAST_REVISION_WORKFLOW.md"

TESTABLE_DIRECTIONS = {"up", "down", "flat"}


def run_backtest_execution_v1(only_testable: bool = False) -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    BACKTEST_QUEUE_ROOT.mkdir(parents=True, exist_ok=True)

    forecasts = load_all_forecasts()
    original_queue = read_json(BACKTEST_QUEUE_ROOT / "pending_backtest_queue.json") if (BACKTEST_QUEUE_ROOT / "pending_backtest_queue.json").exists() else {"items": []}
    if only_testable:
        forecasts = [forecast for forecast in forecasts if is_testable_forecast(forecast)]
    results = [execute_forecast_backtest(forecast) for forecast in forecasts]
    if only_testable:
        summary = build_report_backtest_summary(results)
        write_json(OUTPUT_ROOT / "backtest_results_testable_only.json", {"generated_at": utc_now(), "items": results})
        write_json(OUTPUT_ROOT / "report_backtest_summary_testable_only.json", summary)
        return {
            "backtest_execution_v1_completed": True,
            "forecast_count": len(forecasts),
            "only_testable": True,
            "result_counts": summary["result_counts"],
            "non_destructive_output": True,
            "cli_available": True,
            "no_openai_api_called": True,
            "parse_lab_affected": False,
            "trusted_consumption_affected": False,
            "outputs": {
                "backtest_results_testable_only": str(OUTPUT_ROOT / "backtest_results_testable_only.json"),
                "report_backtest_summary_testable_only": str(OUTPUT_ROOT / "report_backtest_summary_testable_only.json"),
            },
        }
    updated_forecasts = merge_forecasts_with_results(forecasts, results)
    updated_queue = build_updated_pending_queue(results)
    revision_candidates = build_revision_candidates(updated_forecasts, results)
    report_summary = build_report_backtest_summary(results)
    workspace_index = build_research_workspace_index(updated_forecasts, results, revision_candidates)

    write_json(OUTPUT_ROOT / "backtest_results.json", {"generated_at": utc_now(), "items": results})
    write_json(OUTPUT_ROOT / "forecast_items_updated.json", {"generated_at": utc_now(), "items": updated_forecasts})
    write_json(OUTPUT_ROOT / "report_backtest_summary.json", report_summary)
    write_json(OUTPUT_ROOT / "pending_backtest_queue_updated.json", updated_queue)
    write_json(OUTPUT_ROOT / "revision_candidates.json", revision_candidates)
    write_json(WORKSPACE_ROOT / "research_workspace_index.json", workspace_index)
    write_symbol_exports(workspace_index)
    DOC_BACKTEST.write_text(render_backtest_doc(report_summary), encoding="utf-8")
    DOC_WORKSPACE.write_text(render_workspace_doc(workspace_index), encoding="utf-8")
    DOC_REVISION.write_text(render_revision_doc(revision_candidates), encoding="utf-8")

    return {
        "backtest_execution_v1_completed": True,
        "forecast_count": len(forecasts),
        "only_testable": only_testable,
        "original_queue_count": len(original_queue.get("items", [])),
        "result_counts": report_summary["result_counts"],
        "research_workspace_index_completed": True,
        "revision_candidate_count": revision_candidates["candidate_count"],
        "cli_available": True,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "outputs": {
            "backtest_execution": str(OUTPUT_ROOT),
            "research_workspace": str(WORKSPACE_ROOT),
            "backtest_results": str(OUTPUT_ROOT / "backtest_results.json"),
            "workspace_index": str(WORKSPACE_ROOT / "research_workspace_index.json"),
            "revision_candidates": str(OUTPUT_ROOT / "revision_candidates.json"),
            "backtest_doc": str(DOC_BACKTEST),
            "workspace_doc": str(DOC_WORKSPACE),
            "revision_doc": str(DOC_REVISION),
        },
    }


def execute_forecast_backtest(forecast: dict[str, Any]) -> dict[str, Any]:
    actual = lookup_actual_data(
        symbol=forecast.get("target_symbol"),
        metric=forecast.get("target_metric"),
        review_date=forecast.get("review_date"),
    )
    base = lookup_actual_data(
        symbol=forecast.get("target_symbol"),
        metric=forecast.get("target_metric"),
        review_date=forecast.get("as_of_date"),
    )
    if actual["status"] != "available":
        result = "insufficient_actual_data"
        reason = actual.get("reason", "actual data unavailable")
    elif actual.get("quality_status") != "quality_passed":
        result = "insufficient_actual_data"
        reason = "actual_data_quality_not_passed"
    else:
        result, reason = evaluate_forecast(forecast, base, actual)
    return {
        "forecast_id": forecast["forecast_id"],
        "report_id": forecast["report_id"],
        "target_symbol": forecast.get("target_symbol"),
        "as_of_date": forecast.get("as_of_date"),
        "review_date": forecast.get("review_date"),
        "target_metric": forecast.get("target_metric"),
        "forecast_type": forecast.get("forecast_type"),
        "testability_status": forecast.get("testability_status"),
        "forecast_horizon": forecast.get("forecast_horizon"),
        "expected_direction": forecast.get("expected_direction"),
        "expected_range_low": forecast.get("expected_range_low"),
        "expected_range_high": forecast.get("expected_range_high"),
        "actual_value": actual.get("value"),
        "actual_date": actual.get("actual_date"),
        "adjusted_actual_date": actual.get("adjusted_actual_date"),
        "base_value": base.get("value"),
        "base_date": base.get("actual_date"),
        "backtest_result": result,
        "backtest_reason": reason,
        "data_source_used": actual.get("source_path"),
        "quality_status": actual.get("quality_status", "unknown"),
        "candidate_only_note": "Backtest uses candidate/staging market data; GPT forecast remains interpretation, not trusted fact.",
    }


def evaluate_forecast(forecast: dict[str, Any], base: dict[str, Any], actual: dict[str, Any]) -> tuple[str, str]:
    forecast_type = str(forecast.get("forecast_type") or "").lower()
    testability_status = str(forecast.get("testability_status") or "").lower()
    if forecast_type in {"insufficient_evidence", "qualitative"} or testability_status in {"manual_review_required", "insufficient_evidence", "not_backtestable"}:
        return "manual_review_required", f"forecast_type={forecast_type or 'unspecified'} testability_status={testability_status or 'unspecified'} is not automatically backtestable"
    direction = str(forecast.get("expected_direction") or "").lower()
    low = forecast.get("expected_range_low")
    high = forecast.get("expected_range_high")
    actual_value = actual.get("value")
    base_value = base.get("value")
    if low is not None or high is not None:
        if actual_value is None:
            return "insufficient_actual_data", "actual value unavailable for price_range"
        if low is not None and actual_value < low:
            return "backtested_miss", "actual value below expected range"
        if high is not None and actual_value > high:
            return "backtested_miss", "actual value above expected range"
        return "backtested_hit", "actual value inside expected range"
    if direction in TESTABLE_DIRECTIONS:
        if actual_value is None or base_value is None:
            return "insufficient_actual_data", "actual or base value unavailable for direction test"
        diff = float(actual_value) - float(base_value)
        actual_direction = "flat" if abs(diff) < 1e-9 else ("up" if diff > 0 else "down")
        return ("backtested_hit", f"actual direction {actual_direction} matched") if actual_direction == direction else ("backtested_miss", f"actual direction {actual_direction} did not match expected {direction}")
    if direction in {"insufficient_evidence", "unknown", "not_forecasted", ""}:
        return "manual_review_required", "forecast has no testable expected direction or range"
    return "manual_review_required", "qualitative or unsupported forecast type requires manual review"


def is_testable_forecast(forecast: dict[str, Any]) -> bool:
    forecast_type = str(forecast.get("forecast_type") or "").lower()
    status = str(forecast.get("testability_status") or "").lower()
    if status == "testable":
        return True
    if forecast_type in {"price_direction", "price_range", "volume_direction", "metric_direction"}:
        direction = str(forecast.get("expected_direction") or "").lower()
        has_range = forecast.get("expected_range_low") is not None and forecast.get("expected_range_high") is not None
        return bool(forecast.get("target_metric") and forecast.get("review_date") and (direction in TESTABLE_DIRECTIONS or has_range))
    return False


def lookup_actual_data(symbol: str | None, metric: str | None, review_date: str | None) -> dict[str, Any]:
    if not symbol or not metric or not review_date:
        return {"status": "insufficient_actual_data", "reason": "missing symbol/metric/review_date"}
    quality = source_quality("baostock_daily")
    if quality != "quality_passed":
        return {"status": "insufficient_actual_data", "reason": "actual_data_quality_not_passed", "quality_status": quality}
    records = [record for record in read_jsonl(BAOSTOCK_DAILY_PATH) if str(record.get("symbol")) == str(symbol) and metric in record]
    if not records:
        return lookup_secondary_actual(symbol, metric, review_date)
    eligible = [record for record in records if str(record.get("trade_date")) <= review_date]
    if not eligible:
        return {"status": "insufficient_actual_data", "reason": "no observation on or before review_date", "quality_status": quality}
    chosen = sorted(eligible, key=lambda item: item.get("trade_date", ""))[-1]
    return {
        "status": "available",
        "value": chosen.get(metric),
        "actual_date": chosen.get("trade_date"),
        "adjusted_actual_date": chosen.get("trade_date") if chosen.get("trade_date") != review_date else None,
        "source_id": "baostock_daily",
        "source_path": str(BAOSTOCK_DAILY_PATH),
        "quality_status": quality,
    }


def lookup_secondary_actual(symbol: str, metric: str, review_date: str) -> dict[str, Any]:
    quality = source_quality("akshare_tencent_daily")
    if quality != "quality_passed":
        return {"status": "insufficient_actual_data", "reason": "secondary_actual_data_quality_not_passed", "quality_status": quality}
    records = [record for record in read_jsonl(AKSHARE_TENCENT_DAILY_PATH) if str(record.get("symbol")) == str(symbol) and metric in record and record.get(metric) is not None]
    eligible = [record for record in records if str(record.get("trade_date")) <= review_date]
    if not eligible:
        return {"status": "insufficient_actual_data", "reason": "no secondary observation on or before review_date", "quality_status": quality}
    chosen = sorted(eligible, key=lambda item: item.get("trade_date", ""))[-1]
    return {
        "status": "available",
        "value": chosen.get(metric),
        "actual_date": chosen.get("trade_date"),
        "adjusted_actual_date": chosen.get("trade_date") if chosen.get("trade_date") != review_date else None,
        "source_id": "akshare_tencent_daily",
        "source_path": str(AKSHARE_TENCENT_DAILY_PATH),
        "quality_status": quality,
    }


def source_quality(source_id: str) -> str:
    path = PHASE6_ROOT / "connector_run_results.json"
    if not path.exists():
        return "unknown"
    for item in read_json(path).get("items", []):
        if item.get("source_id") == source_id:
            return item.get("quality_check_status", "unknown")
    return "unknown"


def load_all_forecasts() -> list[dict[str, Any]]:
    forecasts: list[dict[str, Any]] = []
    for path in sorted(REPORT_ROOT.glob("*/*/v*/forecast_items.json")):
        payload = read_json(path)
        for item in payload.get("items", []):
            item = dict(item)
            item["forecast_items_path"] = str(path)
            forecasts.append(item)
    return forecasts


def merge_forecasts_with_results(forecasts: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {result["forecast_id"]: result for result in results}
    updated = []
    for forecast in forecasts:
        result = by_id.get(forecast["forecast_id"], {})
        merged = dict(forecast)
        merged.update(
            {
                "actual_value_later": result.get("actual_value"),
                "actual_date": result.get("actual_date"),
                "backtest_status": result.get("backtest_result", forecast.get("backtest_status")),
                "backtest_result": result.get("backtest_result", forecast.get("backtest_result")),
                "backtest_reason": result.get("backtest_reason"),
                "backtest_data_source_used": result.get("data_source_used"),
            }
        )
        updated.append(merged)
    return updated


def build_updated_pending_queue(results: list[dict[str, Any]]) -> dict[str, Any]:
    pending = []
    for result in results:
        if result["backtest_result"] in {"insufficient_actual_data", "manual_review_required", "inconclusive"}:
            pending.append(
                {
                    "forecast_id": result["forecast_id"],
                    "report_id": result["report_id"],
                    "target_symbol": result["target_symbol"],
                    "target_metric": result["target_metric"],
                    "review_date": result["review_date"],
                    "readiness_status": result["backtest_result"],
                    "reason": result["backtest_reason"],
                    "candidate_only_forecast": True,
                    "gpt_content_not_trusted_fact": True,
                }
            )
    payload = {"generated_at": utc_now(), "queue_count": len(pending), "items": pending}
    write_json(BACKTEST_QUEUE_ROOT / "pending_backtest_queue_updated.json", payload)
    return payload


def build_revision_candidates(forecasts: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    result_by_id = {item["forecast_id"]: item for item in results}
    candidates = []
    for forecast in forecasts:
        result = result_by_id.get(forecast["forecast_id"], {})
        if result.get("backtest_result") in {"backtested_miss", "manual_review_required", "inconclusive", "insufficient_actual_data"}:
            candidates.append(
                {
                    "forecast_id": forecast["forecast_id"],
                    "report_id": forecast["report_id"],
                    "target_symbol": forecast["target_symbol"],
                    "original_thesis": forecast.get("thesis"),
                    "backtest_result": result.get("backtest_result"),
                    "miss_reason_if_any": result.get("backtest_reason"),
                    "suggested_revision_prompt": f"Review forecast {forecast['forecast_id']} for {forecast['target_symbol']}. Keep candidate data boundaries explicit and revise only if the user agrees.",
                    "requires_user_review": True,
                    "auto_revision_performed": False,
                }
            )
    return {"generated_at": utc_now(), "candidate_count": len(candidates), "items": candidates}


def build_report_backtest_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(item["backtest_result"] for item in results)
    by_symbol: dict[str, Counter] = defaultdict(Counter)
    for item in results:
        by_symbol[item["target_symbol"]][item["backtest_result"]] += 1
    return {
        "generated_at": utc_now(),
        "forecast_count": len(results),
        "result_counts": dict(counts),
        "by_symbol": {symbol: dict(counter) for symbol, counter in by_symbol.items()},
        "candidate_only_note": "Backtest evaluates GPT/manual forecast records against candidate/staging data only; no trusted facts are created.",
    }


def build_research_workspace_index(forecasts: list[dict[str, Any]], results: list[dict[str, Any]], revisions: dict[str, Any]) -> dict[str, Any]:
    reports = collect_reports()
    packets = collect_packets()
    latest_market = latest_market_summary()
    result_by_forecast = {item["forecast_id"]: item for item in results}
    revisions_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in revisions["items"]:
        revisions_by_symbol[item["target_symbol"]].append(item)
    symbols = sorted(set([item["target_symbol"] for item in forecasts] + list(packets)))
    items = []
    for symbol in symbols:
        symbol_forecasts = [item for item in forecasts if item["target_symbol"] == symbol]
        symbol_reports = [item for item in reports if item["target_symbol"] == symbol]
        symbol_results = [result_by_forecast[item["forecast_id"]] for item in symbol_forecasts if item["forecast_id"] in result_by_forecast]
        items.append(
            {
                "target_symbol": symbol,
                "packets": packets.get(symbol, []),
                "reports": symbol_reports,
                "report_versions": [{"report_id": report["report_id"], "version": report["report_version"], "packet_id": report["packet_id"]} for report in symbol_reports],
                "forecast_items": symbol_forecasts,
                "backtest_results": symbol_results,
                "pending_reviews": [result for result in symbol_results if result["backtest_result"] in {"manual_review_required", "insufficient_actual_data", "inconclusive"}],
                "revision_candidates": revisions_by_symbol.get(symbol, []),
                "latest_market_data_summary": latest_market.get(symbol, {}),
                "insufficient_evidence_items": collect_insufficient_for_symbol(symbol_reports),
            }
        )
    return {
        "generated_at": utc_now(),
        "symbol_count": len(items),
        "items": items,
        "no_openai_api_called": True,
        "formal_trusted_consumption": False,
    }


def collect_reports() -> list[dict[str, Any]]:
    reports = []
    for path in sorted(REPORT_ROOT.glob("*/*/v*/report_manifest.json")):
        payload = read_json(path)
        reports.append(
            {
                "report_id": payload["report_id"],
                "packet_id": payload["packet_id"],
                "target_symbol": payload["target_symbol"],
                "report_version": payload["report_version"],
                "previous_report_id": payload.get("previous_report_id"),
                "created_at": payload["created_at"],
                "manifest_path": str(path),
                "raw_report_path": payload["paths"]["raw_report"],
                "structured_report_path": payload["paths"]["structured_report"],
            }
        )
    return reports


def collect_packets() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted((PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2").glob("*/packet_manifest.json")):
        payload = read_json(path)
        result[payload["target_symbol"]].append(payload)
    return dict(result)


def collect_insufficient_for_symbol(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for report in reports:
        path = Path(report["manifest_path"]).parent / "insufficient_evidence_items.json"
        if path.exists():
            items.extend(read_json(path).get("items", []))
    return items


def latest_market_summary() -> dict[str, dict[str, Any]]:
    records = read_jsonl(BAOSTOCK_DAILY_PATH)
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        symbol = str(record.get("symbol"))
        if symbol not in latest or str(record.get("trade_date", "")) > str(latest[symbol].get("trade_date", "")):
            latest[symbol] = {
                "latest_trade_date": record.get("trade_date"),
                "latest_close": record.get("close"),
                "latest_volume": record.get("volume"),
                "source_id": "baostock_daily",
                "quality_status": source_quality("baostock_daily"),
                "candidate_only": True,
            }
    return latest


def write_symbol_exports(index: dict[str, Any]) -> None:
    for item in index["items"]:
        path = WORKSPACE_ROOT / f"{item['target_symbol']}_workspace.json"
        write_json(path, item)


def render_backtest_doc(summary: dict[str, Any]) -> str:
    return f"""# Backtest Execution v1 Report

Generated: {summary['generated_at']}

## Result Counts

```json
{json.dumps(summary['result_counts'], ensure_ascii=False, indent=2)}
```

Backtest execution uses existing candidate/staging market data only. GPT-generated forecasts remain interpretation records and are not trusted facts.

## v1.1 Testable Forecast Support

`run-backtest --only-testable` filters to forecasts that carry a testable contract (`price_direction`, `price_range`, `volume_direction`, or `metric_direction`) and writes non-destructive outputs:

- `runtime/backtest_execution_v1/backtest_results_testable_only.json`
- `runtime/backtest_execution_v1/report_backtest_summary_testable_only.json`

Non-testable forecasts such as `qualitative` and `insufficient_evidence` remain in manual review.
"""


def render_workspace_doc(index: dict[str, Any]) -> str:
    symbols = ", ".join(item["target_symbol"] for item in index["items"])
    return f"""# Research Workspace Index

Generated: {index['generated_at']}

Symbols: {symbols}

The workspace index aggregates packets, report versions, forecast items, backtest results, pending reviews, revision candidates, market summaries, and insufficient evidence.

Path: `runtime/research_workspace/research_workspace_index.json`
"""


def render_revision_doc(revisions: dict[str, Any]) -> str:
    return f"""# Forecast Revision Workflow

Revision candidates: {revisions['candidate_count']}

The system does not automatically revise investment views. It only prepares prompts for user review.

Each revision candidate includes:

- `forecast_id`
- `report_id`
- `target_symbol`
- `original_thesis`
- `backtest_result`
- `miss_reason_if_any`
- `suggested_revision_prompt`
- `requires_user_review`
"""


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cli() -> int:
    parser = argparse.ArgumentParser(description="Backtest execution and research workspace v1")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run-backtest")
    run.add_argument("--only-testable", action="store_true")
    sub.add_parser("list-reports")
    sub.add_parser("list-forecasts")
    sub.add_parser("list-backtest-results")
    sub.add_parser("list-manual-review")
    show = sub.add_parser("show-symbol-workspace")
    show.add_argument("--symbol", required=True)
    export = sub.add_parser("export-workspace")
    export.add_argument("--symbol", required=True)
    args = parser.parse_args()
    if args.command in {None, "run-backtest"}:
        print(json.dumps(run_backtest_execution_v1(only_testable=getattr(args, "only_testable", False)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-reports":
        print(json.dumps({"items": collect_reports()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-forecasts":
        print(json.dumps({"items": load_all_forecasts()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-backtest-results":
        path = OUTPUT_ROOT / "backtest_results.json"
        print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"items": []}, indent=2))
        return 0
    if args.command == "list-manual-review":
        path = OUTPUT_ROOT / "backtest_results.json"
        payload = read_json(path) if path.exists() else {"items": []}
        items = [item for item in payload.get("items", []) if item.get("backtest_result") == "manual_review_required"]
        print(json.dumps({"items": items}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "show-symbol-workspace":
        path = WORKSPACE_ROOT / f"{args.symbol}_workspace.json"
        print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"error": "workspace not found", "symbol": args.symbol}, indent=2))
        return 0
    if args.command == "export-workspace":
        path = WORKSPACE_ROOT / f"{args.symbol}_workspace.json"
        if not path.exists():
            print(json.dumps({"error": "workspace not found", "symbol": args.symbol}, indent=2))
            return 1
        export_path = WORKSPACE_ROOT / f"{args.symbol}_workspace_export.json"
        export_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print(json.dumps({"exported": str(export_path)}, ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())
