from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BASE_ROOT = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion"
BLS_ROOT = BASE_ROOT / "bls_resilient_ingestion"
DOC_REPORT = PROJECT_ROOT / "docs" / "BLS_RESILIENT_INGESTION_REPORT.md"

BLS_SERIES = [
    {"series_id": "CUUR0000SA0", "metric_name": "us_cpi_all_urban_consumers", "start_year": 1913},
    {"series_id": "WPUFD4", "metric_name": "us_ppi_final_demand", "start_year": 2009},
    {"series_id": "LNS14000000", "metric_name": "us_unemployment_rate", "start_year": 1948},
    {"series_id": "CES0000000001", "metric_name": "us_nonfarm_payrolls", "start_year": 1939},
]

FLAT_FILE_CANDIDATES = [
    {
        "name": "CPI All Items flat file",
        "series_id": "CUUR0000SA0",
        "url": "https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems",
        "expected_status": "official_flat_file",
    },
    {
        "name": "Unemployment all data flat file",
        "series_id": "LNS14000000",
        "url": "https://download.bls.gov/pub/time.series/ln/ln.data.1.AllData",
        "expected_status": "official_flat_file",
    },
    {
        "name": "PPI current flat file",
        "series_id": "WPUFD4",
        "url": "https://download.bls.gov/pub/time.series/wp/wp.data.0.Current",
        "expected_status": "official_flat_file",
    },
    {
        "name": "CES total nonfarm narrow flat file",
        "series_id": "CES0000000001",
        "url": "https://download.bls.gov/pub/time.series/ce/ce.data.00a.TotalNonfarm.Employment",
        "expected_status": "official_flat_file",
    },
]


def run_bls_resilient_ingestion() -> dict[str, Any]:
    BLS_ROOT.mkdir(parents=True, exist_ok=True)
    prior_runs = read_json(BASE_ROOT / "historical_ingestion_run_results.json").get("items", [])
    diagnosis = diagnose_prior_failures(prior_runs)
    retry_plan = build_retry_plan(diagnosis)
    api_retry = try_single_series_small_window()
    fallback_audit = audit_flat_file_sources()
    deferred_queue = build_deferred_queue(diagnosis, retry_plan, api_retry, fallback_audit)
    result = {
        "generated_at": utc_now(),
        "bls_resilient_ingestion_completed": True,
        "api_retry_status": api_retry["status"],
        "final_status": determine_final_status(api_retry, fallback_audit),
        "failure_classifications": sorted({item["failure_classification"] for item in diagnosis["items"]}),
        "diagnosis_path": str(BLS_ROOT / "bls_failure_diagnosis.json"),
        "retry_plan_path": str(BLS_ROOT / "bls_retry_plan.json"),
        "deferred_retry_queue_path": str(BLS_ROOT / "bls_deferred_retry_queue.json"),
        "fallback_source_audit_path": str(BLS_ROOT / "bls_fallback_source_audit.json"),
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "no_openai_api_called": True,
    }
    write_json(BLS_ROOT / "bls_failure_diagnosis.json", diagnosis)
    write_json(BLS_ROOT / "bls_retry_plan.json", retry_plan | {"api_retry": api_retry})
    write_json(BLS_ROOT / "bls_deferred_retry_queue.json", deferred_queue)
    write_json(BLS_ROOT / "bls_fallback_source_audit.json", fallback_audit)
    write_json(BLS_ROOT / "bls_resilient_ingestion_results.json", result)
    DOC_REPORT.write_text(render_doc(result, diagnosis, fallback_audit), encoding="utf-8")
    return result


def diagnose_prior_failures(prior_runs: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for run in prior_runs:
        if run.get("source_id") != "bls_public_api":
            continue
        series_id = str(run.get("connector_name", "")).replace("bls_", "").replace("_full_history", "")
        raw_paths = sorted((Path("Z:/data_lake_master/raw/macro/bls_public_api")).glob(f"**/bls_{series_id}_*.json"))
        messages = []
        endpoint = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        payload_preview = {}
        for raw_path in raw_paths[-2:]:
            try:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                messages.extend(raw.get("message", []))
                payload_preview = {"raw_path": str(raw_path), "status": raw.get("status")}
            except Exception as exc:  # noqa: BLE001
                messages.append(f"raw_parse_error: {exc}")
        message = "; ".join(messages) or run.get("error_message") or "No records returned."
        items.append(
            {
                "error_code": "REQUEST_NOT_PROCESSED" if "REQUEST_NOT_PROCESSED" in message or "threshold" in message.lower() else "NO_RECORDS",
                "error_message": message,
                "endpoint": endpoint,
                "series_id": series_id,
                "time_window": "historical chunked by 10 years",
                "request_payload": payload_preview,
                "retry_count": 0,
                "failure_classification": classify_failure(message),
                "candidate_only": True,
            }
        )
    return {"generated_at": utc_now(), "items": items}


def classify_failure(message: str) -> str:
    lowered = message.lower()
    if "daily threshold" in lowered or "threshold" in lowered:
        return "daily_threshold_reached"
    if "too large" in lowered or "year" in lowered and "limit" in lowered:
        return "request_window_too_large"
    if "not found" in lowered or "invalid series" in lowered:
        return "series_unavailable"
    if "request_not_processed" in lowered:
        return "endpoint_unavailable"
    if "malformed" in lowered or "json" in lowered:
        return "malformed_request"
    if "timeout" in lowered or "remote" in lowered or "connection" in lowered:
        return "temporary_network_error"
    return "unknown"


def build_retry_plan(diagnosis: dict[str, Any]) -> dict[str, Any]:
    current_year = date.today().year
    retry_items = []
    for series in BLS_SERIES:
        retry_items.append(
            {
                "series_id": series["series_id"],
                "metric_name": series["metric_name"],
                "strategy": "single_series_small_window",
                "start_year": current_year - 1,
                "end_year": current_year,
                "max_retries": 1,
                "cooldown_seconds": 2,
                "requires_api_key": "recommended_if_daily_threshold_persists",
                "candidate_only": True,
            }
        )
    return {
        "generated_at": utc_now(),
        "reason": "Prior public API run reached daily threshold; retry only tiny windows and defer the rest.",
        "retry_items": retry_items,
        "do_not_high_frequency_retry": True,
        "user_action_required_if_persistent": "Add a BLS API key to config/local_secrets.json as BLS_API_KEY; do not commit it.",
    }


def try_single_series_small_window() -> dict[str, Any]:
    series = BLS_SERIES[0]
    current_year = date.today().year
    payload = {
        "seriesid": [series["series_id"]],
        "startyear": str(current_year - 1),
        "endyear": str(current_year),
    }
    endpoint = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    try:
        raw = http_post(endpoint, json.dumps(payload).encode("utf-8"), timeout=20)
        raw_path = BLS_ROOT / "api_retry_small_window_raw.json"
        raw_path.write_bytes(raw)
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
        message = "; ".join(parsed.get("message", []))
        status = "success" if parsed.get("status") == "REQUEST_SUCCEEDED" and parsed.get("Results", {}).get("series") else "deferred_retry"
        return {
            "status": status,
            "endpoint": endpoint,
            "series_id": series["series_id"],
            "request_payload": payload,
            "response_status": parsed.get("status"),
            "message": message,
            "failure_classification": classify_failure(message),
            "raw_path": str(raw_path),
            "record_count": sum(len(item.get("data", [])) for item in parsed.get("Results", {}).get("series", [])),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "deferred_retry",
            "endpoint": endpoint,
            "series_id": series["series_id"],
            "request_payload": payload,
            "error_message": f"{type(exc).__name__}: {str(exc)[:300]}",
            "failure_classification": classify_failure(str(exc)),
        }


def audit_flat_file_sources() -> dict[str, Any]:
    results = []
    for candidate in FLAT_FILE_CANDIDATES:
        item = candidate.copy()
        try:
            raw = http_get(candidate["url"], timeout=12, limit=2048)
            item.update(
                {
                    "status": "fallback_available",
                    "sample_bytes": len(raw),
                    "sample_preview": raw.decode("utf-8", errors="replace")[:160],
                    "failure_classification": "",
                }
            )
        except urllib.error.HTTPError as exc:
            item.update(
                {
                    "status": "fallback_deferred",
                    "http_status": exc.code,
                    "error_message": str(exc),
                    "failure_classification": "endpoint_unavailable" if exc.code in {403, 404} else "temporary_network_error",
                }
            )
        except Exception as exc:  # noqa: BLE001
            item.update(
                {
                    "status": "fallback_deferred",
                    "error_message": f"{type(exc).__name__}: {str(exc)[:240]}",
                    "failure_classification": classify_failure(str(exc)),
                }
            )
        results.append(item)
        time.sleep(0.5)
    return {
        "generated_at": utc_now(),
        "official_flat_file_root": "https://download.bls.gov/pub/time.series/",
        "audit_note": "BLS publishes official time.series flat files; local network may receive 403 and should retry later or with BLS-supported access.",
        "items": results,
    }


def build_deferred_queue(diagnosis: dict[str, Any], retry_plan: dict[str, Any], api_retry: dict[str, Any], fallback_audit: dict[str, Any]) -> dict[str, Any]:
    queue = []
    for retry in retry_plan["retry_items"]:
        queue.append(
            {
                "series_id": retry["series_id"],
                "priority": "must_retry_later",
                "reason": "daily_threshold_or_endpoint_deferred",
                "next_action": "retry single-series small window after cooldown/day reset; use BLS_API_KEY if available",
                "api_retry_status": api_retry["status"] if retry["series_id"] == api_retry.get("series_id") else "not_attempted_this_round",
                "candidate_only": True,
            }
        )
    return {
        "generated_at": utc_now(),
        "queue_count": len(queue),
        "items": queue,
        "fallback_available_count": sum(1 for item in fallback_audit["items"] if item["status"] == "fallback_available"),
        "formal_trusted_consumption": False,
    }


def determine_final_status(api_retry: dict[str, Any], fallback_audit: dict[str, Any]) -> str:
    if api_retry["status"] == "success":
        return "small_window_api_recovered"
    if any(item["status"] == "fallback_available" for item in fallback_audit["items"]):
        return "deferred_retry_with_flat_file_fallback_available"
    return "deferred_retry_needs_api_key_or_later_retry"


def render_doc(result: dict[str, Any], diagnosis: dict[str, Any], fallback_audit: dict[str, Any]) -> str:
    return f"""# BLS Resilient Ingestion Report

Generated: {utc_now()}

Final status: `{result['final_status']}`.

The previous BLS API run returned `REQUEST_NOT_PROCESSED` / daily threshold style failures.
This phase did not stop at that message. It produced:

- failure diagnosis by series
- tiny single-series retry
- deferred retry queue
- official flat-file fallback audit

Fallback audit root: `https://download.bls.gov/pub/time.series/`

Fallback availability count: {sum(1 for item in fallback_audit['items'] if item['status'] == 'fallback_available')}

If threshold persists, add `BLS_API_KEY` to `config/local_secrets.json` and rerun with low-frequency chunking.

No OpenAI API was called. No formal trusted consumption was modified.
"""


def http_post(url: str, data: bytes, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "FinancialResearch BLS resilient ingestion"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(2_000_000)


def http_get(url: str, timeout: int = 12, limit: int = 2048) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FinancialResearch BLS resilient ingestion"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(limit)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_bls_resilient_ingestion(), ensure_ascii=False, indent=2))
