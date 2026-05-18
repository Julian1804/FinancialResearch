from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.data_connector_phase2_service import (  # noqa: E402
    METADATA_DB_PATH,
    OUTPUT_ROOT,
    run_data_connector_phase2,
)


DOCS = {
    "report": PROJECT_ROOT / "docs" / "DATA_CONNECTOR_PHASE2_PROTOTYPE_REPORT.md",
    "framework": PROJECT_ROOT / "docs" / "CONNECTOR_FRAMEWORK_DESIGN.md",
    "quality": PROJECT_ROOT / "docs" / "EXTERNAL_DATA_QUALITY_AND_TRUST_GATE.md",
}


def main() -> int:
    result = run_data_connector_phase2()
    write_docs(result)
    summary = {
        "connector_phase2_completed": True,
        "success_count": result["connector_run_results"]["success_count"],
        "failed_count": result["connector_run_results"]["failed_count"],
        "skipped_count": result["connector_run_results"]["skipped_count"],
        "metadata_db_path": str(METADATA_DB_PATH),
        "outputs": {
            "connector_run_results": str(OUTPUT_ROOT / "connector_run_results.json"),
            "quality_check_results": str(OUTPUT_ROOT / "quality_check_results.json"),
            "trust_resolution_results": str(OUTPUT_ROOT / "trust_resolution_results.json"),
            "storage_estimate_refresh": str(OUTPUT_ROOT / "storage_estimate_refresh.json"),
            "metadata_db": str(METADATA_DB_PATH),
            "docs": {key: str(path) for key, path in DOCS.items()},
        },
        "no_openai_api_called": True,
        "trusted_consumption_affected": False,
        "parse_lab_affected": False,
        "default_v1_1_replaced": False,
    }
    (OUTPUT_ROOT / "phase2_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def write_docs(result: dict) -> None:
    for path in DOCS.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    DOCS["report"].write_text(render_report(result), encoding="utf-8")
    DOCS["framework"].write_text(render_framework_doc(), encoding="utf-8")
    DOCS["quality"].write_text(render_quality_doc(), encoding="utf-8")


def render_report(result: dict) -> str:
    runs = result["connector_run_results"]
    rows = "\n".join(
        f"| {item['connector_name']} | {item['source_id']} | {item['status']} | {item['record_count']} | {item['quality_check_status']} | {item['trust_status']} | {item.get('error_message','')} |"
        for item in runs["items"]
    )
    failed = [item for item in runs["items"] if item["status"] != "success"]
    failed_lines = "\n".join(f"- {item['connector_name']}: {item['error_message'] or item['quality_check_status']}" for item in failed) or "- none"
    trust_counts: dict[str, int] = {}
    for item in runs["items"]:
        trust_counts[item["trust_status"]] = trust_counts.get(item["trust_status"], 0) + 1
    return f"""# Data Connector Phase 2 Prototype Report

## Scope

Small-sample connector prototype only. No full download, no paid/point data source, no OpenAI API, no parse_lab change, and no trusted-consumption integration.

## Run Summary

- connector count: {runs['connector_count']}
- success: {runs['success_count']}
- failed: {runs['failed_count']}
- skipped: {runs['skipped_count']}
- metadata DB: `{METADATA_DB_PATH}`

| Connector | Source | Status | Records | Quality | Trust status | Error |
|---|---|---:|---:|---|---|---|
{rows}

## Failed / Skipped

{failed_lines}

## Trust Distribution

```json
{json.dumps(trust_counts, ensure_ascii=False, indent=2)}
```

## Outputs

- Connector run results: `{OUTPUT_ROOT / 'connector_run_results.json'}`
- Quality check results: `{OUTPUT_ROOT / 'quality_check_results.json'}`
- Trust resolution results: `{OUTPUT_ROOT / 'trust_resolution_results.json'}`
- Storage estimate refresh: `{OUTPUT_ROOT / 'storage_estimate_refresh.json'}`
"""


def render_framework_doc() -> str:
    return """# Connector Framework Design

## Pipeline

All Phase 2 connectors follow:

raw data preservation -> source classification -> parsing/extraction -> normalization -> quality checks -> trust resolution -> consumption eligibility.

## Config Sources

- `config/storage_paths.json`
- `runtime/data_connector_feasibility/source_registry.json`

## Result Schema

Each connector result includes:

- `source_id`
- `source_name`
- `connector_name`
- `provider_type`
- `official_source`
- `trusted_external_eligible`
- `retrieved_at`
- `source_url_or_reference`
- `raw_output_path`
- `normalized_output_path`
- `quality_check_status`
- `trust_status`
- `candidate_only`
- `error_message`

## Metadata Index

SQLite prototype tables:

- `source_registry_index`
- `connector_run_log`
- `normalized_dataset_index`
- `quality_check_log`
"""


def render_quality_doc() -> str:
    return """# External Data Quality and Trust Gate

## Quality Checks

Common:

- numeric_format_ok
- date_format_ok
- missing_value_check
- duplicate_check
- source_id_present
- retrieved_at_present
- checksum_present
- field_mapping_ok

Time series:

- date_order_ok
- duplicate_date_check
- frequency_consistency_check
- suspicious_gap_check

Financial:

- price_non_negative
- volume_non_negative
- rate_reasonable_range
- currency_present_if_required
- unit_present_if_required

## Trust Rules

- Official / regulator / exchange / official public APIs with quality passed: `trusted_by_real_external_candidate`.
- AKShare / Baostock: `candidate_external_data` unless a specific dataset has documented official upstream provenance.
- Non-official crawler/web data: candidate only.
- Trusted source with failed quality: `trusted_source_but_quality_failed`.

Phase 2 does not make data consumption-grade. All outputs remain outside the formal trusted consumption layer.
"""


if __name__ == "__main__":
    raise SystemExit(main())
