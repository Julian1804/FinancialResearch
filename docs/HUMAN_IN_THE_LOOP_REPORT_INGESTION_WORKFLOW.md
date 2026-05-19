# Human-in-the-loop Report Ingestion Workflow

## Scope

This workflow stores reports copied manually from GPT Web. It does not call the OpenAI API and does not promote GPT text into trusted facts.

## CLI

```powershell
python scripts/run_report_ingestion_v1.py sample-run
python scripts/run_report_ingestion_v1.py ingest --report-path <path>
python scripts/run_report_ingestion_v1.py list-reports
```

## Stored Outputs

- Local reports: `runtime/analysis_reports`
- NAS backup: `Z:\data_lake_master\exports\analysis_reports`
- Backtest queue: `runtime/backtest_queue\pending_backtest_queue.json`
- Version history: `runtime/report_ingestion_v1\report_version_history.json`

## Guardrail

GPT-generated content is stored as `analysis_report / forecast / interpretation` only. It is not formal trusted consumption.
