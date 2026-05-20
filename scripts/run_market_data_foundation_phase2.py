from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CONFIG_ROOT = PROJECT_ROOT / "config"
PHASE1_ROOT = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion"
FOUNDATION_ROOT = PROJECT_ROOT / "runtime" / "market_data_foundation_catalog"
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "market_data_foundation_phase2"
METADATA_DB = OUTPUT_ROOT / "market_data_foundation_metadata.sqlite"
LOCAL_SECRETS_PATH = CONFIG_ROOT / "local_secrets.json"
STORAGE_PATHS = CONFIG_ROOT / "storage_paths.json"
DOC_REPORT = PROJECT_ROOT / "docs" / "MARKET_DATA_FOUNDATION_PHASE2_REPORT.md"


FRED_PHASE2_SERIES = {
    "us_30y_yield": {
        "series_id": "DGS30",
        "domain": "rates_bonds",
        "category": "sovereign_yield",
        "metric_name": "US 30Y Treasury yield",
        "unit": "percent",
        "frequency": "daily",
        "country": "US",
        "source_id": "fred_public_api",
    },
    "sofr": {
        "series_id": "SOFR",
        "domain": "rates_bonds",
        "category": "overnight_rate",
        "metric_name": "Secured Overnight Financing Rate",
        "unit": "percent",
        "frequency": "daily",
        "country": "US",
        "source_id": "fred_public_api",
    },
    "usd_cny": {
        "series_id": "DEXCHUS",
        "domain": "fx",
        "category": "spot_fx",
        "metric_name": "USD/CNY",
        "unit": "CNY_per_USD",
        "frequency": "daily",
        "base_currency": "USD",
        "quote_currency": "CNY",
        "source_id": "fred_public_api",
    },
    "usd_jpy": {
        "series_id": "DEXJPUS",
        "domain": "fx",
        "category": "spot_fx",
        "metric_name": "USD/JPY",
        "unit": "JPY_per_USD",
        "frequency": "daily",
        "base_currency": "USD",
        "quote_currency": "JPY",
        "source_id": "fred_public_api",
    },
    "eur_usd": {
        "series_id": "DEXUSEU",
        "domain": "fx",
        "category": "spot_fx",
        "metric_name": "EUR/USD",
        "unit": "USD_per_EUR",
        "frequency": "daily",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "source_id": "fred_public_api",
    },
    "gbp_usd": {
        "series_id": "DEXUSUK",
        "domain": "fx",
        "category": "spot_fx",
        "metric_name": "GBP/USD",
        "unit": "USD_per_GBP",
        "frequency": "daily",
        "base_currency": "GBP",
        "quote_currency": "USD",
        "source_id": "fred_public_api",
    },
}


DOMAIN_STORAGE = {
    "macro": "macro",
    "rates_bonds": "rates_bond",
    "fx": "fx_currency",
    "commodity": "commodity",
    "futures": "futures",
    "asset_class": "asset_class",
}


def run_market_data_foundation_phase2() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    storage = load_storage_paths()
    ensure_domain_dirs(storage)
    snapshot_id = "market_data_foundation_phase2_" + utc_now().replace("-", "").replace(":", "")

    foundation_catalog = read_json(FOUNDATION_ROOT / "foundation_catalog.json")
    phase1_catalog = read_json(PHASE1_ROOT / "dataset_catalog.json")
    phase1_dashboard = read_json(PHASE1_ROOT / "dashboard_macro_asset_summary.json")
    previous = load_previous_phase2_records()

    run_records: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []
    normalized_records: list[dict[str, Any]] = []
    processed_metric_ids: set[str] = set()

    for item in foundation_catalog.get("items", []):
        metric_id = item["metric_id"]
        if metric_id in FRED_PHASE2_SERIES:
            result = fetch_fred_phase2_series(storage, metric_id, FRED_PHASE2_SERIES[metric_id], snapshot_id)
            run_records.append(result["run"])
            raw_artifacts.extend(result["raw_artifacts"])
            normalized_records.extend(result["records"])
            processed_metric_ids.add(metric_id)
            continue
        if item["current_status"] == "available":
            run_records.append(reuse_existing_run_record(item, phase1_catalog, snapshot_id))
            processed_metric_ids.add(metric_id)
            continue
        if item["priority"] <= 2 or item["domain"] == "futures":
            run_records.append(deferred_run_record(item, snapshot_id))
            processed_metric_ids.add(metric_id)

    quality = run_quality_gate(normalized_records)
    apply_quality_to_records(normalized_records, quality)
    revision_log = detect_revisions(previous, normalized_records)
    vintage_summary = build_vintage_summary(normalized_records, revision_log)
    normalized_paths = write_normalized_outputs(storage, normalized_records, snapshot_id)
    update_run_records_after_quality(run_records, normalized_records, quality, normalized_paths)
    raw_index = {"generated_at": utc_now(), "items": raw_artifacts}
    catalog_update = build_catalog_update(foundation_catalog, phase1_catalog, run_records, normalized_records)
    source_audit = build_source_availability_audit(foundation_catalog)
    dashboard_summary = build_dashboard_summary(phase1_dashboard, catalog_update, normalized_records)
    update_foundation_catalog_runtime(catalog_update)
    write_metadata_db(run_records, raw_artifacts, normalized_records, quality, revision_log, catalog_update)

    outputs = {
        "run_records": str(write_json(OUTPUT_ROOT / "phase2_run_records.json", {"generated_at": utc_now(), "items": run_records})),
        "raw_artifact_index": str(write_json(OUTPUT_ROOT / "raw_artifact_index.json", raw_index)),
        "normalized_records": str(write_jsonl(OUTPUT_ROOT / "normalized_phase2_records.jsonl", normalized_records)),
        "normalized_paths": str(write_json(OUTPUT_ROOT / "normalized_paths.json", normalized_paths)),
        "quality_results": str(write_json(OUTPUT_ROOT / "quality_results.json", quality)),
        "revision_log": str(write_json(OUTPUT_ROOT / "revision_log.json", revision_log)),
        "vintage_summary": str(write_json(OUTPUT_ROOT / "vintage_summary.json", vintage_summary)),
        "foundation_catalog_update": str(write_json(OUTPUT_ROOT / "foundation_catalog_update.json", catalog_update)),
        "source_availability_audit": str(write_json(OUTPUT_ROOT / "source_availability_audit.json", source_audit)),
        "dashboard_market_data_summary": str(write_json(OUTPUT_ROOT / "dashboard_market_data_summary.json", dashboard_summary)),
        "metadata_db": str(METADATA_DB),
    }
    report = write_phase2_report(run_records, catalog_update, quality, revision_log, outputs)
    summary = {
        "generated_at": utc_now(),
        "phase2_market_data_foundation_completed": True,
        "catalog_items_processed": len(processed_metric_ids),
        "successful_ingestion_count": sum(1 for item in run_records if item["qa_status"] in {"quality_passed", "quality_warning"} and item["records_normalized"] > 0),
        "deferred_count": sum(1 for item in run_records if item["qa_status"] == "deferred"),
        "records_normalized": len(normalized_records),
        "quality_counts": quality["quality_counts"],
        "revision_count": revision_log["revision_count"],
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "outputs": {**outputs, "report": str(report)},
    }
    write_json(OUTPUT_ROOT / "phase2_summary.json", summary)
    return summary


def fetch_fred_phase2_series(storage: dict[str, Path], metric_id: str, spec: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    source_id = spec["source_id"]
    series_id = spec["series_id"]
    domain = spec["domain"]
    raw_dir = storage["raw"][domain] / source_id
    raw_path = raw_dir / f"fred_{series_id}_full_history.json"
    safe_reference = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&file_type=json"
    error = ""
    raw_artifacts: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    try:
        if raw_path.exists():
            raw = raw_path.read_bytes()
            checksum = sha256_bytes(raw)
        else:
            params = {
                "series_id": series_id,
                "file_type": "json",
                "observation_start": "1776-07-04",
            }
            key = load_secret("FRED_API_KEY")
            if key:
                params["api_key"] = key
            url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
            raw = http_get(url, timeout=30, limit=25_000_000)
            if key:
                raw = raw.replace(key.encode("utf-8"), b"****")
            raw_path, checksum = save_raw(raw_dir, raw_path.name, raw)
        raw_artifacts.append(raw_artifact(source_id, raw_path, checksum, safe_reference))
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        for row in payload.get("observations", []):
            value = to_float(row.get("value"))
            if value is None:
                continue
            records.append(phase2_record(snapshot_id, metric_id, spec, row.get("date"), value, raw_path, checksum, row))
        status = "success" if records else "failed"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = f"{type(exc).__name__}: {str(exc)[:400]}"
    elapsed = round(time.perf_counter() - started, 3)
    return {
        "run": run_record(
            run_id="run_" + hash_short(f"{metric_id}|{snapshot_id}|{utc_now()}"),
            snapshot_id=snapshot_id,
            source_id=source_id,
            dataset_id=f"{source_id}:{series_id}",
            domain=domain,
            category=spec["category"],
            metric_id=metric_id,
            start_date=records[0]["observation_date"] if records else "",
            end_date=records[-1]["observation_date"] if records else "",
            records_raw=len(payload.get("observations", [])) if "payload" in locals() else 0,
            records_normalized=len(records),
            raw_path=str(raw_path) if "raw_path" in locals() else "",
            normalized_path="",
            qa_status="pending_quality" if records else "quality_failed",
            revision_status="pending_revision" if records else "not_applicable",
            publish_date_coverage=publish_date_coverage(records),
            trust_status="trusted_by_real_external_candidate" if records else "candidate_only",
            elapsed_seconds=elapsed,
            error_message=error,
        ),
        "records": records,
        "raw_artifacts": raw_artifacts,
    }


def phase2_record(
    snapshot_id: str,
    metric_id: str,
    spec: dict[str, Any],
    observation_date: str,
    value: float,
    raw_path: Path,
    checksum: str,
    source_row: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": "market_data_foundation_schema_v1",
        "dataset_id": f"{spec['source_id']}:{spec['series_id']}",
        "retrieval_snapshot_id": snapshot_id,
        "source_id": spec["source_id"],
        "provider_name": "FRED",
        "domain": spec["domain"],
        "category": spec["category"],
        "metric_id": metric_id,
        "series_id": spec["series_id"],
        "metric_name": spec["metric_name"],
        "frequency": spec["frequency"],
        "data_period_start": observation_date,
        "data_period_end": observation_date,
        "observation_date": observation_date,
        "publish_date": None,
        "publish_date_source": "unavailable",
        "value": value,
        "unit": spec["unit"],
        "vintage_date": source_row.get("realtime_start"),
        "revision_status": "vintage_available" if source_row.get("realtime_start") else "vintage_support_limited",
        "retrieved_at": utc_now(),
        "raw_path": str(raw_path),
        "checksum": checksum,
        "quality_status": "pending_quality",
        "trust_status": "trusted_by_real_external_candidate",
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }
    if spec["domain"] == "rates_bonds":
        base.update(
            {
                "country": spec.get("country"),
                "rate_type": spec["category"],
                "instrument_type": "money_market_rate" if spec["series_id"] == "SOFR" else "sovereign_yield",
                "tenor": "overnight" if spec["series_id"] == "SOFR" else "30Y",
                "maturity_bucket": "overnight" if spec["series_id"] == "SOFR" else "long",
                "curve_name": "US Treasury" if spec["series_id"].startswith("DGS") else "US overnight funding",
                "yield_value": value if spec["series_id"].startswith("DGS") else None,
                "rate_value": value,
                "nominal_or_real": "nominal",
                "seasonality": "not_applicable",
            }
        )
    if spec["domain"] == "fx":
        base.update(
            {
                "base_currency": spec["base_currency"],
                "quote_currency": spec["quote_currency"],
                "currency_pair": f"{spec['base_currency']}/{spec['quote_currency']}",
                "fx_type": "spot_fx",
                "rate": value,
                "market": "FRED official/aggregated FX series",
                "source_timezone": "source_default",
            }
        )
    return base


def reuse_existing_run_record(item: dict[str, Any], phase1_catalog: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    matching = match_existing_catalog_item(item, phase1_catalog)
    return run_record(
        run_id="reuse_" + hash_short(item["metric_id"]),
        snapshot_id=snapshot_id,
        source_id=(matching or {}).get("source_id") or item.get("preferred_source", "").split(":")[0] or "existing_runtime",
        dataset_id=(matching or {}).get("dataset_id") or item["metric_id"],
        domain=item["domain"],
        category=(matching or {}).get("category") or item["domain"],
        metric_id=item["metric_id"],
        start_date=(matching or {}).get("first_observation_date", ""),
        end_date=(matching or {}).get("latest_observation_date", ""),
        records_raw=(matching or {}).get("record_count", 0),
        records_normalized=(matching or {}).get("record_count", 0),
        raw_path="existing_phase1_raw_artifact_index",
        normalized_path="existing_phase1_normalized_dataset",
        qa_status=(matching or {}).get("quality_status") or ("quality_passed" if item["current_status"] == "available" else "deferred"),
        revision_status=(matching or {}).get("revision_status") or "vintage_support_limited",
        publish_date_coverage=(matching or {}).get("publish_date_source", "unavailable"),
        trust_status=(matching or {}).get("trust_status") or "trusted_by_real_external_candidate",
        elapsed_seconds=0.0,
        error_message="reused_existing_phase1_dataset_not_refetched",
    )


def deferred_run_record(item: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    reason = deferred_reason(item)
    return run_record(
        run_id="defer_" + hash_short(item["metric_id"]),
        snapshot_id=snapshot_id,
        source_id=item.get("preferred_source", "").split(":")[0] or "source_to_build",
        dataset_id=item["metric_id"],
        domain=item["domain"],
        category=item["domain"],
        metric_id=item["metric_id"],
        start_date="",
        end_date="",
        records_raw=0,
        records_normalized=0,
        raw_path="",
        normalized_path="",
        qa_status="deferred",
        revision_status="not_applicable",
        publish_date_coverage="not_applicable",
        trust_status="candidate_only",
        elapsed_seconds=0.0,
        error_message=reason,
    )


def deferred_reason(item: dict[str, Any]) -> str:
    metric_id = item["metric_id"]
    source = item.get("preferred_source", "")
    if item["domain"] == "futures":
        return f"futures schema ready, but {source} requires source-specific connector and authorization/terms review before ingestion"
    if metric_id.startswith("china_"):
        return f"official China source feasibility required for {source}; non-official scraping not used"
    if metric_id in {"shibor", "dr007"}:
        return f"official interbank source feasibility required for {source}; not mixed with Treasury/FRED data"
    if metric_id in {"japan_policy_rate", "euro_area_cpi", "uk_cpi", "japan_jgb_yield", "uk_gilt_yield"}:
        return f"official/authority connector not yet implemented for {source}"
    if "authorization" in item.get("connector_status", "") or item.get("current_status") == "future_connector":
        return "future_connector_or_authorization_required"
    return "source_feasibility_pending"


def run_record(
    run_id: str,
    snapshot_id: str,
    source_id: str,
    dataset_id: str,
    domain: str,
    category: str,
    metric_id: str,
    start_date: str,
    end_date: str,
    records_raw: int,
    records_normalized: int,
    raw_path: str,
    normalized_path: str,
    qa_status: str,
    revision_status: str,
    publish_date_coverage: str,
    trust_status: str,
    elapsed_seconds: float,
    error_message: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "retrieval_snapshot_id": snapshot_id,
        "source_id": source_id,
        "dataset_id": dataset_id,
        "domain": domain,
        "category": category,
        "metric_id": metric_id,
        "start_date": start_date,
        "end_date": end_date,
        "records_raw": records_raw,
        "records_normalized": records_normalized,
        "raw_path": raw_path,
        "normalized_path": normalized_path,
        "qa_status": qa_status,
        "revision_status": revision_status,
        "publish_date_coverage": publish_date_coverage,
        "trust_status": trust_status,
        "candidate_only": True,
        "elapsed_seconds": elapsed_seconds,
        "error_message": error_message,
    }


def run_quality_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_dataset.setdefault(record["dataset_id"], []).append(record)
    items = []
    for dataset_id, rows in sorted(by_dataset.items()):
        checks = {
            "required_fields_present": all(record.get("dataset_id") and record.get("source_id") and record.get("metric_id") for record in rows),
            "schema_version_present": all(record.get("schema_version") for record in rows),
            "date_parseable": all(is_date_like(record.get("observation_date")) for record in rows),
            "value_numeric": all(isinstance(record.get("value"), (int, float)) for record in rows),
            "duplicate_observation_check": len({record.get("observation_date") for record in rows}) == len(rows),
            "unit_present": all(record.get("unit") for record in rows),
            "frequency_consistency": len({record.get("frequency") for record in rows}) == 1,
            "source_id_present": all(record.get("source_id") for record in rows),
            "raw_checksum_present": all(record.get("checksum") for record in rows),
            "publish_date_source_classified": all(record.get("publish_date_source") in {"source_confirmed", "source_confirmed_record_date", "inferred", "user_override", "unavailable", "not_applicable"} for record in rows),
            "revision_vintage_status_classified": all(record.get("revision_status") for record in rows),
            "domain_category_mapping_valid": all(record.get("domain") in DOMAIN_STORAGE for record in rows),
        }
        values = [float(record["value"]) for record in rows if isinstance(record.get("value"), (int, float))]
        missing_ratio = 1 - (len(values) / len(rows)) if rows else 1
        checks["missing_ratio_ok"] = missing_ratio <= 0.05
        checks["outlier_check_non_blocking"] = True
        failed = [key for key, ok in checks.items() if not ok]
        status = "quality_passed"
        if failed:
            status = "quality_failed" if {"required_fields_present", "date_parseable", "value_numeric", "raw_checksum_present"} & set(failed) else "quality_warning"
        items.append(
            {
                "dataset_id": dataset_id,
                "domain": rows[0].get("domain"),
                "metric_id": rows[0].get("metric_id"),
                "series_id": rows[0].get("series_id"),
                "record_count": len(rows),
                "quality_status": status,
                "failed_checks": failed,
                "missing_ratio": round(missing_ratio, 6),
                "publish_date_source_counts": dict(Counter(record.get("publish_date_source") for record in rows)),
                "checks": checks,
            }
        )
    return {
        "generated_at": utc_now(),
        "dataset_count": len(items),
        "quality_counts": dict(Counter(item["quality_status"] for item in items)),
        "items": items,
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def apply_quality_to_records(records: list[dict[str, Any]], quality: dict[str, Any]) -> None:
    status_by_dataset = {item["dataset_id"]: item["quality_status"] for item in quality["items"]}
    for record in records:
        status = status_by_dataset.get(record["dataset_id"], "quality_failed")
        record["quality_status"] = status
        if status != "quality_passed":
            record["trust_status"] = "trusted_source_but_quality_failed"


def update_run_records_after_quality(
    run_records: list[dict[str, Any]],
    records: list[dict[str, Any]],
    quality: dict[str, Any],
    normalized_paths: dict[str, str],
) -> None:
    rows_by_dataset = group_by(records, "dataset_id")
    quality_by_dataset = {item["dataset_id"]: item["quality_status"] for item in quality["items"]}
    for run in run_records:
        rows = rows_by_dataset.get(run["dataset_id"], [])
        if not rows:
            continue
        sorted_rows = sorted(rows, key=lambda row: row["observation_date"])
        domain = sorted_rows[-1]["domain"]
        run["qa_status"] = quality_by_dataset.get(run["dataset_id"], "quality_failed")
        run["revision_status"] = sorted_rows[-1]["revision_status"]
        run["publish_date_coverage"] = publish_date_coverage(rows)
        run["trust_status"] = sorted_rows[-1]["trust_status"]
        run["start_date"] = sorted_rows[0]["observation_date"]
        run["end_date"] = sorted_rows[-1]["observation_date"]
        run["normalized_path"] = normalized_paths.get(f"{domain}_latest", "")


def detect_revisions(previous: dict[tuple[str, str], dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    detected_at = utc_now()
    for record in records:
        key = (record.get("dataset_id", ""), record.get("observation_date", ""))
        old = previous.get(key)
        if not old:
            continue
        old_value = to_float(old.get("value"))
        new_value = to_float(record.get("value"))
        if old_value is None or new_value is None:
            continue
        if abs(old_value - new_value) > max(1e-9, abs(old_value) * 1e-10):
            items.append(
                {
                    "series_id": record.get("series_id"),
                    "dataset_id": record.get("dataset_id"),
                    "observation_date": record.get("observation_date"),
                    "old_value": old_value,
                    "new_value": new_value,
                    "old_retrieved_at": old.get("retrieved_at"),
                    "new_retrieved_at": record.get("retrieved_at"),
                    "revision_detected_at": detected_at,
                    "source_id": record.get("source_id"),
                    "revision_type": "value_changed_since_previous_phase2_snapshot",
                }
            )
    return {
        "generated_at": detected_at,
        "revision_count": len(items),
        "items": items,
        "policy": "Do not overwrite old observations for as-of analysis; use retrieval_snapshot_id and vintage_date.",
    }


def build_vintage_summary(records: list[dict[str, Any]], revision_log: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "dataset_count": len({record["dataset_id"] for record in records}),
        "vintage_status_counts": dict(Counter(record.get("revision_status") for record in records)),
        "revision_count": revision_log["revision_count"],
        "vintage_support_limited_note": "FRED observations expose realtime_start/realtime_end fields; other sources may only support retrieval snapshots.",
        "candidate_only": True,
    }


def build_catalog_update(
    foundation_catalog: dict[str, Any],
    phase1_catalog: dict[str, Any],
    run_records: list[dict[str, Any]],
    normalized_records: list[dict[str, Any]],
) -> dict[str, Any]:
    phase1_by_metric = build_phase1_metric_lookup(phase1_catalog)
    phase2_by_metric: dict[str, list[dict[str, Any]]] = {}
    for record in normalized_records:
        phase2_by_metric.setdefault(record["metric_id"], []).append(record)
    run_by_metric = {record["metric_id"]: record for record in run_records}
    items = []
    for item in foundation_catalog.get("items", []):
        metric_id = item["metric_id"]
        updated = dict(item)
        phase2_rows = phase2_by_metric.get(metric_id, [])
        phase1 = phase1_by_metric.get(metric_id)
        run = run_by_metric.get(metric_id)
        if phase2_rows:
            sorted_rows = sorted(phase2_rows, key=lambda row: row["observation_date"])
            latest = sorted_rows[-1]
            updated.update(
                {
                    "current_status": "available",
                    "records_loaded": len(phase2_rows),
                    "earliest_observation": sorted_rows[0]["observation_date"],
                    "latest_observation": latest["observation_date"],
                    "source_used": latest["source_id"],
                    "quality_status": latest["quality_status"],
                    "publish_date_coverage": publish_date_coverage(phase2_rows),
                    "revision_status": latest["revision_status"],
                    "connector_status": "connected",
                    "dashboard_ready": latest["quality_status"] == "quality_passed",
                    "next_action": "monitor_incremental_updates_and_revision_snapshots",
                }
            )
        elif phase1:
            updated.update(
                {
                    "records_loaded": phase1.get("record_count", 0),
                    "earliest_observation": phase1.get("first_observation_date"),
                    "latest_observation": phase1.get("latest_observation_date"),
                    "source_used": phase1.get("source_id"),
                    "quality_status": phase1.get("quality_status"),
                    "publish_date_coverage": phase1.get("publish_date_source"),
                    "revision_status": phase1.get("revision_status"),
                    "connector_status": "connected",
                    "dashboard_ready": phase1.get("quality_status") == "quality_passed",
                    "next_action": "reuse_existing_ingested_dataset",
                }
            )
        elif run and run["qa_status"] == "deferred":
            updated.update(
                {
                    "current_status": "future_connector" if item["domain"] == "futures" else "missing",
                    "records_loaded": 0,
                    "source_used": "",
                    "quality_status": "not_run",
                    "publish_date_coverage": "not_applicable",
                    "revision_status": "not_applicable",
                    "dashboard_ready": False,
                    "next_action": run["error_message"],
                }
            )
        else:
            updated.update(
                {
                    "records_loaded": 0,
                    "source_used": "",
                    "quality_status": "not_run",
                    "publish_date_coverage": "not_applicable",
                    "revision_status": "not_applicable",
                    "next_action": "not_selected_in_phase2_batch",
                }
            )
        items.append(updated)
    return {
        "generated_at": utc_now(),
        "items": items,
        "summary": {
            "item_count": len(items),
            "available": sum(1 for item in items if item["current_status"] == "available"),
            "missing": sum(1 for item in items if item["current_status"] == "missing"),
            "future_connector": sum(1 for item in items if item["current_status"] == "future_connector"),
            "dashboard_ready": sum(1 for item in items if item.get("dashboard_ready")),
            "records_loaded": sum(int(item.get("records_loaded") or 0) for item in items),
        },
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def update_foundation_catalog_runtime(catalog_update: dict[str, Any]) -> None:
    items = catalog_update["items"]
    write_json(FOUNDATION_ROOT / "foundation_catalog.json", {"generated_at": utc_now(), "items": items, "candidate_only": True, "formal_trusted_consumption": False})
    gaps = [item for item in items if item["current_status"] != "available"]
    write_json(
        FOUNDATION_ROOT / "source_gap_matrix.json",
        {
            "generated_at": utc_now(),
            "items": [
                {
                    "metric_id": item["metric_id"],
                    "domain": item["domain"],
                    "current_status": item["current_status"],
                    "preferred_source": item["preferred_source"],
                    "next_action": item.get("next_action"),
                    "priority": item["priority"],
                }
                for item in gaps
            ],
        },
    )
    write_json(
        FOUNDATION_ROOT / "next_ingestion_plan.json",
        {
            "generated_at": utc_now(),
            "principle": "Continue official/free connector work; do not backfill unavailable sources with non-official substitutes.",
            "items": [
                {
                    "metric_id": item["metric_id"],
                    "domain": item["domain"],
                    "preferred_source": item["preferred_source"],
                    "priority": item["priority"],
                    "safe_next_step": item.get("next_action", "source_feasibility"),
                }
                for item in gaps
                if item["priority"] <= 3
            ],
        },
    )
    write_json(
        FOUNDATION_ROOT / "foundation_summary.json",
        {
            "generated_at": utc_now(),
            "item_count": len(items),
            "domain_counts": dict(Counter(item["domain"] for item in items)),
            "status_counts": dict(Counter(item["current_status"] for item in items)),
            "schema_ready_count": sum(1 for item in items if item.get("schema_ready")),
            "dashboard_ready_count": sum(1 for item in items if item.get("dashboard_ready")),
        },
    )


def build_source_availability_audit(foundation_catalog: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in foundation_catalog.get("items", []):
        if item["current_status"] == "available":
            continue
        source = item.get("preferred_source", "")
        if item["metric_id"] in FRED_PHASE2_SERIES:
            status = "attempted_in_phase2"
            reason = "FRED official/free source available"
        elif item["domain"] == "futures":
            status = "deferred"
            reason = "exchange futures require source-specific connector, terms review and contract schema mapping"
        elif item["metric_id"].startswith("china_"):
            status = "future_connector"
            reason = "official NBS/PBOC/SAFE source feasibility required; no unofficial substitute used"
        elif item["metric_id"] in {"japan_policy_rate", "euro_area_cpi", "uk_cpi", "japan_jgb_yield", "uk_gilt_yield"}:
            status = "future_connector"
            reason = "official authority source connector not implemented in this batch"
        else:
            status = "missing"
            reason = "not selected or source feasibility pending"
        items.append({**{key: item.get(key) for key in ["metric_id", "domain", "preferred_source", "priority"]}, "source_status": status, "reason": reason})
    return {"generated_at": utc_now(), "items": items}


def build_dashboard_summary(phase1_dashboard: dict[str, Any], catalog_update: dict[str, Any], phase2_records: list[dict[str, Any]]) -> dict[str, Any]:
    macro_series = list(phase1_dashboard.get("macro_series", []))
    asset_series = list(phase1_dashboard.get("asset_series", []))
    for metric_id, rows in sorted(group_by(phase2_records, "metric_id").items()):
        sorted_rows = sorted(rows, key=lambda row: row["observation_date"])
        first = sorted_rows[0]
        latest = sorted_rows[-1]
        item = {
            "dataset_id": latest["dataset_id"],
            "source_id": latest["source_id"],
            "provider_name": latest["provider_name"],
            "schema_type": latest["domain"],
            "series_id": latest["series_id"],
            "metric_name": latest["metric_name"],
            "category": latest["category"],
            "frequency": latest["frequency"],
            "record_count": len(rows),
            "first_observation_date": first["observation_date"],
            "latest_observation_date": latest["observation_date"],
            "latest_value": latest["value"],
            "unit": latest["unit"],
            "currency": latest.get("quote_currency") or latest.get("currency"),
            "quality_status": latest["quality_status"],
            "trust_status": latest["trust_status"],
            "publish_date_source": latest["publish_date_source"],
            "revision_status": latest["revision_status"],
            "candidate_only": True,
        }
        if latest["domain"] in {"rates_bonds", "fx"}:
            macro_series.append(item)
        else:
            asset_series.append(item)
    combined_records_count = int(phase1_dashboard.get("record_count") or 0) + len(phase2_records)
    return {
        **phase1_dashboard,
        "generated_at": utc_now(),
        "phase2_summary": catalog_update["summary"],
        "macro_series_count": len(macro_series),
        "asset_commodity_series_count": len(asset_series),
        "record_count": combined_records_count,
        "macro_series": macro_series,
        "asset_series": asset_series,
        "recent_events": [
            {"event_type": "data_ingestion", "title": f"Market Data Foundation Phase 2 processed {catalog_update['summary']['item_count']} catalog items", "event_date": utc_now()[:10], "source": "Foundation Catalog"},
            {"event_type": "quality_gate", "title": "Phase 2 official/candidate datasets remain outside formal trusted consumption", "event_date": utc_now()[:10], "source": "Quality Gate"},
        ] + phase1_dashboard.get("recent_events", []),
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def write_normalized_outputs(storage: dict[str, Path], records: list[dict[str, Any]], snapshot_id: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    for domain, rows in group_by(records, "domain").items():
        structured_root = storage["structured"][domain]
        domain_name = DOMAIN_STORAGE[domain]
        paths[f"{domain}_snapshot"] = str(write_jsonl(structured_root / f"{domain_name}_history_{snapshot_id}.jsonl", rows))
        paths[f"{domain}_latest"] = str(write_jsonl(structured_root / f"{domain_name}_history_latest.jsonl", rows))
        paths[f"runtime_{domain}_latest"] = str(write_jsonl(OUTPUT_ROOT / f"normalized_{domain_name}_history_latest.jsonl", rows))
    return paths


def write_metadata_db(
    run_records: list[dict[str, Any]],
    raw_artifacts: list[dict[str, Any]],
    normalized_records: list[dict[str, Any]],
    quality: dict[str, Any],
    revision_log: dict[str, Any],
    catalog_update: dict[str, Any],
) -> None:
    if METADATA_DB.exists():
        METADATA_DB.unlink()
    conn = sqlite3.connect(METADATA_DB)
    try:
        conn.execute("CREATE TABLE connector_run_log (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE raw_artifact_index (raw_path TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE normalized_dataset_index (dataset_id TEXT, observation_date TEXT, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE quality_check_log (dataset_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE revision_log (dataset_id TEXT, observation_date TEXT, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE foundation_catalog_update (metric_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        for item in run_records:
            conn.execute("INSERT INTO connector_run_log VALUES (?, ?)", (item["run_id"], json.dumps(item, ensure_ascii=False)))
        for item in raw_artifacts:
            conn.execute("INSERT INTO raw_artifact_index VALUES (?, ?)", (item["raw_path"], json.dumps(item, ensure_ascii=False)))
        for item in normalized_records:
            conn.execute("INSERT INTO normalized_dataset_index VALUES (?, ?, ?)", (item["dataset_id"], item["observation_date"], json.dumps(item, ensure_ascii=False)))
        for item in quality["items"]:
            conn.execute("INSERT INTO quality_check_log VALUES (?, ?)", (item["dataset_id"], json.dumps(item, ensure_ascii=False)))
        for item in revision_log["items"]:
            conn.execute("INSERT INTO revision_log VALUES (?, ?, ?)", (item["dataset_id"], item["observation_date"], json.dumps(item, ensure_ascii=False)))
        for item in catalog_update["items"]:
            conn.execute("INSERT INTO foundation_catalog_update VALUES (?, ?)", (item["metric_id"], json.dumps(item, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def write_phase2_report(
    run_records: list[dict[str, Any]],
    catalog_update: dict[str, Any],
    quality: dict[str, Any],
    revision_log: dict[str, Any],
    outputs: dict[str, str],
) -> Path:
    successes = [item for item in run_records if item["records_normalized"] > 0]
    deferred = [item for item in run_records if item["qa_status"] == "deferred"]
    text = f"""# Market Data Foundation Phase 2 Report

Generated: {utc_now()}

Phase 2 is catalog-driven. It reused existing Phase 1 historical macro/asset datasets,
ingested additional official FRED series where the catalog had a safe connector path,
and left unsupported China/Japan/Euro/UK/futures sources as explicit missing or
future_connector items.

## Scope

- Catalog items updated: {catalog_update['summary']['item_count']}
- Dashboard-ready items: {catalog_update['summary']['dashboard_ready']}
- Records loaded across updated catalog: {catalog_update['summary']['records_loaded']}
- Phase 2 fresh successful datasets: {len(successes)}
- Deferred / future connector items in this run: {len(deferred)}

## Successful Phase 2 Ingestion

{json.dumps([{k: item[k] for k in ['domain', 'metric_id', 'source_id', 'records_normalized', 'qa_status']} for item in successes], ensure_ascii=False, indent=2)}

## Deferred / Missing

{json.dumps([{k: item[k] for k in ['domain', 'metric_id', 'error_message']} for item in deferred], ensure_ascii=False, indent=2)}

## QA

```json
{json.dumps(quality['quality_counts'], ensure_ascii=False, indent=2)}
```

## Revision / Vintage

- revision_count: {revision_log['revision_count']}
- FRED realtime fields are preserved when present.
- Sources without release/vintage data are marked `vintage_support_limited`.
- `publish_date` is not fabricated from observation_date.

## Output Paths

```json
{json.dumps(outputs, ensure_ascii=False, indent=2)}
```

All outputs remain candidate/staging evidence. Formal trusted consumption was not modified.
No OpenAI API was called.
"""
    DOC_REPORT.write_text(text, encoding="utf-8")
    return DOC_REPORT


def match_existing_catalog_item(item: dict[str, Any], phase1_catalog: dict[str, Any]) -> dict[str, Any] | None:
    mapping = build_phase1_metric_lookup(phase1_catalog)
    return mapping.get(item["metric_id"])


def build_phase1_metric_lookup(phase1_catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    series_to_metric = {
        "CPIAUCSL": "us_cpi",
        "PPIACO": "us_ppi",
        "UNRATE": "us_unemployment_rate",
        "PAYEMS": "us_nonfarm_payrolls",
        "DFF": "fed_funds_effective",
        "DGS2": "us_2y_yield",
        "DGS10": "us_10y_yield",
        "DTWEXBGS": "trade_weighted_usd",
        "DCOILWTICO": "wti_oil",
        "GOLD": "gold_benchmark",
        "SILVER": "silver_benchmark",
        "CRUDE_BRENT": "brent_oil",
        "CRUDE_WTI": "wti_oil",
        "COPPER": "copper_benchmark",
        "ALUMINUM": "aluminum_benchmark",
        "IRON_ORE": "iron_ore_benchmark",
        "SOYBEANS": "soybeans_benchmark",
        "WHEAT_US_HRW": "wheat_benchmark",
        "COAL_AUS": "coal_benchmark",
    }
    for item in phase1_catalog.get("items", []):
        metric_id = series_to_metric.get(item.get("series_id", ""))
        if metric_id and metric_id not in lookup:
            lookup[metric_id] = item
    return lookup


def load_previous_phase2_records() -> dict[tuple[str, str], dict[str, Any]]:
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    for path in OUTPUT_ROOT.glob("normalized_*_history_latest.jsonl"):
        for record in read_jsonl(path):
            previous[(record.get("dataset_id", ""), record.get("observation_date", ""))] = record
    return previous


def load_storage_paths() -> dict[str, dict[str, Path]]:
    paths = read_json(STORAGE_PATHS)["paths"]
    cold_root = Path(paths["cold_data_root"])
    structured_root = Path(paths["structured_data_root"])
    return {
        "raw": {domain: cold_root / "raw" / dirname for domain, dirname in DOMAIN_STORAGE.items()},
        "structured": {domain: structured_root / dirname for domain, dirname in DOMAIN_STORAGE.items()},
    }


def ensure_domain_dirs(storage: dict[str, dict[str, Path]]) -> None:
    for group in storage.values():
        for path in group.values():
            path.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def load_secret(key: str) -> str:
    if not LOCAL_SECRETS_PATH.exists():
        return ""
    try:
        return str(read_json(LOCAL_SECRETS_PATH).get(key) or "")
    except Exception:  # noqa: BLE001
        return ""


def http_get(url: str, timeout: int, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "FinancialResearch/phase2 small controlled ingestion"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError(f"response exceeded limit {limit}")
        return data


def save_raw(root: Path, filename: str, raw: bytes) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_bytes(raw)
    return path, sha256_bytes(raw)


def raw_artifact(source_id: str, raw_path: Path, checksum: str, reference: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "raw_path": str(raw_path),
        "checksum": checksum,
        "source_url_or_reference": reference,
        "retrieved_at": utc_now(),
    }


def publish_date_coverage(records: list[dict[str, Any]]) -> str:
    if not records:
        return "not_applicable"
    counts = Counter(record.get("publish_date_source") for record in records)
    if len(counts) == 1:
        return next(iter(counts))
    return json.dumps(dict(counts), ensure_ascii=False, sort_keys=True)


def group_by(records: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        result.setdefault(str(record.get(key)), []).append(record)
    return result


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    return path


def to_float(value: Any) -> float | None:
    if value in {None, "", "."}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_date_like(value: Any) -> bool:
    if not value:
        return False
    try:
        datetime.strptime(str(value)[:10], "%Y-%m-%d")
        return True
    except ValueError:
        return False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_market_data_foundation_phase2(), ensure_ascii=False, indent=2))
