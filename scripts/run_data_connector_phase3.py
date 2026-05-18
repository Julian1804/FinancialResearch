from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.data_connector_phase3_service import (  # noqa: E402
    METADATA_DB_PATH,
    OUTPUT_ROOT,
    run_data_connector_phase3,
)


DOCS = {
    "report": PROJECT_ROOT / "docs" / "DATA_CONNECTOR_PHASE3_CURATED_PIPELINE_REPORT.md",
    "registry": PROJECT_ROOT / "docs" / "CURATED_SOURCE_REGISTRY_AND_WATCHLIST_DESIGN.md",
    "staging": PROJECT_ROOT / "docs" / "CONSUMPTION_GRADE_STAGING_RULES.md",
}


def main() -> int:
    result = run_data_connector_phase3()
    write_docs(result)
    pipeline = result["incremental_pipeline_run_results"]
    staging = result["consumption_grade_staging"]
    summary = {
        "phase3_completed": True,
        "pipeline_status_counts": pipeline["status_counts"],
        "pipeline_quality_counts": pipeline["quality_status_counts"],
        "consumption_grade_candidate_count": staging["consumption_grade_candidate_count"],
        "review_candidate_count": staging["review_candidate_count"],
        "defer_count": staging["defer_count"],
        "metadata_db_path": str(METADATA_DB_PATH),
        "outputs": {
            "curated_source_registry": str(OUTPUT_ROOT / "curated_source_registry.json"),
            "quality_remediation_results": str(OUTPUT_ROOT / "quality_remediation_results.json"),
            "incremental_pipeline_run_results": str(OUTPUT_ROOT / "incremental_pipeline_run_results.json"),
            "consumption_grade_staging": str(OUTPUT_ROOT / "consumption_grade_staging.json"),
            "storage_estimate_refresh": str(OUTPUT_ROOT / "storage_estimate_refresh.json"),
            "docs": {key: str(path) for key, path in DOCS.items()},
        },
        "no_openai_api_called": True,
        "trusted_consumption_affected": False,
        "parse_lab_affected": False,
        "default_v1_1_replaced": False,
    }
    (OUTPUT_ROOT / "phase3_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def write_docs(result: dict) -> None:
    for path in DOCS.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    DOCS["report"].write_text(render_report(result), encoding="utf-8")
    DOCS["registry"].write_text(render_registry_doc(result), encoding="utf-8")
    DOCS["staging"].write_text(render_staging_doc(), encoding="utf-8")


def render_report(result: dict) -> str:
    remediation = result["quality_remediation_results"]
    pipeline = result["incremental_pipeline_run_results"]
    staging = result["consumption_grade_staging"]
    remediation_rows = "\n".join(
        f"| {item['source_id']} | {item['before_status']} | {item['after_status']} | {item['remediation_action']} | {item['issue_owner']} | {item['remediation_reason']} |"
        for item in remediation["items"]
    )
    pipeline_rows = "\n".join(
        f"| {item['connector_name']} | {item['source_id']} | {item['status']} | {item['record_count']} | {item['quality_check_status']} | {item['trust_status']} | {item.get('error_message','')} |"
        for item in pipeline["items"]
    )
    return f"""# Data Connector Phase 3 Curated Pipeline Report

## Scope

Phase 3 adds quality remediation, a curated source registry, a watchlist-driven incremental connector prototype, and consumption-grade staging. It does not perform full downloads and does not connect staged data to the formal trusted consumption layer.

## Quality Remediation

| Source | Before | After | Action | Owner | Reason |
|---|---|---|---|---|---|
{remediation_rows}

Before status counts:

```json
{json.dumps(remediation['before_quality_status_counts'], ensure_ascii=False, indent=2)}
```

After status counts:

```json
{json.dumps(remediation['after_quality_status_counts'], ensure_ascii=False, indent=2)}
```

## Incremental Pipeline

| Connector | Source | Status | Records | Quality | Trust | Error |
|---|---|---:|---:|---|---|---|
{pipeline_rows}

Status counts:

```json
{json.dumps(pipeline['status_counts'], ensure_ascii=False, indent=2)}
```

Quality counts:

```json
{json.dumps(pipeline['quality_status_counts'], ensure_ascii=False, indent=2)}
```

## Consumption-grade Staging

- consumption-grade candidates: {staging['consumption_grade_candidate_count']}
- review candidates: {staging['review_candidate_count']}
- deferred: {staging['defer_count']}

Only official/authoritative sources with `quality_passed` can enter `consumption_grade_candidate`. `quality_warning` and `quality_failed` are excluded.

## Outputs

- Curated source registry: `{OUTPUT_ROOT / 'curated_source_registry.json'}`
- Quality remediation: `{OUTPUT_ROOT / 'quality_remediation_results.json'}`
- Incremental pipeline: `{OUTPUT_ROOT / 'incremental_pipeline_run_results.json'}`
- Consumption-grade staging: `{OUTPUT_ROOT / 'consumption_grade_staging.json'}`
- Storage estimate refresh: `{OUTPUT_ROOT / 'storage_estimate_refresh.json'}`
"""


def render_registry_doc(result: dict) -> str:
    registry = result["curated_source_registry"]
    rows = "\n".join(
        f"| {item['source_id']} | {item['trust_eligibility']} | {item['quality_status']} | {item['incremental_supported']} | {item['current_phase_status']} | {item['next_action']} |"
        for item in registry["entries"]
    )
    return f"""# Curated Source Registry and Watchlist Design

## Config Files

- Watchlist: `config/watchlist.json`
- Metrics registry: `config/metrics_registry.json`

The watchlist is deliberately small and sample-oriented. It is not a production investment universe.

## Curated Source Registry

| Source | Trust eligibility | Quality | Incremental | Phase status | Next action |
|---|---|---|---:|---|---|
{rows}

## Design Notes

- SEC, BLS, Treasury, and World Bank are official/authoritative and can become `trusted_by_real_external_candidate` only after quality passes.
- CNINFO is treated as official disclosure metadata candidate when original URL, retrieval time, and checksum are preserved.
- Baostock remains candidate external data until dataset-level upstream provenance is documented.
- AKShare is deferred for Phase 3 when upstream is unavailable or dataset-level provenance is not explicit.
- FRED remains retry/defer if public CSV access times out.
"""


def render_staging_doc() -> str:
    return """# Consumption-grade Staging Rules

## Staging Is Not Formal Trusted Consumption

Phase 3 staging is a pre-consumption holding layer. It does not modify the formal FinancialResearch trusted consumption path.

## Rules

- `consumption_grade_candidate`: official/authoritative source plus `quality_passed`.
- `review_candidate`: quality passed but source provenance is not yet sufficient, or quality warning that must not enter consumption-grade.
- `defer`: connector failed or quality failed.

## Explicit Exclusions

- `quality_warning` does not enter consumption-grade.
- `quality_failed` does not enter consumption-grade.
- Baostock and AKShare do not become consumption-grade without dataset-level provenance.
- Media reposts, forums, public-account reposts, and second-hand commentary are not trusted external sources.
"""


if __name__ == "__main__":
    raise SystemExit(main())
