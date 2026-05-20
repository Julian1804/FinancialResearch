from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_backtest_execution_v1 import lookup_actual_data  # noqa: E402


PACKET_ROOT = PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2"
REPORT_ROOT = PROJECT_ROOT / "runtime" / "analysis_reports"
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "forecast_contract_v2"
PILOT_ROOT = PROJECT_ROOT / "runtime" / "manual_report_pilot"
DOC_CONTRACT = PROJECT_ROOT / "docs" / "FORECAST_CONTRACT_V2.md"
DOC_PROMPT = PROJECT_ROOT / "docs" / "GPT_WEB_PROMPT_TEMPLATE_V2_1.md"
DOC_VALIDATION = PROJECT_ROOT / "docs" / "FORECAST_TESTABILITY_VALIDATION.md"

FORECAST_TYPES = {
    "price_direction",
    "price_range",
    "volume_direction",
    "metric_direction",
    "risk_trigger",
    "qualitative",
    "insufficient_evidence",
}
TESTABILITY_STATUSES = {"testable", "manual_review_required", "insufficient_evidence", "not_backtestable"}
DIRECTIONS = {"up", "down", "flat"}


def run_forecast_contract_v2() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    PILOT_ROOT.mkdir(parents=True, exist_ok=True)
    validation_results = validate_existing_reports()
    pilot = prepare_manual_pilot("600519")
    write_json(OUTPUT_ROOT / "forecast_testability_results.json", validation_results)
    write_json(OUTPUT_ROOT / "forecast_contract_v2_summary.json", {
        "generated_at": utc_now(),
        "forecast_contract_v2_completed": True,
        "validated_forecast_count": validation_results["forecast_count"],
        "testability_counts": validation_results["summary"],
        "manual_pilot": pilot,
        "no_openai_api_called": True,
        "trusted_consumption_affected": False,
    })
    DOC_CONTRACT.write_text(render_contract_doc(), encoding="utf-8")
    DOC_PROMPT.write_text(render_prompt_doc(), encoding="utf-8")
    DOC_VALIDATION.write_text(render_validation_doc(validation_results), encoding="utf-8")
    return {
        "forecast_contract_v2_completed": True,
        "gpt_web_prompt_v2_1_completed": True,
        "forecast_validator_completed": True,
        "manual_pilot_600519_completed": True,
        "validation_summary": validation_results["summary"],
        "pilot_paths": pilot["paths"],
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "outputs": {
            "forecast_contract_v2": str(OUTPUT_ROOT),
            "manual_report_pilot": str(PILOT_ROOT),
            "contract_doc": str(DOC_CONTRACT),
            "prompt_doc": str(DOC_PROMPT),
            "validation_doc": str(DOC_VALIDATION),
        },
    }


def validate_existing_reports() -> dict[str, Any]:
    items = []
    for forecast_path in sorted(REPORT_ROOT.glob("*/*/v*/forecast_items.json")):
        structured_path = forecast_path.parent / "structured_report.json"
        structured = read_json(structured_path) if structured_path.exists() else {}
        forecast_payload = read_json(forecast_path)
        for forecast in forecast_payload.get("items", []):
            items.append(validate_forecast_item(forecast, structured, forecast_path))
    summary: dict[str, int] = {}
    for item in items:
        summary[item["testability_status"]] = summary.get(item["testability_status"], 0) + 1
    return {"generated_at": utc_now(), "forecast_count": len(items), "summary": summary, "items": items}


def validate_forecast_item(forecast: dict[str, Any], report: dict[str, Any], forecast_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    forecast_type = forecast.get("forecast_type") or infer_forecast_type(forecast)
    target_metric = forecast.get("target_metric")
    review_date = forecast.get("review_date")
    direction = str(forecast.get("expected_direction") or "").lower()
    range_low = forecast.get("expected_range_low")
    range_high = forecast.get("expected_range_high")
    if forecast_type not in FORECAST_TYPES:
        errors.append("invalid_or_missing_forecast_type")
    if not target_metric:
        errors.append("missing_target_metric")
    if not review_date:
        errors.append("missing_review_date")
    if forecast_type == "price_direction" and direction not in DIRECTIONS:
        errors.append("price_direction_requires_expected_direction")
    if forecast_type == "price_range" and (range_low is None or range_high is None):
        errors.append("price_range_requires_low_and_high")
    if forecast_type == "volume_direction":
        if target_metric != "volume":
            errors.append("volume_direction_requires_target_metric_volume")
        if direction not in DIRECTIONS:
            errors.append("volume_direction_requires_expected_direction")
    if forecast_type == "metric_direction" and direction not in DIRECTIONS:
        errors.append("metric_direction_requires_expected_direction")
    if forecast_type == "risk_trigger" and not (forecast.get("invalidation_triggers") or forecast.get("risk_triggers")):
        errors.append("risk_trigger_requires_trigger_condition")
    actual = lookup_actual_data(report.get("target_symbol") or forecast.get("target_symbol"), target_metric, review_date) if target_metric and review_date else {"status": "not_checked"}
    actual_lookup_status = actual.get("status")
    can_auto = forecast_type in {"price_direction", "price_range", "volume_direction", "metric_direction"} and not errors and actual_lookup_status == "available"
    if forecast_type == "insufficient_evidence":
        status = "insufficient_evidence"
        route = "manual_review"
    elif forecast_type in {"qualitative", "risk_trigger"}:
        status = "manual_review_required" if not errors else "not_backtestable"
        route = "manual_review"
    elif can_auto:
        status = "testable"
        route = "automatic_backtest"
    elif errors:
        status = "not_backtestable"
        route = "manual_review"
    else:
        status = "insufficient_evidence"
        route = "manual_review"
        warnings.append("actual_data_lookup_not_available")
    return {
        "forecast_id": forecast.get("forecast_id"),
        "report_id": forecast.get("report_id") or report.get("report_id"),
        "target_symbol": report.get("target_symbol") or forecast.get("target_symbol"),
        "forecast_type": forecast_type,
        "target_metric": target_metric,
        "review_date": review_date,
        "expected_direction": forecast.get("expected_direction"),
        "expected_range_low": range_low,
        "expected_range_high": range_high,
        "testability_status": status,
        "backtest_route": route,
        "actual_data_lookup_status": actual_lookup_status,
        "errors": errors,
        "warnings": warnings,
        "forecast_items_path": str(forecast_path),
        "candidate_only_note": "Forecast is GPT/manual interpretation, not a trusted fact.",
    }


def prepare_manual_pilot(symbol: str) -> dict[str, Any]:
    packet_path = PACKET_ROOT / symbol / "analysis_packet.json"
    manifest_path = PACKET_ROOT / symbol / "packet_manifest.json"
    packet = read_json(packet_path)
    manifest = read_json(manifest_path)
    pilot_dir = PILOT_ROOT / symbol
    pilot_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = pilot_dir / "copy_to_gpt_prompt_v2_1.md"
    steps_path = pilot_dir / "user_manual_steps.md"
    manifest_out = pilot_dir / "manual_pilot_manifest.json"
    prompt_path.write_text(render_prompt_v2_1(packet), encoding="utf-8")
    steps_path.write_text(render_manual_steps(symbol, prompt_path), encoding="utf-8")
    payload = {
        "generated_at": utc_now(),
        "symbol": symbol,
        "packet_id": manifest["packet_id"],
        "data_snapshot_id": manifest["data_snapshot_id"],
        "latest_analysis_packet": str(packet_path),
        "copy_to_gpt_prompt_v2_1": str(prompt_path),
        "user_manual_steps": str(steps_path),
        "no_openai_api_called": True,
        "formal_trusted_consumption": False,
        "paths": {
            "analysis_packet": str(packet_path),
            "packet_manifest": str(manifest_path),
            "copy_to_gpt_prompt_v2_1": str(prompt_path),
            "user_manual_steps": str(steps_path),
        },
    }
    write_json(manifest_out, payload)
    return payload


def render_prompt_v2_1(packet: dict[str, Any]) -> str:
    return f"""# GPT Web Analysis Prompt v2.1

You are helping analyze a FinancialResearch packet for `{packet['target_symbol']}`.

Use only the packet below. Treat `{packet['as_of_date']}` as the information boundary. Do not use future information.

Guardrails:
- Candidate/staging data cannot be written as trusted facts.
- `needs_review_candidate` and `insufficient_evidence` must remain visible.
- Do not produce formal investment advice.
- If evidence is not enough for a forecast, output `forecast_type=insufficient_evidence`.
- If evidence is enough, you may output 1-3 testable forecasts.
- Do not output vague forecasts such as "may fluctuate".
- Every testable forecast must have `forecast_type`, `target_metric`, `review_date`, `confidence`, `thesis`, `supporting_evidence`, and `invalidation_triggers`.
- `price_direction` requires `expected_direction` of `up`, `down`, or `flat`.
- `price_range` requires `expected_range.low` and `expected_range.high`.
- `volume_direction` requires `target_metric=volume` and expected direction.

FINAL_REPORT_JSON must include:
- `packet_id`
- `data_snapshot_id`
- `target_symbol`
- `as_of_date`
- `analysis_scope`
- `key_assumptions`
- `investment_view`
- `forecast_items`
- `risk_items`
- `watchlist_signals`
- `confidence`
- `next_review_date`
- `insufficient_evidence_items`
- `candidate_data_usage_note`

Each forecast item must include:
- `forecast_type`
- `target_metric`
- `forecast_horizon`
- `review_date`
- `expected_direction`
- `expected_range`
- `expected_value`
- `confidence`
- `thesis`
- `supporting_evidence`
- `key_assumptions`
- `invalidation_triggers`
- `data_dependency`
- `testability_status`

Packet:
```json
{json.dumps(packet, ensure_ascii=False, indent=2)}
```
"""


def render_manual_steps(symbol: str, prompt_path: Path) -> str:
    return f"""# Manual Report Pilot Steps for {symbol}

1. Open `{prompt_path}`.
2. Copy the full prompt into GPT Web.
3. Discuss and refine manually.
4. Ask GPT Web to output the final report with a valid `FINAL_REPORT_JSON` block.
5. Save the final markdown locally, for example under `runtime/report_ingestion_v1/manual_inputs/{symbol}_final_report.md`.
6. Ingest it:

```powershell
python scripts/run_report_ingestion_v1.py ingest --report-path <saved_report.md>
```

7. Validate forecast testability:

```powershell
python scripts/run_forecast_contract_v2.py validate-forecast --report-path <structured_report.json>
```

8. When the review date is reached, run:

```powershell
python scripts/run_backtest_execution_v1.py run-backtest --only-testable
```
"""


def infer_forecast_type(forecast: dict[str, Any]) -> str:
    direction = str(forecast.get("expected_direction") or "").lower()
    target_metric = str(forecast.get("target_metric") or "").lower()
    if direction == "insufficient_evidence":
        return "insufficient_evidence"
    if forecast.get("expected_range_low") is not None or forecast.get("expected_range_high") is not None:
        return "price_range" if target_metric == "close" else "metric_direction"
    if target_metric == "volume":
        return "volume_direction"
    if target_metric and direction in DIRECTIONS:
        return "price_direction" if target_metric == "close" else "metric_direction"
    return "qualitative"


def validate_by_report_path(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    forecast_path = path.parent / "forecast_items.json"
    forecasts = read_json(forecast_path).get("items", []) if forecast_path.exists() else payload.get("forecast_items", [])
    items = [validate_forecast_item(item, payload, forecast_path) for item in forecasts]
    summary: dict[str, int] = {}
    for item in items:
        summary[item["testability_status"]] = summary.get(item["testability_status"], 0) + 1
    result = {"generated_at": utc_now(), "report_path": str(path), "forecast_count": len(items), "summary": summary, "items": items}
    output = OUTPUT_ROOT / f"forecast_testability_{path.parent.name}.json"
    write_json(output, result)
    return result


def validate_by_report_id(report_id: str) -> dict[str, Any]:
    for path in REPORT_ROOT.glob("*/*/v*/structured_report.json"):
        payload = read_json(path)
        if payload.get("report_id") == report_id:
            return validate_by_report_path(path)
    return {"generated_at": utc_now(), "error": "report_id_not_found", "report_id": report_id, "items": []}


def list_manual_review() -> dict[str, Any]:
    results = validate_existing_reports()
    items = [item for item in results["items"] if item["testability_status"] != "testable"]
    return {"generated_at": utc_now(), "count": len(items), "items": items}


def render_contract_doc() -> str:
    return """# Forecast Contract v2

Forecast categories:

- `price_direction`
- `price_range`
- `volume_direction`
- `metric_direction`
- `risk_trigger`
- `qualitative`
- `insufficient_evidence`

Every forecast item must include `forecast_type`, `target_metric`, `forecast_horizon`, `review_date`, `expected_direction`, `expected_range`, `expected_value`, `confidence`, `thesis`, `supporting_evidence`, `key_assumptions`, `invalidation_triggers`, `data_dependency`, and `testability_status`.

`testability_status` values:

- `testable`
- `manual_review_required`
- `insufficient_evidence`
- `not_backtestable`

GPT/manual forecasts remain interpretation records and never become trusted facts.
"""


def render_prompt_doc() -> str:
    return """# GPT Web Prompt Template v2.1

The manual pilot prompt is generated at `runtime/manual_report_pilot/600519/copy_to_gpt_prompt_v2_1.md`.

The template asks GPT Web to output 1-3 testable forecasts only when evidence is sufficient. It forbids vague forecasts and requires target metric, review date, expected direction or range, supporting evidence, and invalidation triggers.
"""


def render_validation_doc(results: dict[str, Any]) -> str:
    return f"""# Forecast Testability Validation

Validated forecasts: {results['forecast_count']}

```json
{json.dumps(results['summary'], ensure_ascii=False, indent=2)}
```

The validator checks required v2 fields, forecast-type-specific requirements, actual-data lookup, and whether each item should enter automatic backtest or manual review.
"""


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cli() -> int:
    parser = argparse.ArgumentParser(description="Forecast Contract v2 tools")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run")
    validate = sub.add_parser("validate-forecast")
    validate.add_argument("--report-id")
    validate.add_argument("--report-path")
    pilot = sub.add_parser("prepare-manual-pilot")
    pilot.add_argument("--symbol", default="600519")
    sub.add_parser("list-manual-review")
    args = parser.parse_args()
    if args.command in {None, "run"}:
        print(json.dumps(run_forecast_contract_v2(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate-forecast":
        if args.report_path:
            print(json.dumps(validate_by_report_path(Path(args.report_path)), ensure_ascii=False, indent=2))
            return 0
        if args.report_id:
            print(json.dumps(validate_by_report_id(args.report_id), ensure_ascii=False, indent=2))
            return 0
        print(json.dumps({"error": "report-id or report-path required"}, indent=2))
        return 1
    if args.command == "prepare-manual-pilot":
        print(json.dumps(prepare_manual_pilot(args.symbol), ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-manual-review":
        print(json.dumps(list_manual_review(), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())
