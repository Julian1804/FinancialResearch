from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from hashlib import sha256


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


STORAGE_PATH = PROJECT_ROOT / "config" / "storage_paths.json"
PACKET_ROOT = PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2"
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "report_ingestion_v1"
REPORT_ROOT = PROJECT_ROOT / "runtime" / "analysis_reports"
BACKTEST_ROOT = PROJECT_ROOT / "runtime" / "backtest_queue"
DOC_WORKFLOW = PROJECT_ROOT / "docs" / "HUMAN_IN_THE_LOOP_REPORT_INGESTION_WORKFLOW.md"
DOC_FORECAST = PROJECT_ROOT / "docs" / "FORECAST_BACKTEST_SCHEMA_V1.md"
DOC_VERSIONING = PROJECT_ROOT / "docs" / "REPORT_VERSIONING_AND_STORAGE.md"


REQUIRED_REPORT_FIELDS = {
    "packet_id",
    "data_snapshot_id",
    "target_symbol",
    "as_of_date",
    "analysis_scope",
    "key_assumptions",
    "investment_view",
    "forecast_items",
    "risk_items",
    "watchlist_signals",
    "confidence",
    "next_review_date",
    "insufficient_evidence_items",
    "candidate_data_usage_note",
}


def run_report_ingestion_v1() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    BACKTEST_ROOT.mkdir(parents=True, exist_ok=True)

    sample_reports = generate_sample_reports()
    ingestion_results = [ingest_report(path) for path in sample_reports]
    pending_queue = build_pending_backtest_queue()
    version_history = collect_version_history()
    smoke = build_cli_smoke_result(ingestion_results, pending_queue, version_history)

    write_json(OUTPUT_ROOT / "sample_ingestion_results.json", {"generated_at": utc_now(), "items": ingestion_results})
    write_json(OUTPUT_ROOT / "report_version_history.json", version_history)
    write_json(BACKTEST_ROOT / "pending_backtest_queue.json", pending_queue)
    write_json(BACKTEST_ROOT / "backtest_readiness_summary.json", build_backtest_readiness_summary(pending_queue))
    write_json(OUTPUT_ROOT / "cli_smoke_result.json", smoke)
    DOC_WORKFLOW.write_text(render_workflow_doc(smoke), encoding="utf-8")
    DOC_FORECAST.write_text(render_forecast_doc(), encoding="utf-8")
    DOC_VERSIONING.write_text(render_versioning_doc(), encoding="utf-8")

    return {
        "report_ingestion_v1_completed": True,
        "sample_report_count": len(sample_reports),
        "successful_ingestions": sum(1 for item in ingestion_results if item["ingestion_status"] == "success"),
        "failed_ingestions": sum(1 for item in ingestion_results if item["ingestion_status"] != "success"),
        "forecast_item_count": sum(len(item.get("forecast_items", [])) for item in ingestion_results),
        "pending_backtest_queue_count": pending_queue["queue_count"],
        "versioned_reports": version_history["report_count"],
        "cli_available": True,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "outputs": {
            "report_ingestion_runtime": str(OUTPUT_ROOT),
            "analysis_reports": str(REPORT_ROOT),
            "backtest_queue": str(BACKTEST_ROOT),
            "workflow_doc": str(DOC_WORKFLOW),
            "forecast_doc": str(DOC_FORECAST),
            "versioning_doc": str(DOC_VERSIONING),
        },
    }


def ingest_report(raw_report_path: Path | str, change_note: str = "sample ingestion run") -> dict[str, Any]:
    raw_report_path = Path(raw_report_path)
    raw_text = raw_report_path.read_text(encoding="utf-8")
    extracted = extract_final_report_json(raw_text)
    if not extracted["schema_valid"]:
        return save_failed_draft(raw_report_path, raw_text, extracted)

    payload = extracted["payload"]
    target = str(payload["target_symbol"])
    packet_id = str(payload["packet_id"])
    version_info = next_report_version(target, packet_id)
    report_id = f"report_{packet_id}_v{version_info['version']}_{hash_short(raw_text)}"
    created_at = utc_now()
    report_dir = REPORT_ROOT / target / packet_id / f"v{version_info['version']}"
    report_dir.mkdir(parents=True, exist_ok=True)

    structured = {
        "report_id": report_id,
        "report_version": version_info["version"],
        "previous_report_id": version_info["previous_report_id"],
        "source": "gpt_web_manual",
        "created_at": created_at,
        "raw_report_path": str(report_dir / "raw_report.md"),
        "schema_valid": True,
        "trusted_fact_status": "analysis_report_only_not_trusted_fact",
        "formal_trusted_consumption": False,
        **payload,
    }
    forecasts = normalize_forecast_items(payload.get("forecast_items", []), structured)
    risks = normalize_collection(payload.get("risk_items", []), "risk_id", report_id)
    watchlist = normalize_collection(payload.get("watchlist_signals", []), "signal_id", report_id)
    insufficient = normalize_insufficient(payload.get("insufficient_evidence_items", []), report_id)
    manifest = {
        "report_id": report_id,
        "packet_id": packet_id,
        "data_snapshot_id": payload["data_snapshot_id"],
        "target_symbol": target,
        "report_version": version_info["version"],
        "previous_report_id": version_info["previous_report_id"],
        "created_at": created_at,
        "source": "gpt_web_manual",
        "change_note": change_note,
        "paths": {
            "raw_report": str(report_dir / "raw_report.md"),
            "structured_report": str(report_dir / "structured_report.json"),
            "report_manifest": str(report_dir / "report_manifest.json"),
            "forecast_items": str(report_dir / "forecast_items.json"),
            "risk_items": str(report_dir / "risk_items.json"),
            "watchlist_signals": str(report_dir / "watchlist_signals.json"),
            "insufficient_evidence_items": str(report_dir / "insufficient_evidence_items.json"),
        },
        "candidate_data_usage_note": payload.get("candidate_data_usage_note", ""),
        "gpt_content_not_trusted_fact": True,
        "formal_trusted_consumption": False,
    }

    (report_dir / "raw_report.md").write_text(raw_text, encoding="utf-8")
    write_json(report_dir / "structured_report.json", structured)
    write_json(report_dir / "report_manifest.json", manifest)
    write_json(report_dir / "forecast_items.json", {"generated_at": created_at, "items": forecasts})
    write_json(report_dir / "risk_items.json", {"generated_at": created_at, "items": risks})
    write_json(report_dir / "watchlist_signals.json", {"generated_at": created_at, "items": watchlist})
    write_json(report_dir / "insufficient_evidence_items.json", {"generated_at": created_at, "items": insufficient})
    backup_report_dir(report_dir, target, packet_id, version_info["version"])
    return {
        "ingestion_status": "success",
        "report_id": report_id,
        "report_version": version_info["version"],
        "previous_report_id": version_info["previous_report_id"],
        "target_symbol": target,
        "packet_id": packet_id,
        "data_snapshot_id": payload["data_snapshot_id"],
        "forecast_items": forecasts,
        "risk_item_count": len(risks),
        "watchlist_signal_count": len(watchlist),
        "insufficient_evidence_count": len(insufficient),
        "report_dir": str(report_dir),
        "formal_trusted_consumption": False,
    }


def extract_final_report_json(raw_text: str) -> dict[str, Any]:
    match = re.search(r"FINAL_REPORT_JSON\s*```json\s*(\{.*?\})\s*```", raw_text, flags=re.DOTALL)
    if not match:
        return {"schema_valid": False, "error": "FINAL_REPORT_JSON fenced json block not found"}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return {"schema_valid": False, "error": f"invalid FINAL_REPORT_JSON: {exc}"}
    missing = sorted(REQUIRED_REPORT_FIELDS - set(payload))
    if missing:
        return {"schema_valid": False, "error": "missing required fields", "missing_fields": missing, "payload": payload}
    return {"schema_valid": True, "payload": payload, "missing_fields": []}


def generate_sample_reports() -> list[Path]:
    sample_root = OUTPUT_ROOT / "sample_reports"
    sample_root.mkdir(parents=True, exist_ok=True)
    manifests = [read_json(PACKET_ROOT / symbol / "packet_manifest.json") for symbol in ["600519", "000001"]]
    paths: list[Path] = []
    paths.append(write_sample_report(sample_root / "sample_600519_v1.md", manifests[0], "v1_schema_workflow_sample", "insufficient_evidence"))
    paths.append(write_sample_report(sample_root / "sample_600519_v2.md", manifests[0], "v2_revised_note_sample", "insufficient_evidence"))
    paths.append(write_sample_report(sample_root / "sample_000001_v1.md", manifests[1], "v1_schema_workflow_sample", "insufficient_evidence"))
    return paths


def write_sample_report(path: Path, manifest: dict[str, Any], change_note: str, investment_view: str) -> Path:
    payload = {
        "packet_id": manifest["packet_id"],
        "data_snapshot_id": manifest["data_snapshot_id"],
        "target_symbol": manifest["target_symbol"],
        "as_of_date": manifest["as_of_date"],
        "analysis_scope": manifest["analysis_scope"],
        "key_assumptions": [
            "Sample report for workflow validation only.",
            "Candidate/staging data is not treated as trusted fact.",
        ],
        "investment_view": investment_view,
        "forecast_items": [
            {
                "target_metric": "close",
                "forecast_horizon": "schema_validation_same_day",
                "expected_direction": "insufficient_evidence",
                "expected_range": {"low": None, "high": None},
                "expected_value": None,
                "confidence": "low",
                "thesis": "No real investment forecast is made; this item validates forecast/backtest storage.",
                "supporting_evidence": ["market_daily_candidate_staging", "cross_validated_candidate"],
                "key_assumptions": ["human-in-the-loop workflow sample"],
                "risk_triggers": ["candidate data cannot be treated as trusted final fact"],
                "review_date": manifest["as_of_date"],
                "revision_note": change_note,
            }
        ],
        "risk_items": [
            {
                "risk_name": "candidate_data_boundary",
                "severity": "high",
                "description": "GPT interpretation is not a trusted fact and must remain separate from FR trusted consumption.",
            }
        ],
        "watchlist_signals": [
            {
                "signal_name": "source_consistency_monitor",
                "metric": "pct_change",
                "condition": "review mismatches before downstream use",
            }
        ],
        "confidence": "low",
        "next_review_date": manifest["as_of_date"],
        "insufficient_evidence_items": [
            "Financial report facts are not parsed in this sample report.",
            "No real investment recommendation is generated.",
        ],
        "candidate_data_usage_note": "Candidate/staging data is referenced only for workflow validation and is not promoted to trusted facts.",
    }
    text = f"""# Sample GPT Web Report ({manifest['target_symbol']})

This is a workflow validation sample. It is not investment advice.

FINAL_REPORT_JSON
```json
{json.dumps(payload, ensure_ascii=False, indent=2)}
```
"""
    path.write_text(text, encoding="utf-8")
    return path


def normalize_forecast_items(items: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = []
    for index, item in enumerate(items, start=1):
        expected_range = item.get("expected_range") or {}
        review_date = item.get("review_date") or report.get("next_review_date") or report["as_of_date"]
        actual = lookup_actual_value(report["target_symbol"], item.get("target_metric"), review_date)
        status = "ready_for_backtest" if actual["status"] == "available" else "pending_review"
        if date.fromisoformat(review_date) > date.today():
            status = "pending_review"
        elif actual["status"] != "available":
            status = "inconclusive"
        normalized.append(
            {
                "forecast_id": f"forecast_{report['report_id']}_{index}",
                "report_id": report["report_id"],
                "packet_id": report["packet_id"],
                "target_symbol": report["target_symbol"],
                "as_of_date": report["as_of_date"],
                "forecast_horizon": item.get("forecast_horizon"),
                "target_metric": item.get("target_metric"),
                "expected_direction": item.get("expected_direction"),
                "expected_range_low": expected_range.get("low"),
                "expected_range_high": expected_range.get("high"),
                "expected_value": item.get("expected_value"),
                "confidence": item.get("confidence"),
                "thesis": item.get("thesis"),
                "supporting_evidence": item.get("supporting_evidence", []),
                "key_assumptions": item.get("key_assumptions", []),
                "risk_triggers": item.get("risk_triggers", []),
                "review_date": review_date,
                "actual_value_later": actual.get("value"),
                "actual_value_source": actual.get("source"),
                "backtest_status": status,
                "backtest_result": "not_evaluated",
                "revision_note": item.get("revision_note", ""),
            }
        )
    return normalized


def build_pending_backtest_queue() -> dict[str, Any]:
    items = []
    for forecast_path in REPORT_ROOT.glob("*/*/v*/forecast_items.json"):
        payload = read_json(forecast_path)
        for forecast in payload.get("items", []):
            review_date = forecast.get("review_date")
            actual = lookup_actual_value(forecast.get("target_symbol"), forecast.get("target_metric"), review_date)
            if review_date and date.fromisoformat(review_date) <= date.today():
                readiness = "ready_for_backtest" if actual["status"] == "available" else "insufficient_actual_data"
            else:
                readiness = "pending_review_date"
            items.append(
                {
                    "forecast_id": forecast["forecast_id"],
                    "report_id": forecast["report_id"],
                    "packet_id": forecast["packet_id"],
                    "target_symbol": forecast["target_symbol"],
                    "target_metric": forecast["target_metric"],
                    "review_date": review_date,
                    "readiness_status": readiness,
                    "actual_value_later": actual.get("value"),
                    "actual_value_source": actual.get("source"),
                    "candidate_only_forecast": True,
                    "gpt_content_not_trusted_fact": True,
                }
            )
    return {"generated_at": utc_now(), "queue_count": len(items), "items": items}


def lookup_actual_value(symbol: str | None, metric: str | None, review_date: str | None) -> dict[str, Any]:
    if not symbol or not metric or not review_date:
        return {"status": "insufficient_actual_data", "reason": "missing symbol/metric/review_date"}
    path = Path("Z:/data_lake_master/structured/market_data/a_share_daily/baostock_daily/baostock_watchlist_controlled_30d.jsonl")
    if not path.exists():
        return {"status": "insufficient_actual_data", "reason": "baostock structured data not found"}
    records = read_jsonl(path)
    candidates = [record for record in records if str(record.get("symbol")) == symbol and str(record.get("trade_date")) <= review_date and metric in record]
    if not candidates:
        return {"status": "insufficient_actual_data", "reason": "no matching actual observation"}
    latest = sorted(candidates, key=lambda record: record.get("trade_date", ""))[-1]
    return {"status": "available", "value": latest.get(metric), "source": str(path), "trade_date": latest.get("trade_date")}


def next_report_version(target: str, packet_id: str) -> dict[str, Any]:
    root = REPORT_ROOT / target / packet_id
    existing = []
    if root.exists():
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
                existing.append(int(child.name[1:]))
    version = max(existing, default=0) + 1
    previous_id = None
    if existing:
        previous_manifest = root / f"v{max(existing)}" / "report_manifest.json"
        if previous_manifest.exists():
            previous_id = read_json(previous_manifest).get("report_id")
    return {"version": version, "previous_report_id": previous_id}


def collect_version_history() -> dict[str, Any]:
    manifests = []
    for manifest_path in sorted(REPORT_ROOT.glob("*/*/v*/report_manifest.json")):
        manifest = read_json(manifest_path)
        manifests.append(
            {
                "report_id": manifest["report_id"],
                "previous_report_id": manifest.get("previous_report_id"),
                "packet_id": manifest["packet_id"],
                "target_symbol": manifest["target_symbol"],
                "version": manifest["report_version"],
                "change_note": manifest.get("change_note", ""),
                "created_at": manifest["created_at"],
                "manifest_path": str(manifest_path),
            }
        )
    return {"generated_at": utc_now(), "report_count": len(manifests), "items": manifests}


def build_backtest_readiness_summary(queue: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in queue["items"]:
        counts[item["readiness_status"]] = counts.get(item["readiness_status"], 0) + 1
    return {"generated_at": utc_now(), "counts": counts, "queue_path": str(BACKTEST_ROOT / "pending_backtest_queue.json")}


def save_failed_draft(path: Path, raw_text: str, extracted: dict[str, Any]) -> dict[str, Any]:
    failed_id = "failed_" + hash_short(raw_text)
    root = OUTPUT_ROOT / "failed_drafts" / failed_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw_report.md").write_text(raw_text, encoding="utf-8")
    write_json(root / "ingestion_error.json", extracted)
    return {"ingestion_status": "ingestion_failed", "failed_id": failed_id, "raw_report_path": str(path), "error": extracted}


def backup_report_dir(report_dir: Path, target: str, packet_id: str, version: int) -> None:
    storage = read_json(STORAGE_PATH)["paths"]
    backup_root = Path(storage["cold_data_root"]) / "exports" / "analysis_reports" / target / packet_id / f"v{version}"
    backup_root.mkdir(parents=True, exist_ok=True)
    for path in report_dir.iterdir():
        if path.is_file():
            shutil.copy2(path, backup_root / path.name)


def normalize_collection(items: list[Any], id_name: str, report_id: str) -> list[dict[str, Any]]:
    normalized = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            item = {"value": item}
        normalized.append({id_name: f"{id_name}_{report_id}_{index}", "report_id": report_id, **item})
    return normalized


def normalize_insufficient(items: list[Any], report_id: str) -> list[dict[str, Any]]:
    normalized = []
    for index, item in enumerate(items, start=1):
        normalized.append({"insufficient_evidence_id": f"insufficient_{report_id}_{index}", "report_id": report_id, "item": item})
    return normalized


def build_cli_smoke_result(ingestions: list[dict[str, Any]], queue: dict[str, Any], version_history: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "cli_entrypoint": "python scripts/run_report_ingestion_v1.py --help",
        "commands": [
            "python scripts/run_report_ingestion_v1.py sample-run",
            "python scripts/run_report_ingestion_v1.py ingest --report-path <path>",
            "python scripts/run_report_ingestion_v1.py list-reports",
        ],
        "sample_ingestion_success": all(item["ingestion_status"] == "success" for item in ingestions),
        "forecast_items_visible": sum(len(item.get("forecast_items", [])) for item in ingestions),
        "pending_backtest_queue_count": queue["queue_count"],
        "report_version_history_count": version_history["report_count"],
        "no_openai_api_called": True,
    }


def render_workflow_doc(smoke: dict[str, Any]) -> str:
    return f"""# Human-in-the-loop Report Ingestion Workflow

## Scope

This workflow stores reports copied manually from GPT Web. It does not call the OpenAI API and does not promote GPT text into trusted facts.

## CLI

```powershell
{chr(10).join(smoke['commands'])}
```

## Stored Outputs

- Local reports: `runtime/analysis_reports`
- NAS backup: `Z:\\data_lake_master\\exports\\analysis_reports`
- Backtest queue: `runtime/backtest_queue\\pending_backtest_queue.json`
- Version history: `runtime/report_ingestion_v1\\report_version_history.json`

## Guardrail

GPT-generated content is stored as `analysis_report / forecast / interpretation` only. It is not formal trusted consumption.
"""


def render_forecast_doc() -> str:
    return """# Forecast Backtest Schema v1

Each forecast item includes:

- `forecast_id`
- `report_id`
- `packet_id`
- `target_symbol`
- `as_of_date`
- `forecast_horizon`
- `target_metric`
- `expected_direction`
- `expected_range_low`
- `expected_range_high`
- `expected_value`
- `confidence`
- `thesis`
- `supporting_evidence`
- `key_assumptions`
- `risk_triggers`
- `review_date`
- `actual_value_later`
- `backtest_status`
- `backtest_result`
- `revision_note`

Statuses:

- `pending_review`
- `ready_for_backtest`
- `backtested_hit`
- `backtested_miss`
- `inconclusive`
- `revised`

Phase v1 only prepares the queue and attaches actual values when existing A-share daily data is available.
"""


def render_versioning_doc() -> str:
    return """# Report Versioning and Storage

Rules:

1. First report for a packet is `v1`.
2. Re-ingesting the same `packet_id` creates `v2`, `v3`, and so on.
3. Existing reports are never overwritten.
4. `report_version_history.json` tracks report lineage.

Per-version files:

- `raw_report.md`
- `structured_report.json`
- `report_manifest.json`
- `forecast_items.json`
- `risk_items.json`
- `watchlist_signals.json`
- `insufficient_evidence_items.json`

Reports are stored locally under `runtime/analysis_reports` and copied to `Z:\\data_lake_master\\exports\\analysis_reports`.
"""


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def hash_short(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()[:12]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cli() -> int:
    parser = argparse.ArgumentParser(description="Human-in-the-loop report ingestion v1")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("sample-run")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--report-path", required=True)
    sub.add_parser("list-reports")
    args = parser.parse_args()
    if args.command in {None, "sample-run"}:
        print(json.dumps(run_report_ingestion_v1(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "ingest":
        result = ingest_report(Path(args.report_path))
        pending = build_pending_backtest_queue()
        write_json(BACKTEST_ROOT / "pending_backtest_queue.json", pending)
        write_json(BACKTEST_ROOT / "backtest_readiness_summary.json", build_backtest_readiness_summary(pending))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "list-reports":
        print(json.dumps(collect_version_history(), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())
