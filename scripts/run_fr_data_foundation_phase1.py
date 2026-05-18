from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.data_connector_feasibility_service import (  # noqa: E402
    REGISTRY_OUTPUT_DIR,
    build_data_foundation_phase1_outputs,
)
from backend.app.modules.financial_report.services.human_in_loop_analysis_service import (  # noqa: E402
    OUTPUT_DIR as ANALYSIS_OUTPUT_DIR,
    build_sample_analysis_packet_and_ingestion,
)


DOCS_DIR = PROJECT_ROOT / "docs"
SUMMARY_PATH = ANALYSIS_OUTPUT_DIR / "fr_data_foundation_phase1_summary.json"


def main() -> int:
    analysis = build_sample_analysis_packet_and_ingestion()
    data_foundation = build_data_foundation_phase1_outputs()
    docs = write_docs(analysis, data_foundation)
    summary = {
        "phase": "FR Data Foundation Phase 1 + Human-in-the-loop Analysis Skeleton",
        "human_in_loop_skeleton_completed": True,
        "analysis_packet_completed": True,
        "gpt_web_prompt_completed": True,
        "report_ingestion_completed": True,
        "data_connector_feasibility_audit_completed": True,
        "no_openai_api_called": True,
        "no_full_download": True,
        "trusted_consumption_affected": False,
        "parse_lab_affected": False,
        "default_v1_1_replaced": False,
        "sample_packet_id": analysis["summary"]["packet_id"],
        "sample_report_id": analysis["summary"]["report_id"],
        "source_count": data_foundation["summary"]["source_count"],
        "smoke_success_count": data_foundation["summary"]["smoke_success_count"],
        "smoke_failed_count": data_foundation["summary"]["smoke_failed_count"],
        "smoke_skipped_count": data_foundation["summary"]["smoke_skipped_count"],
        "outputs": {
            "analysis_sample_dir": str(ANALYSIS_OUTPUT_DIR / "sample"),
            "source_registry": str(REGISTRY_OUTPUT_DIR / "source_registry.json"),
            "connector_smoke_results": str(REGISTRY_OUTPUT_DIR / "connector_smoke_results.json"),
            "storage_estimate": str(REGISTRY_OUTPUT_DIR / "storage_estimate.json"),
            "docs": docs,
        },
    }
    write_json(SUMMARY_PATH, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def write_docs(analysis: dict, data_foundation: dict) -> dict[str, str]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "workflow": DOCS_DIR / "HUMAN_IN_THE_LOOP_GPT_ANALYSIS_WORKFLOW.md",
        "packet_schema": DOCS_DIR / "ANALYSIS_PACKET_SCHEMA.md",
        "report_ingestion_schema": DOCS_DIR / "GPT_REPORT_INGESTION_SCHEMA.md",
        "connector_audit": DOCS_DIR / "DATA_CONNECTOR_FEASIBILITY_AUDIT.md",
        "storage_architecture": DOCS_DIR / "DATA_STORAGE_ARCHITECTURE.md",
        "source_registry_schema": DOCS_DIR / "DATA_SOURCE_REGISTRY_SCHEMA.md",
    }
    paths["workflow"].write_text(_workflow_doc(analysis), encoding="utf-8")
    paths["packet_schema"].write_text(_packet_schema_doc(), encoding="utf-8")
    paths["report_ingestion_schema"].write_text(_report_ingestion_schema_doc(), encoding="utf-8")
    paths["connector_audit"].write_text(_connector_audit_doc(data_foundation), encoding="utf-8")
    paths["storage_architecture"].write_text(_storage_architecture_doc(data_foundation), encoding="utf-8")
    paths["source_registry_schema"].write_text(_source_registry_schema_doc(data_foundation), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def _workflow_doc(analysis: dict) -> str:
    summary = analysis["summary"]
    return f"""# Human-in-the-loop GPT Analysis Workflow

## Phase 1 Objective

FinancialResearch does not run a background ChatGPT/OpenAI analysis agent. The local system builds a structured analysis packet, the user copies it to ChatGPT Web, discusses and revises manually, then pastes the final report back into FR for structured storage and future backtest.

## Workflow

1. Build a data snapshot from consumption-grade trusted facts only.
2. Add candidate facts as clearly labeled context, never as final facts.
3. Generate a markdown analysis packet and a copy-to-GPT prompt.
4. User pastes the packet into ChatGPT Web.
5. GPT Web returns a markdown report plus a `FINAL_REPORT_JSON` block.
6. User pastes the final report back into FR.
7. FR stores raw report text, parsed JSON, assumptions, forecasts, risks, watchlist signals, confidence, and backtest fields.

## Guardrails

- Do not call OpenAI API from FR backend.
- Use only information available on or before `as_of_date`.
- Candidate facts cannot become trusted facts inside the report.
- If evidence is missing, the report must output `insufficient_evidence`.
- Forecasts are stored as reviewable hypotheses, not as decisions.

## Sample Outputs

- sample packet id: `{summary['packet_id']}`
- sample ingested report id: `{summary['report_id']}`
- sample directory: `{summary['output_dir']}`
"""


def _packet_schema_doc() -> str:
    return """# Analysis Packet Schema

## Required Fields

- `packet_id`
- `data_snapshot_id`
- `company`
- `ticker`
- `as_of_date`
- `analysis_scope`
- `selected_financial_reports`
- `trusted_facts`
- `candidate_facts_summary`
- `price_data_placeholder`
- `macro_data_placeholder`
- `asset_class_data_placeholder`
- `sentiment_management_commentary_placeholder`
- `previous_reports_forecasts`
- `insufficient_trusted_evidence`

## Trusted Fact Requirements

Each trusted fact must include source provenance:

- `fact_id`
- `canonical_field` or `field_name`
- `value`
- `unit`
- `currency`
- `period`
- `source_id`
- `source_url`
- `retrieved_at`
- `trust_status`
- `quality_status`
- `provenance`

Only facts that have passed trust resolution and data quality checks can enter `trusted_facts`.
"""


def _report_ingestion_schema_doc() -> str:
    return """# GPT Report Ingestion Schema

## Raw Input

The user pastes the complete GPT Web report into FR. FR preserves:

- `raw_report_text`
- `packet_id`
- `data_snapshot_id`
- `created_at`
- `report_version`

## FINAL_REPORT_JSON

The pasted report must include a fenced JSON block after `FINAL_REPORT_JSON` with:

- `report_title`
- `as_of_date`
- `summary`
- `assumptions`
- `forecasts`
- `risks`
- `watchlist_signals`
- `confidence`
- `next_review_date`
- `insufficient_evidence`

## Forecast / Backtest Fields

Each forecast item stores:

- `forecast_item`
- `target_metric`
- `forecast_horizon`
- `expected_direction`
- `expected_range`
- `confidence`
- `thesis`
- `risk_trigger`
- `review_date`
- `actual_value_later`
- `backtest_result`
- `revision_note`
"""


def _connector_audit_doc(data_foundation: dict) -> str:
    registry = data_foundation["registry"]
    smoke = data_foundation["smoke"]
    official_ready = [
        item["source_id"]
        for item in registry["entries"]
        if item["trusted_external_eligible"] and item["terms_risk"] == "low"
    ]
    deferred = [
        item["source_id"]
        for item in registry["entries"]
        if item["requires_points_or_paid_quota"] or item["status"].startswith("defer")
    ]
    return f"""# Data Connector Feasibility Audit

## Scope

This audit covers Phase 1 feasibility only. It does not start full crawlers and does not use paid, point-based, or recharge-based sources as the mainline.

## Official / Authoritative Source Rule

Trusted external facts must come from official institutions, exchanges, regulators, official authorized APIs, or open-source wrappers whose upstream source is traceable to official data. Media reposts, forums, public accounts, and second-hand commentary are not trusted external sources.

## Ready or Priority Sources

Recommended first connectors:

- `sec_edgar_companyfacts`
- `fred_public_csv`
- `treasury_fiscaldata`
- `world_bank_pink_sheet`
- `bls_public_api`
- `akshare_traceable_official` only for official-upstream datasets
- `cninfo_disclosure` for report discovery/download after rate/terms checks

Low-risk trusted eligible examples: {', '.join(official_ready)}

## Deferred or Not Phase 1 Mainline

Deferred sources: {', '.join(deferred)}

- Wind is trusted eligible under license but not Phase 1 mainline.
- EIA is official, but key policy should be checked before implementation.
- Baostock and broad AKShare endpoints remain candidate until upstream provenance is recorded per dataset.

## Smoke Summary

- test count: {smoke['test_count']}
- success: {smoke['success_count']}
- failed: {smoke['failed_count']}
- skipped: {smoke['skipped_count']}

Raw smoke results: `{REGISTRY_OUTPUT_DIR / 'connector_smoke_results.json'}`
Source registry: `{REGISTRY_OUTPUT_DIR / 'source_registry.json'}`

## Data Quality Gate

Authoritative source status is not enough. Every record must pass checks for numeric format, dates, nulls, duplicates, unit/currency, period, field mapping, continuity, range, source URL, retrieval timestamp, and checksum. A trusted source with failed quality checks becomes `trusted_source_but_quality_failed` or `needs_review`, not consumption-grade.

## Official References Used

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- BLS Public Data API: https://www.bls.gov/developers/
- U.S. Treasury FiscalData API: https://fiscaldata.treasury.gov/api-documentation/
- World Bank Commodity Markets / Pink Sheet: https://www.worldbank.org/en/research/commodity-markets
- FRED public data portal: https://fred.stlouisfed.org/
- CNINFO disclosure portal: http://www.cninfo.com.cn/new/index
- Shanghai Stock Exchange disclosure portal: https://www.sse.com.cn/disclosure/listedinfo/announcement/
- Shenzhen Stock Exchange disclosure portal: https://www.szse.cn/disclosure/listed/notice/
"""


def _storage_architecture_doc(data_foundation: dict) -> str:
    storage = data_foundation["storage"]
    return f"""# Data Storage Architecture

## Layers

1. Raw layer: PDF originals, raw API responses, raw CSV/XLSX, source URL, retrieved_at, checksum.
2. Classification layer: source type, provider type, official source, data category, frequency.
3. Normalized layer: date, symbol, metric_name, value, unit, currency, source_id, as_of_date, data_frequency.
4. Quality layer: numeric/date/null/duplicate/unit/range/continuity/field mapping checks.
5. Trust layer: trusted_by_official_source, trusted_by_real_external, candidate_only, needs_review, trusted_source_but_quality_failed.
6. Consumption layer: dashboard_eligible, gpt_packet_eligible, backtest_eligible.

## Storage Recommendation

- DuckDB + Parquet: primary analytics and time-series store.
- SQLite: small metadata registry, ingestion status, report index.
- JSONL: append-only audit/event logs.
- NAS cold storage: PDFs, raw API response snapshots, parser raw output archives.

## Capacity Estimate

```json
{json.dumps(storage['estimates'], ensure_ascii=False, indent=2)}
```

2TB desktop hot storage is enough for curated equities, macro, commodity, active report sets, and active parser outputs. 8TB NAS cold storage is enough for broader PDF/archive retention if deduplicated and compressed.
"""


def _source_registry_schema_doc(data_foundation: dict) -> str:
    return f"""# Data Source Registry Schema

## Fields

- `source_id`
- `source_name`
- `category`
- `official_source`
- `provider_type`
- `free_level`
- `requires_account`
- `requires_api_key`
- `requires_points_or_paid_quota`
- `terms_risk`
- `update_frequency`
- `data_frequency`
- `coverage`
- `status`
- `connector_module`
- `raw_storage_policy`
- `normalized_schema`
- `trusted_external_eligible`
- `data_quality_checks`
- `consumption_eligibility`
- `source_url`
- `notes`

## Current Registry

Source count: {data_foundation['registry']['source_count']}

Machine-readable registry: `{REGISTRY_OUTPUT_DIR / 'source_registry.json'}`
"""


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
