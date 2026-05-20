from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion"
LOCAL_SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
STORAGE_PATHS = PROJECT_ROOT / "config" / "storage_paths.json"
METADATA_DB = OUTPUT_ROOT / "macro_asset_metadata.sqlite"

DOC_REPORT = PROJECT_ROOT / "docs" / "MACRO_ASSET_HISTORICAL_DATA_INGESTION_REPORT.md"
DOC_SCHEMA = PROJECT_ROOT / "docs" / "MACRO_ASSET_DATA_SCHEMA.md"
DOC_VINTAGE = PROJECT_ROOT / "docs" / "MACRO_ASSET_DATA_VINTAGE_AND_REVISION.md"
DOC_QUALITY = PROJECT_ROOT / "docs" / "MACRO_ASSET_QUALITY_GATE.md"


FRED_SERIES = [
    {"series_id": "DGS10", "metric_name": "10y_treasury_yield", "category": "rates", "unit": "percent", "frequency": "daily"},
    {"series_id": "DGS2", "metric_name": "2y_treasury_yield", "category": "rates", "unit": "percent", "frequency": "daily"},
    {"series_id": "DFF", "metric_name": "effective_federal_funds_rate", "category": "central_bank_policy", "unit": "percent", "frequency": "daily"},
    {"series_id": "CPIAUCSL", "metric_name": "us_cpi", "category": "inflation", "unit": "index", "frequency": "monthly"},
    {"series_id": "PPIACO", "metric_name": "us_ppi_all_commodities", "category": "inflation", "unit": "index", "frequency": "monthly"},
    {"series_id": "UNRATE", "metric_name": "us_unemployment_rate", "category": "employment", "unit": "percent", "frequency": "monthly"},
    {"series_id": "PAYEMS", "metric_name": "us_nonfarm_payrolls", "category": "employment", "unit": "thousands_persons", "frequency": "monthly"},
    {"series_id": "DCOILWTICO", "metric_name": "wti_crude_oil_spot_price", "category": "energy", "unit": "USD_per_barrel", "frequency": "daily"},
    {"series_id": "DTWEXBGS", "metric_name": "nominal_broad_usd_index", "category": "currency", "unit": "index", "frequency": "daily"},
]


BLS_SERIES = [
    {"series_id": "CUUR0000SA0", "metric_name": "us_cpi_all_urban_consumers", "category": "inflation", "unit": "index", "start_year": 1913},
    {"series_id": "WPUFD4", "metric_name": "us_ppi_final_demand", "category": "inflation", "unit": "index", "start_year": 2009},
    {"series_id": "LNS14000000", "metric_name": "us_unemployment_rate", "category": "employment", "unit": "percent", "start_year": 1948},
    {"series_id": "CES0000000001", "metric_name": "us_nonfarm_payrolls", "category": "employment", "unit": "thousands_persons", "start_year": 1939},
]


WORLD_BANK_COMMODITY_GROUPS = {
    "CRUDE_WTI": ("energy", "WTI crude oil"),
    "CRUDE_BRENT": ("energy", "Brent crude oil"),
    "NATURAL_GAS_US": ("energy", "US natural gas"),
    "COAL_AUS": ("energy", "Australian coal"),
    "COPPER": ("metals", "Copper"),
    "ALUMINUM": ("metals", "Aluminum"),
    "IRON_ORE": ("metals", "Iron ore"),
    "GOLD": ("precious_metals", "Gold"),
    "SILVER": ("precious_metals", "Silver"),
    "WHEAT_US_HRW": ("agriculture", "US HRW wheat"),
    "CORN": ("agriculture", "Corn"),
    "SOYBEANS": ("agriculture", "Soybeans"),
}


@dataclass
class StorageContext:
    raw_macro_root: Path
    raw_asset_root: Path
    raw_commodity_root: Path
    structured_macro_root: Path
    structured_asset_root: Path
    structured_commodity_root: Path


def run_macro_asset_historical_ingestion() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    context = load_storage_context()
    ensure_storage_dirs(context)
    init_metadata_db()
    snapshot_id = "macro_asset_snapshot_" + utc_now().replace(":", "").replace("-", "")
    previous_latest = load_previous_latest_records()

    run_results: list[dict[str, Any]] = []
    normalized_records: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []

    for series in FRED_SERIES:
        result = fetch_fred_series(context, series, snapshot_id)
        run_results.append(result["run"])
        raw_artifacts.extend(result["raw_artifacts"])
        normalized_records.extend(result["records"])

    for series in BLS_SERIES:
        result = fetch_bls_series(context, series, snapshot_id)
        run_results.append(result["run"])
        raw_artifacts.extend(result["raw_artifacts"])
        normalized_records.extend(result["records"])

    treasury_result = fetch_treasury_avg_interest_rates(context, snapshot_id)
    run_results.append(treasury_result["run"])
    raw_artifacts.extend(treasury_result["raw_artifacts"])
    normalized_records.extend(treasury_result["records"])

    wb_result = fetch_world_bank_pink_sheet(context, snapshot_id)
    run_results.append(wb_result["run"])
    raw_artifacts.extend(wb_result["raw_artifacts"])
    normalized_records.extend(wb_result["records"])

    macro_records = [record for record in normalized_records if record.get("schema_type") == "macro"]
    asset_records = [record for record in normalized_records if record.get("schema_type") == "asset_class"]
    commodity_records = [record for record in normalized_records if record.get("schema_type") == "commodity"]

    normalized_paths = write_normalized_outputs(context, macro_records, asset_records, commodity_records, snapshot_id)
    quality = run_quality_gate(normalized_records)
    revision_log = detect_revisions(previous_latest, normalized_records)
    catalog = build_dataset_catalog(normalized_records, run_results, normalized_paths)
    category_mapping = build_category_mapping(catalog)
    dashboard_summary = build_dashboard_macro_asset_summary(catalog, normalized_records, quality, revision_log)
    ingestion_summary = {
        "generated_at": utc_now(),
        "retrieval_snapshot_id": snapshot_id,
        "run_count": len(run_results),
        "success_count": sum(1 for item in run_results if item["status"] == "success"),
        "failed_count": sum(1 for item in run_results if item["status"] == "failed"),
        "source_counts": source_counts(normalized_records),
        "series_count": len({record["series_id"] for record in normalized_records}),
        "record_count": len(normalized_records),
        "raw_artifact_count": len(raw_artifacts),
        "normalized_paths": normalized_paths,
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
    }

    write_json(OUTPUT_ROOT / "historical_ingestion_run_results.json", {"generated_at": utc_now(), "items": run_results})
    write_json(OUTPUT_ROOT / "raw_artifact_index.json", {"generated_at": utc_now(), "items": raw_artifacts})
    write_json(OUTPUT_ROOT / "quality_results.json", quality)
    write_json(OUTPUT_ROOT / "revision_log.json", revision_log)
    write_json(OUTPUT_ROOT / "dataset_catalog.json", catalog)
    write_json(OUTPUT_ROOT / "category_mapping.json", category_mapping)
    write_json(OUTPUT_ROOT / "dashboard_macro_asset_summary.json", dashboard_summary)
    write_json(OUTPUT_ROOT / "ingestion_summary.json", ingestion_summary)
    write_metadata_db(run_results, raw_artifacts, catalog, quality, revision_log, normalized_paths)
    write_docs(ingestion_summary, catalog, quality, revision_log)
    return ingestion_summary


def load_storage_context() -> StorageContext:
    storage = read_json(STORAGE_PATHS)["paths"]
    cold = Path(storage["cold_data_root"])
    structured = Path(storage["structured_data_root"])
    return StorageContext(
        raw_macro_root=cold / "raw" / "macro",
        raw_asset_root=cold / "raw" / "asset_class",
        raw_commodity_root=cold / "raw" / "commodity",
        structured_macro_root=structured / "macro",
        structured_asset_root=structured / "asset_class",
        structured_commodity_root=structured / "commodity",
    )


def ensure_storage_dirs(context: StorageContext) -> None:
    for path in [
        context.raw_macro_root,
        context.raw_asset_root,
        context.raw_commodity_root,
        context.structured_macro_root,
        context.structured_asset_root,
        context.structured_commodity_root,
        OUTPUT_ROOT,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def fetch_fred_series(context: StorageContext, series: dict[str, str], snapshot_id: str) -> dict[str, Any]:
    source_id = "fred_public_api"
    key = load_fred_key()
    params = {
        "series_id": series["series_id"],
        "file_type": "json",
        "observation_start": "1776-07-04",
    }
    if key:
        params["api_key"] = key
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
    safe_reference = f"https://api.stlouisfed.org/fred/series/observations?series_id={series['series_id']}&file_type=json"
    try:
        raw = http_get(url, timeout=30, limit=25_000_000)
        if key:
            raw = raw.replace(key.encode("utf-8"), b"****")
        raw_path, checksum = save_raw(context.raw_macro_root / "fred_public_api", f"fred_{series['series_id']}_full_history.json", raw)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        records = []
        for row in payload.get("observations", []):
            value = to_float(row.get("value"))
            if value is None:
                continue
            observation_date = row.get("date")
            records.append(
                macro_record(
                    snapshot_id=snapshot_id,
                    source_id=source_id,
                    provider_name="FRED",
                    series_id=series["series_id"],
                    metric_name=series["metric_name"],
                    macro_category=series["category"],
                    country="US",
                    frequency=series["frequency"],
                    observation_date=observation_date,
                    value=value,
                    unit=series["unit"],
                    seasonal_adjustment="source_default",
                    vintage_date=row.get("realtime_start"),
                    revision_status="vintage_available" if row.get("realtime_start") else "vintage_support_limited",
                    raw_path=raw_path,
                    checksum=checksum,
                    publish_date=None,
                    publish_date_source="unavailable",
                )
            )
        return source_result(source_id, f"fred_{series['series_id']}_full_history", "success" if records else "failed", records, [raw_artifact(source_id, raw_path, checksum, safe_reference)], "")
    except Exception as exc:  # noqa: BLE001
        return source_result(source_id, f"fred_{series['series_id']}_full_history", "failed", [], [], f"{type(exc).__name__}: {str(exc)[:400]}")


def fetch_bls_series(context: StorageContext, series: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    source_id = "bls_public_api"
    current_year = date.today().year
    all_records: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []
    errors: list[str] = []
    for start_year in range(int(series["start_year"]), current_year + 1, 10):
        end_year = min(start_year + 9, current_year)
        payload = {
            "seriesid": [series["series_id"]],
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        data = json.dumps(payload).encode("utf-8")
        url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        try:
            raw = http_post(url, data, headers={"Content-Type": "application/json"}, timeout=30, limit=8_000_000)
            raw_path, checksum = save_raw(context.raw_macro_root / "bls_public_api", f"bls_{series['series_id']}_{start_year}_{end_year}.json", raw)
            raw_artifacts.append(raw_artifact(source_id, raw_path, checksum, f"{url} {series['series_id']} {start_year}-{end_year}"))
            response = json.loads(raw.decode("utf-8", errors="replace"))
            for item in response.get("Results", {}).get("series", []):
                for row in item.get("data", []):
                    period = row.get("period", "")
                    if not period.startswith("M"):
                        continue
                    value = to_float(row.get("value"))
                    if value is None:
                        continue
                    obs_date = f"{row.get('year')}-{period[1:]}-01"
                    footnotes = [note.get("text") for note in row.get("footnotes", []) if note.get("text")]
                    all_records.append(
                        macro_record(
                            snapshot_id=snapshot_id,
                            source_id=source_id,
                            provider_name="BLS",
                            series_id=series["series_id"],
                            metric_name=series["metric_name"],
                            macro_category=series["category"],
                            country="US",
                            frequency="monthly",
                            observation_date=obs_date,
                            value=value,
                            unit=series["unit"],
                            seasonal_adjustment="not_seasonally_adjusted" if series["series_id"].startswith("CUU") else "source_default",
                            vintage_date=None,
                            revision_status="source_footnote_present" if footnotes else "vintage_support_limited",
                            raw_path=raw_path,
                            checksum=checksum,
                            publish_date=None,
                            publish_date_source="unavailable",
                            extra={"footnotes": footnotes},
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{start_year}-{end_year}: {type(exc).__name__}: {str(exc)[:240]}")
            time.sleep(1)
    status = "success" if all_records else "failed"
    return source_result(source_id, f"bls_{series['series_id']}_full_history", status, all_records, raw_artifacts, "; ".join(errors))


def fetch_treasury_avg_interest_rates(context: StorageContext, snapshot_id: str) -> dict[str, Any]:
    source_id = "treasury_fiscaldata"
    url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates?sort=record_date&page[size]=10000"
    try:
        raw = http_get(url, timeout=30, limit=25_000_000)
        raw_path, checksum = save_raw(context.raw_macro_root / "treasury_fiscaldata", "treasury_avg_interest_rates_full.json", raw)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        records = []
        for row in payload.get("data", []):
            value = to_float(row.get("avg_interest_rate_amt"))
            if value is None:
                continue
            security_desc = str(row.get("security_desc") or "treasury_average_interest_rate")
            record_date = row.get("record_date")
            records.append(
                macro_record(
                    snapshot_id=snapshot_id,
                    source_id=source_id,
                    provider_name="U.S. Treasury FiscalData",
                    series_id="avg_interest_rates:" + security_desc.replace(" ", "_").lower(),
                    metric_name="treasury_average_interest_rate",
                    macro_category="treasury",
                    country="US",
                    frequency="monthly",
                    observation_date=record_date,
                    value=value,
                    unit="percent",
                    seasonal_adjustment="not_applicable",
                    vintage_date=None,
                    revision_status="vintage_support_limited",
                    raw_path=raw_path,
                    checksum=checksum,
                    publish_date=record_date,
                    publish_date_source="source_confirmed_record_date",
                    extra={"security_desc": security_desc},
                )
            )
        return source_result(source_id, "treasury_avg_interest_rates_full_history", "success" if records else "failed", records, [raw_artifact(source_id, raw_path, checksum, url)], "")
    except Exception as exc:  # noqa: BLE001
        return source_result(source_id, "treasury_avg_interest_rates_full_history", "failed", [], [], f"{type(exc).__name__}: {str(exc)[:400]}")


def fetch_world_bank_pink_sheet(context: StorageContext, snapshot_id: str) -> dict[str, Any]:
    source_id = "world_bank_pink_sheet"
    url = "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
    try:
        raw = http_get(url, timeout=45, limit=15_000_000)
        raw_path, checksum = save_raw(context.raw_commodity_root / "world_bank_pink_sheet", "world_bank_pink_sheet_monthly_full.xlsx", raw)
        records = parse_world_bank_pink_sheet(raw_path, checksum, snapshot_id)
        return source_result(source_id, "world_bank_pink_sheet_monthly_full_history", "success" if records else "failed", records, [raw_artifact(source_id, raw_path, checksum, url)], "")
    except Exception as exc:  # noqa: BLE001
        return source_result(source_id, "world_bank_pink_sheet_monthly_full_history", "failed", [], [], f"{type(exc).__name__}: {str(exc)[:400]}")


def parse_world_bank_pink_sheet(raw_path: Path, checksum: str, snapshot_id: str) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_excel(raw_path, sheet_name="Monthly Prices", header=None)
    headers = list(df.iloc[4])
    units = list(df.iloc[5])
    codes = list(df.iloc[6])
    data = df.iloc[7:]
    records = []
    for col_idx, code in enumerate(codes):
        if code not in WORLD_BANK_COMMODITY_GROUPS:
            continue
        commodity_group, instrument_name = WORLD_BANK_COMMODITY_GROUPS[code]
        for _, row in data.iterrows():
            value = to_float(row.iloc[col_idx])
            period = month_label_to_date(str(row.iloc[0]))
            if value is None or not period:
                continue
            unit = str(units[col_idx])
            records.append(
                commodity_record(
                    snapshot_id=snapshot_id,
                    source_id="world_bank_pink_sheet",
                    provider_name="World Bank Pink Sheet",
                    series_id=str(code),
                    asset_class="commodities",
                    commodity_group=commodity_group,
                    instrument_name=instrument_name,
                    metric_name=str(headers[col_idx]),
                    frequency="monthly",
                    observation_date=period,
                    value=value,
                    unit=unit,
                    currency="USD" if "$" in unit or "US" in unit else "",
                    raw_path=raw_path,
                    checksum=checksum,
                    publish_date=None,
                    publish_date_source="unavailable",
                )
            )
    return records


def macro_record(
    snapshot_id: str,
    source_id: str,
    provider_name: str,
    series_id: str,
    metric_name: str,
    macro_category: str,
    country: str,
    frequency: str,
    observation_date: str,
    value: float,
    unit: str,
    seasonal_adjustment: str,
    vintage_date: str | None,
    revision_status: str,
    raw_path: Path,
    checksum: str,
    publish_date: str | None,
    publish_date_source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_type": "macro",
        "dataset_id": f"{source_id}:{series_id}",
        "retrieval_snapshot_id": snapshot_id,
        "source_id": source_id,
        "provider_name": provider_name,
        "series_id": series_id,
        "metric_name": metric_name,
        "macro_category": macro_category,
        "country": country,
        "frequency": frequency,
        "data_period_start": observation_date,
        "data_period_end": observation_date,
        "observation_date": observation_date,
        "publish_date": publish_date,
        "publish_date_source": publish_date_source,
        "value": value,
        "unit": unit,
        "seasonal_adjustment": seasonal_adjustment,
        "vintage_date": vintage_date,
        "revision_status": revision_status,
        "retrieved_at": utc_now(),
        "raw_path": str(raw_path),
        "checksum": checksum,
        "quality_status": "pending_quality",
        "trust_status": "trusted_by_real_external_candidate",
        "candidate_only": True,
        **(extra or {}),
    }


def commodity_record(
    snapshot_id: str,
    source_id: str,
    provider_name: str,
    series_id: str,
    asset_class: str,
    commodity_group: str,
    instrument_name: str,
    metric_name: str,
    frequency: str,
    observation_date: str,
    value: float,
    unit: str,
    currency: str,
    raw_path: Path,
    checksum: str,
    publish_date: str | None,
    publish_date_source: str,
) -> dict[str, Any]:
    return {
        "schema_type": "commodity",
        "dataset_id": f"{source_id}:{series_id}",
        "retrieval_snapshot_id": snapshot_id,
        "source_id": source_id,
        "provider_name": provider_name,
        "asset_class": asset_class,
        "commodity_group": commodity_group,
        "instrument_name": instrument_name,
        "series_id": series_id,
        "metric_name": metric_name,
        "frequency": frequency,
        "data_period_start": observation_date,
        "data_period_end": observation_date,
        "observation_date": observation_date,
        "publish_date": publish_date,
        "publish_date_source": publish_date_source,
        "price": value,
        "value": value,
        "unit": unit,
        "currency": currency,
        "vintage_date": None,
        "revision_status": "vintage_support_limited",
        "retrieved_at": utc_now(),
        "raw_path": str(raw_path),
        "checksum": checksum,
        "quality_status": "pending_quality",
        "trust_status": "trusted_by_real_external_candidate",
        "candidate_only": True,
    }


def source_result(source_id: str, connector_name: str, status: str, records: list[dict[str, Any]], raw_artifacts: list[dict[str, Any]], error: str) -> dict[str, Any]:
    return {
        "run": {
            "run_id": "run_" + hash_short(f"{source_id}|{connector_name}|{utc_now()}"),
            "source_id": source_id,
            "connector_name": connector_name,
            "status": status,
            "record_count": len(records),
            "series_count": len({record.get("series_id") for record in records}),
            "retrieved_at": utc_now(),
            "candidate_only": True,
            "formal_trusted_consumption": False,
            "error_message": error,
        },
        "records": records,
        "raw_artifacts": raw_artifacts,
    }


def raw_artifact(source_id: str, raw_path: Path, checksum: str, reference: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "raw_path": str(raw_path),
        "checksum": checksum,
        "source_url_or_reference": reference,
        "retrieved_at": utc_now(),
    }


def write_normalized_outputs(
    context: StorageContext,
    macro_records: list[dict[str, Any]],
    asset_records: list[dict[str, Any]],
    commodity_records: list[dict[str, Any]],
    snapshot_id: str,
) -> dict[str, str]:
    paths = {
        "macro_snapshot": str(write_jsonl(context.structured_macro_root / f"macro_history_{snapshot_id}.jsonl", macro_records)),
        "macro_latest": str(write_jsonl(context.structured_macro_root / "macro_history_latest.jsonl", macro_records)),
        "asset_snapshot": str(write_jsonl(context.structured_asset_root / f"asset_class_history_{snapshot_id}.jsonl", asset_records)),
        "asset_latest": str(write_jsonl(context.structured_asset_root / "asset_class_history_latest.jsonl", asset_records)),
        "commodity_snapshot": str(write_jsonl(context.structured_commodity_root / f"commodity_history_{snapshot_id}.jsonl", commodity_records)),
        "commodity_latest": str(write_jsonl(context.structured_commodity_root / "commodity_history_latest.jsonl", commodity_records)),
        "runtime_macro_latest": str(write_jsonl(OUTPUT_ROOT / "normalized_macro_history_latest.jsonl", macro_records)),
        "runtime_asset_latest": str(write_jsonl(OUTPUT_ROOT / "normalized_asset_class_history_latest.jsonl", asset_records)),
        "runtime_commodity_latest": str(write_jsonl(OUTPUT_ROOT / "normalized_commodity_history_latest.jsonl", commodity_records)),
    }
    return paths


def run_quality_gate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_dataset.setdefault(record["dataset_id"], []).append(record)
    items = []
    for dataset_id, rows in sorted(by_dataset.items()):
        checks = {
            "required_fields_present": all(record.get("dataset_id") and record.get("source_id") and record.get("series_id") for record in rows),
            "value_numeric": all(isinstance(record.get("value"), (int, float)) for record in rows),
            "date_parseable": all(is_date_like(record.get("observation_date")) for record in rows),
            "duplicate_series_observation": len({(record.get("series_id"), record.get("observation_date")) for record in rows}) == len(rows),
            "unit_present": all(bool(record.get("unit")) for record in rows),
            "currency_present_for_price_series": all(bool(record.get("currency")) for record in rows if record.get("schema_type") == "commodity"),
            "source_id_present": all(bool(record.get("source_id")) for record in rows),
            "raw_checksum_present": all(bool(record.get("checksum")) for record in rows),
            "publish_date_status_classified": all(record.get("publish_date_source") in {"source_confirmed", "source_confirmed_record_date", "inferred", "user_override", "unavailable", "not_applicable"} for record in rows),
            "revision_vintage_status_classified": all(bool(record.get("revision_status")) for record in rows),
        }
        values = [float(record["value"]) for record in rows if isinstance(record.get("value"), (int, float))]
        missing_ratio = 1 - (len(values) / len(rows)) if rows else 1
        checks["missing_value_ratio_ok"] = missing_ratio <= 0.05
        checks["extreme_outlier_detection"] = detect_outlier_warning(values) != "extreme_outlier_blocking"
        checks["frequency_consistency"] = len(rows) > 1
        failed_checks = [key for key, value in checks.items() if not value]
        status = "quality_passed"
        if failed_checks:
            status = "quality_failed" if any(key in failed_checks for key in ["required_fields_present", "value_numeric", "date_parseable", "source_id_present", "raw_checksum_present"]) else "quality_warning"
        for record in rows:
            record["quality_status"] = status
            if status != "quality_passed":
                record["trust_status"] = "trusted_source_but_quality_failed"
        items.append(
            {
                "dataset_id": dataset_id,
                "series_id": rows[0].get("series_id"),
                "source_id": rows[0].get("source_id"),
                "record_count": len(rows),
                "quality_status": status,
                "failed_checks": failed_checks,
                "missing_value_ratio": round(missing_ratio, 4),
                "publish_date_source_counts": dict(source_counts(rows, field="publish_date_source")),
                "vintage_support": rows[0].get("revision_status"),
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


def detect_revisions(previous_latest: dict[tuple[str, str], dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    revisions = []
    detected_at = utc_now()
    for record in records:
        key = (record.get("series_id", ""), record.get("observation_date", ""))
        old = previous_latest.get(key)
        if not old:
            continue
        old_value = to_float(old.get("value"))
        new_value = to_float(record.get("value"))
        if old_value is None or new_value is None:
            continue
        if abs(old_value - new_value) > max(1e-9, abs(old_value) * 1e-10):
            revisions.append(
                {
                    "series_id": record.get("series_id"),
                    "observation_date": record.get("observation_date"),
                    "old_value": old_value,
                    "new_value": new_value,
                    "old_retrieved_at": old.get("retrieved_at"),
                    "new_retrieved_at": record.get("retrieved_at"),
                    "revision_detected_at": detected_at,
                    "source_id": record.get("source_id"),
                    "revision_type": "value_changed_since_previous_latest_snapshot",
                }
            )
    return {
        "generated_at": detected_at,
        "revision_count": len(revisions),
        "items": revisions,
        "vintage_policy": "Do not overwrite old observations for as-of analysis; record retrieval_snapshot_id and revision differences.",
    }


def load_previous_latest_records() -> dict[tuple[str, str], dict[str, Any]]:
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    for path in [
        OUTPUT_ROOT / "normalized_macro_history_latest.jsonl",
        OUTPUT_ROOT / "normalized_asset_class_history_latest.jsonl",
        OUTPUT_ROOT / "normalized_commodity_history_latest.jsonl",
    ]:
        if not path.exists():
            continue
        for record in read_jsonl(path):
            previous[(record.get("series_id", ""), record.get("observation_date", ""))] = record
    return previous


def build_dataset_catalog(records: list[dict[str, Any]], run_results: list[dict[str, Any]], normalized_paths: dict[str, str]) -> dict[str, Any]:
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_dataset.setdefault(record["dataset_id"], []).append(record)
    items = []
    for dataset_id, rows in sorted(by_dataset.items()):
        sorted_rows = sorted(rows, key=lambda item: item.get("observation_date") or "")
        first = sorted_rows[0]
        latest = sorted_rows[-1]
        items.append(
            {
                "dataset_id": dataset_id,
                "source_id": first.get("source_id"),
                "provider_name": first.get("provider_name"),
                "schema_type": first.get("schema_type"),
                "series_id": first.get("series_id"),
                "metric_name": first.get("metric_name"),
                "category": first.get("macro_category") or first.get("commodity_group") or first.get("asset_class"),
                "frequency": first.get("frequency"),
                "record_count": len(rows),
                "first_observation_date": first.get("observation_date"),
                "latest_observation_date": latest.get("observation_date"),
                "latest_value": latest.get("value"),
                "unit": latest.get("unit"),
                "currency": latest.get("currency"),
                "quality_status": latest.get("quality_status"),
                "trust_status": latest.get("trust_status"),
                "publish_date_source": latest.get("publish_date_source"),
                "revision_status": latest.get("revision_status"),
                "candidate_only": True,
            }
        )
    return {
        "generated_at": utc_now(),
        "dataset_count": len(items),
        "record_count": len(records),
        "run_results": run_results,
        "normalized_paths": normalized_paths,
        "items": items,
    }


def build_category_mapping(catalog: dict[str, Any]) -> dict[str, Any]:
    mapping: dict[str, list[str]] = {}
    for item in catalog["items"]:
        mapping.setdefault(item["category"] or "uncategorized", []).append(item["dataset_id"])
    return {
        "generated_at": utc_now(),
        "macro_categories": ["rates", "inflation", "employment", "money_supply", "currency", "treasury", "central_bank_policy"],
        "asset_class_categories": ["energy", "metals", "precious_metals", "agriculture", "bonds", "currency", "equity_index", "commodities"],
        "mapping": mapping,
    }


def build_dashboard_macro_asset_summary(catalog: dict[str, Any], records: list[dict[str, Any]], quality: dict[str, Any], revision_log: dict[str, Any]) -> dict[str, Any]:
    macro_items = [item for item in catalog["items"] if item["schema_type"] == "macro"]
    commodity_items = [item for item in catalog["items"] if item["schema_type"] == "commodity"]
    latest_by_category = {}
    for item in catalog["items"]:
        category = item.get("category") or item.get("schema_type")
        latest_by_category.setdefault(category, []).append(item)
    return {
        "generated_at": utc_now(),
        "macro_series_count": len(macro_items),
        "asset_commodity_series_count": len(commodity_items),
        "record_count": len(records),
        "quality_counts": quality["quality_counts"],
        "publish_date_coverage": dict(source_counts(records, field="publish_date_source")),
        "revision_count": revision_log["revision_count"],
        "vintage_warning": "Some official datasets have vintage_support_limited; use retrieval_snapshot_id for as-of analysis.",
        "top_summary_cards": build_top_summary_cards(catalog["items"]),
        "macro_series": macro_items,
        "asset_series": commodity_items,
        "recent_events": build_recent_event_ticker(catalog["items"], quality, revision_log),
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def build_top_summary_cards(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred = ["DGS10", "CPIAUCSL", "UNRATE", "DCOILWTICO", "GOLD", "COPPER", "CRUDE_WTI"]
    cards = []
    by_series = {item["series_id"]: item for item in items}
    for series in preferred:
        item = by_series.get(series)
        if not item:
            continue
        cards.append(
            {
                "title": item["metric_name"],
                "series_id": item["series_id"],
                "latest_value": item["latest_value"],
                "unit": item.get("unit") or item.get("currency") or "",
                "latest_observation_date": item["latest_observation_date"],
                "quality_status": item["quality_status"],
                "publish_date_source": item["publish_date_source"],
                "candidate_only": True,
            }
        )
    return cards[:8]


def build_recent_event_ticker(items: list[dict[str, Any]], quality: dict[str, Any], revision_log: dict[str, Any]) -> list[dict[str, Any]]:
    ticker = [
        {
            "event_type": "data_ingestion",
            "title": f"Macro/asset historical ingestion updated {len(items)} datasets",
            "event_date": utc_now()[:10],
            "source": "FRDataConnectors",
        },
        {
            "event_type": "quality_gate",
            "title": f"Quality status: {quality['quality_counts']}",
            "event_date": utc_now()[:10],
            "source": "Quality Gate",
        },
    ]
    if revision_log["revision_count"]:
        ticker.append(
            {
                "event_type": "revision_detected",
                "title": f"{revision_log['revision_count']} revised observations detected",
                "event_date": utc_now()[:10],
                "source": "Revision Log",
            }
        )
    return ticker


def write_metadata_db(run_results: list[dict[str, Any]], raw_artifacts: list[dict[str, Any]], catalog: dict[str, Any], quality: dict[str, Any], revision_log: dict[str, Any], normalized_paths: dict[str, str]) -> None:
    if METADATA_DB.exists():
        METADATA_DB.unlink()
    conn = sqlite3.connect(METADATA_DB)
    try:
        conn.execute("create table ingestion_runs (source_id text, connector_name text, status text, record_count integer, retrieved_at text, error_message text)")
        conn.execute("create table raw_artifacts (source_id text, raw_path text, checksum text, source_url_or_reference text, retrieved_at text)")
        conn.execute("create table dataset_catalog (dataset_id text, source_id text, schema_type text, series_id text, category text, record_count integer, first_observation_date text, latest_observation_date text, quality_status text)")
        conn.execute("create table quality_results (dataset_id text, source_id text, quality_status text, failed_checks text)")
        conn.execute("create table revision_log (series_id text, observation_date text, old_value real, new_value real, revision_detected_at text, source_id text, revision_type text)")
        conn.execute("create table normalized_paths (name text, path text)")
        conn.executemany(
            "insert into ingestion_runs values (:source_id,:connector_name,:status,:record_count,:retrieved_at,:error_message)",
            run_results,
        )
        conn.executemany(
            "insert into raw_artifacts values (:source_id,:raw_path,:checksum,:source_url_or_reference,:retrieved_at)",
            raw_artifacts,
        )
        conn.executemany(
            "insert into dataset_catalog values (:dataset_id,:source_id,:schema_type,:series_id,:category,:record_count,:first_observation_date,:latest_observation_date,:quality_status)",
            catalog["items"],
        )
        conn.executemany(
            "insert into quality_results values (:dataset_id,:source_id,:quality_status,:failed_checks)",
            [
                {
                    "dataset_id": item["dataset_id"],
                    "source_id": item["source_id"],
                    "quality_status": item["quality_status"],
                    "failed_checks": json.dumps(item["failed_checks"], ensure_ascii=False),
                }
                for item in quality["items"]
            ],
        )
        conn.executemany(
            "insert into revision_log values (:series_id,:observation_date,:old_value,:new_value,:revision_detected_at,:source_id,:revision_type)",
            revision_log["items"],
        )
        conn.executemany("insert into normalized_paths values (?,?)", normalized_paths.items())
        conn.commit()
    finally:
        conn.close()


def write_docs(ingestion_summary: dict[str, Any], catalog: dict[str, Any], quality: dict[str, Any], revision_log: dict[str, Any]) -> None:
    DOC_REPORT.write_text(render_ingestion_report(ingestion_summary, catalog, quality), encoding="utf-8")
    DOC_SCHEMA.write_text(render_schema_doc(), encoding="utf-8")
    DOC_VINTAGE.write_text(render_vintage_doc(revision_log), encoding="utf-8")
    DOC_QUALITY.write_text(render_quality_doc(quality), encoding="utf-8")


def render_ingestion_report(ingestion_summary: dict[str, Any], catalog: dict[str, Any], quality: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {item['source_id']} | {item['series_id']} | {item['category']} | {item['record_count']} | {item['first_observation_date']} | {item['latest_observation_date']} | {item['quality_status']} |"
        for item in catalog["items"][:80]
    )
    return f"""# Macro Asset Historical Data Ingestion Report

Generated: {utc_now()}

Scope: macro and asset/commodity historical data only. No A-share full history, no full financial report download, no OpenAI API, no parse_lab change, and no formal trusted consumption update.

Summary:

- retrieval_snapshot_id: `{ingestion_summary['retrieval_snapshot_id']}`
- sources: {json.dumps(ingestion_summary['source_counts'], ensure_ascii=False)}
- series: {ingestion_summary['series_count']}
- records: {ingestion_summary['record_count']}
- raw artifacts: {ingestion_summary['raw_artifact_count']}
- quality: {json.dumps(quality['quality_counts'], ensure_ascii=False)}
- metadata DB: `{METADATA_DB}`

| Source | Series | Category | Records | First | Latest | Quality |
|---|---|---|---:|---|---|---|
{rows}
"""


def render_schema_doc() -> str:
    return """# Macro Asset Data Schema

Macro schema fields:

- dataset_id, source_id, provider_name, series_id, metric_name, country, frequency
- data_period_start, data_period_end, observation_date
- publish_date, publish_date_source
- value, unit, seasonal_adjustment
- vintage_date, revision_status
- retrieved_at, raw_path, checksum, quality_status, trust_status, candidate_only

Asset/commodity schema fields:

- dataset_id, source_id, provider_name, asset_class, commodity_group, instrument_name, metric_name, frequency
- data_period_start, data_period_end, observation_date
- publish_date, publish_date_source
- price, value, unit, currency
- vintage_date, revision_status
- retrieved_at, raw_path, checksum, quality_status, trust_status, candidate_only

No publish_date is fabricated. If no official release date is available, `publish_date=null` and `publish_date_source=unavailable`.
"""


def render_vintage_doc(revision_log: dict[str, Any]) -> str:
    return f"""# Macro Asset Data Vintage and Revision

Generated: {utc_now()}

Policy:

- Every historical ingestion run has a `retrieval_snapshot_id`.
- Latest normalized files are refreshed, but revision detection compares with previous latest snapshots.
- If a series_id + observation_date value changes, the old/new values are recorded in `revision_log.json`.
- FRED realtime fields are stored when available.
- Sources without vintage support are marked `vintage_support_limited`.
- As-of analysis must use retrieval snapshots and must not silently consume revised values as if they were available historically.

Current revision count: {revision_log['revision_count']}
"""


def render_quality_doc(quality: dict[str, Any]) -> str:
    return f"""# Macro Asset Quality Gate

Generated: {utc_now()}

Checks:

- required fields present
- value numeric
- date parseable
- duplicate series_id + observation_date
- frequency consistency
- extreme outlier detection
- missing value ratio
- unit present
- currency present for commodity price series
- source_id present
- raw checksum present
- publish_date status classified
- revision/vintage status classified

Quality counts:

```json
{json.dumps(quality['quality_counts'], ensure_ascii=False, indent=2)}
```

Official/authoritative sources with quality_passed are still only `trusted_by_real_external_candidate`; this phase does not enter formal trusted consumption.
"""


def http_get(url: str, timeout: int = 30, limit: int = 25_000_000) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FinancialResearch local historical ingestion"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"response exceeded limit {limit}")
    return data


def http_post(url: str, data: bytes, headers: dict[str, str], timeout: int = 30, limit: int = 25_000_000) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers | {"User-Agent": "FinancialResearch local historical ingestion"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise RuntimeError(f"response exceeded limit {limit}")
    return payload


def save_raw(root: Path, filename: str, raw: bytes) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / utc_now()[:10].replace("-", "") / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    return path, checksum


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8")
    return path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_fred_key() -> str:
    env_key = os.environ.get("FRED_API_KEY", "")
    if env_key:
        return env_key
    if not LOCAL_SECRETS_PATH.exists():
        return ""
    payload = read_json(LOCAL_SECRETS_PATH)
    return payload.get("FRED_API_KEY") or payload.get("fred_api_key") or ""


def to_float(value: Any) -> float | None:
    try:
        if value in {None, "", "."}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def is_date_like(value: Any) -> bool:
    if not value:
        return False
    return bool(str(value)[:10].count("-") == 2)


def month_label_to_date(value: str) -> str | None:
    text = value.strip()
    # World Bank rows often look like "1960M01".
    if len(text) >= 7 and text[4] == "M":
        return f"{text[:4]}-{text[5:7]}-01"
    try:
        parsed = datetime.fromisoformat(text[:10])
        return parsed.date().isoformat()
    except ValueError:
        return None


def detect_outlier_warning(values: list[float]) -> str:
    if len(values) < 12:
        return "insufficient_for_outlier_detection"
    sorted_values = sorted(values)
    median = sorted_values[len(sorted_values) // 2]
    if median == 0:
        return "ok"
    max_abs = max(abs(value) for value in values)
    return "extreme_outlier_blocking" if max_abs > abs(median) * 1_000_000 else "ok"


def source_counts(records: list[dict[str, Any]], field: str = "source_id") -> Counter:
    return Counter(record.get(field) or "missing" for record in records)


def init_metadata_db() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def hash_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    result = run_macro_asset_historical_ingestion()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
