# Local Project Inventory

Generated at: 2026-05-03

## 0. Workspace State

- Project path: `D:\workspace\FinancialResearch`
- Current branch: `refactor/parse-lab-api-integration`
- Inventory scope: read-only structure review plus this document.
- Parse Lab contract reviewed: `D:\workspace\parse_lab\docs\FINANCIAL_RESEARCH_PARSE_API_CONTRACT.md`

This inventory does not modify business logic, does not install dependencies, does not delete files, and does not push.

## 1. Current Project Directory Structure

Top-level structure:

```text
FinancialResearch/
  .git/
  .vscode/
  app/
  docs/
  .env.example
  .gitignore
  README.md
  requirements-forecast.txt
  requirements.txt
```

Application structure:

```text
app/
  __init__.py
  main.py
  agents/
    analysis_agent.py
    extractor_agent.py
    framework_agent.py
    parser_agent.py
    retrieval_agent.py
    update_agent.py
  config/
    agent_registry.json
    industry_metric_profiles.json
    llm_profiles.json
    settings.py
  models/
    modeltest.py
  pages/
    actuals.py
    analyze.py
    backtest_dashboard.py
    backtest_report.py
    company_profile.py
    decision_support.py
    extract.py
    forecast.py
    forecast_check.py
    forecast_dashboard.py
    formal_workbench.py
    ingest.py
    master_report.py
    metrics.py
    metrics_table.py
    parse.py
    qa.py
    repository.py
    revision_memory.py
    summary_report.py
    update.py
    upload.py
  services/
    actual_metric_service.py
    agent_router.py
    analysis_service.py
    backtest_dashboard_service.py
    backtest_report_service.py
    company_profile_service.py
    company_ui_service.py
    decision_support_service.py
    extractor_service.py
    forecast_service.py
    industry_profile_service.py
    ingest_service.py
    json_repair_service.py
    llm_gateway_service.py
    master_report_service.py
    metric_extraction_service.py
    metric_table_service.py
    parser_service.py
    period_service.py
    provider_service.py
    repository_service.py
    research_utils.py
    retrieval_service.py
    revision_memory_service.py
    sqlite_index_service.py
    summary_report_service.py
    task_runtime_service.py
    update_service.py
    vision_parser_service.py
  utils/
    file_utils.py
```

Docs:

```text
docs/
  ARCHITECTURE.md
  COLLABORATION.md
  RESEARCH_FRAMEWORK.md
  ROADMAP.md
  LOCAL_PROJECT_INVENTORY.md
```

## 2. Streamlit Files

Streamlit is present and appears to be the current UI/runtime entry.

Confirmed files:

- `app/main.py` imports `streamlit as st` and defines the navigation.
- Most files under `app/pages/` are Streamlit pages.

Examples:

- `app/pages/upload.py`
- `app/pages/parse.py`
- `app/pages/extract.py`
- `app/pages/analyze.py`
- `app/pages/forecast.py`
- `app/pages/backtest_dashboard.py`
- `app/pages/formal_workbench.py`

The current project is not separated into a dedicated web frontend plus backend API.

## 3. Backend / Frontend Status

There is no `backend/` directory and no `frontend/` directory in the current project tree.

Current structure is closer to:

```text
Streamlit pages -> app/services -> local data files
```

Service modules live under `app/services/`. UI modules live under `app/pages/`.

No FastAPI entrypoint was found. No `APIRouter` or backend API layer was found during inventory.

## 4. Existing Financial Report Analysis Modules

The project already has financial report workflow modules:

- Parse layer:
  - `app/services/parser_service.py`
  - `app/services/vision_parser_service.py`
  - `app/pages/parse.py`
- Ingestion pipeline:
  - `app/services/ingest_service.py`
  - `app/pages/ingest.py`
- Extraction layer:
  - `app/services/extractor_service.py`
  - `app/services/metric_extraction_service.py`
  - `app/pages/extract.py`
  - `app/pages/metrics.py`
  - `app/pages/metrics_table.py`
- Analysis/report layer:
  - `app/services/analysis_service.py`
  - `app/services/master_report_service.py`
  - `app/services/summary_report_service.py`
  - `app/pages/analyze.py`
  - `app/pages/master_report.py`
  - `app/pages/summary_report.py`
- Forecast/backtest layer:
  - `app/services/forecast_service.py`
  - `app/services/backtest_dashboard_service.py`
  - `app/services/backtest_report_service.py`
  - `app/pages/forecast.py`
  - `app/pages/forecast_check.py`
  - `app/pages/backtest_dashboard.py`
  - `app/pages/backtest_report.py`
- Repository/retrieval layer:
  - `app/services/repository_service.py`
  - `app/services/retrieval_service.py`
  - `app/services/sqlite_index_service.py`
  - `app/pages/repository.py`
  - `app/pages/qa.py`

## 5. Requirements / pyproject / package.json

Found:

- `requirements.txt`
- `requirements-forecast.txt`

Not found:

- `pyproject.toml`
- `package.json`

Important dependency observation:

`requirements.txt` currently includes PDF parsing dependencies such as:

- `pypdf`
- `pymupdf`
- `pdfplumber`

This confirms the existing project has local parser logic today. Future Parse Lab integration should not copy Parse Lab parser code and should not directly call Marker / MinerU / Surya / pdfplumber / PyMuPDF through the new integration path. It should call Parse Lab only over HTTP.

## 6. Files Suspected To Contain Core Financial Analysis Logic

Likely core financial analysis and research logic:

- `app/services/analysis_service.py`
  - Builds analysis context from parsed and extracted materials.
  - Generates structured financial research reports.
- `app/services/extractor_service.py`
  - Builds structured extracted output from parsed data.
- `app/services/metric_extraction_service.py`
  - Extracts standardized financial metrics.
- `app/services/actual_metric_service.py`
  - Builds actual metrics registry.
- `app/services/forecast_service.py`
  - Forecasting workflow.
- `app/services/update_service.py`
  - Updates master research state from latest materials and history.
- `app/services/master_report_service.py`
  - Master report rendering/output.
- `app/services/backtest_dashboard_service.py`
- `app/services/backtest_report_service.py`
- `app/services/revision_memory_service.py`
- `app/services/repository_service.py`
- `app/services/period_service.py`
  - Period/report type metadata logic appears important for primary report vs auxiliary material separation.

These should not be changed in the next Parse Lab API skeleton step except through a narrow, reviewed ingestion boundary.

## 7. Files Suspected To Be Old UI Or Old Entrypoints

Likely UI entrypoints:

- `app/main.py`
- `app/pages/*.py`

Potential old/test/debug pages:

- `app/pages/parse.py`
- `app/pages/extract.py`
- `app/pages/metrics.py`
- `app/pages/metrics_table.py`
- `app/pages/actuals.py`
- `app/pages/analyze.py`
- `app/pages/update.py`
- `app/pages/forecast.py`
- `app/pages/backtest_dashboard.py`
- `app/pages/backtest_report.py`
- `app/pages/repository.py`

README and architecture docs describe a split between "formal" pages and "test/debug" pages. The current `app/main.py` navigation reflects this Streamlit page split.

Potential old local parsing implementation:

- `app/services/parser_service.py`
- `app/services/vision_parser_service.py`
- `app/agents/parser_agent.py`

Do not remove or replace these during the integration skeleton phase. Treat them as existing behavior until a separate migration plan is approved.

## 8. Data / Output / Runtime Directories

No committed top-level `data/`, `runtime/`, or `outputs/` directory was present in the repository listing.

Runtime data is configured in `app/config/settings.py`:

- `FIN_RESEARCH_DATA_DIR` can override the data root.
- If QNAP settings are enabled, data root can be under a NAS mount.
- Otherwise default is `BASE_DIR / "data"`.
- `DATA_DIR.mkdir(...)` and `SYSTEM_DIR.mkdir(...)` are executed at import time.

Configured subfolders:

```python
SUBFOLDERS = {
    "raw": "年报",
    "parsed": "年报解析",
    "extracted": "年报提取",
    "analysis": "年报分析",
    "page_images": "年报页面图片",
    "qa_index": "问答索引",
}
```

The `.gitignore` excludes:

- `data/`
- `_system/`
- `logs/`
- `runtime_tasks/`
- `cache/`

This means local parse outputs and registries are expected to be generated artifacts rather than committed source.

## 9. Existing API Or Service Layer

No HTTP API layer was found.

Existing service layer is plain Python modules under `app/services/`.

Observed service patterns:

- `ingest_service.run_ingest_pipeline(...)` orchestrates parse -> extract -> metrics -> repository refresh.
- `parser_service.build_parsed_output(...)` performs local PDF parsing and writes `parsed_*.json`.
- `extractor_service.build_extracted_output(...)` consumes parsed JSON.
- `repository_service.refresh_company_repository(...)` builds repository/timeline/index views.

There is also `app/services/task_runtime_service.py`, which may be useful for future task-state handling, but it was not modified during this inventory.

## 10. Parse Lab API Integration Placement Recommendation

Recommended minimal placement, aligned with current project style:

```text
app/
  services/
    parse_lab_client.py
    parse_lab_ingestion_service.py
    parse_quality_gate.py
  models/
    parse_contract.py
```

Alternative if the project later introduces a real backend package:

```text
backend/app/
  clients/
    parse_lab_client.py
  modules/
    financial_report/
      parse_ingestion_service.py
      parse_quality_gate.py
      schemas/
        parse_contract.py
```

Given the current repository has no `backend/` directory, the first option is less disruptive.

Recommended integration boundary:

- `parse_lab_client.py`: HTTP-only wrapper for Parse Lab API v1.
- `parse_lab_ingestion_service.py`: submit, poll, and convert Parse Lab result to a local manifest.
- `parse_quality_gate.py`: evaluate `summary.json`, `quality_flags.json`, and `pages.jsonl` count into `parse_quality_level`.
- `parse_contract.py`: local dataclasses or Pydantic models for:
  - `ParseTaskRecord`
  - `ParseResultManifest`
  - `ParseQualityAssessment`
  - `ParsedDocumentRegistryEntry`

Do not connect this directly to:

- `run_ingest_pipeline(...)`
- automatic extraction
- metrics extraction
- forecast
- backtest
- report generation

## 11. Parse Lab Contract Implications

FinancialResearch should only call Parse Lab via HTTP:

- `POST /api/v1/parse/document`
- `GET /api/v1/parse/tasks/{task_id}`
- `GET /api/v1/parse/tasks/{task_id}/result`
- `POST /api/v1/parse/tasks/{task_id}/cancel`
- `DELETE /api/v1/parse/tasks/{task_id}`

FinancialResearch should persist only references and quality status at this stage:

- `task_id`
- `output_dir`
- `summary_path`
- `merged_md_path`
- `tables_json_path`
- `merged_tables_json_path`
- `quality_flags_path`
- `parse_quality_level`

FinancialResearch must not:

- import Parse Lab internal parser modules
- copy Parse Lab parser logic
- call Marker / MinerU / Surya directly
- call pdfplumber / PyMuPDF as part of the new Parse Lab integration path
- auto-feed partial or failed Parse Lab output into prediction/backtest/report workflows

## 12. Suggested Next Integration Path

Recommended next step:

1. Add an HTTP-only Parse Lab client under `app/services/parse_lab_client.py`.
2. Add local parse contract models under `app/models/parse_contract.py`.
3. Add a quality gate under `app/services/parse_quality_gate.py`.
4. Add a narrow ingestion helper under `app/services/parse_lab_ingestion_service.py`.
5. Store Parse Lab manifest records separately from existing `parsed_*.json` until reviewed.
6. Only after manifest/quality gate review, design a controlled adapter from Parse Lab output to the existing `parsed_*.json` shape.

This keeps Parse Lab integration reversible and prevents accidental changes to forecast, backtest, or report generation.
