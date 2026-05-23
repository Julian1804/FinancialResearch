# Architecture Overview

## System Shape

FinancialResearch is organized around evidence flow:

```text
source data
-> raw preservation where needed
-> normalized structured data
-> QA and provenance
-> candidate / data product staging
-> dashboard / statistical report / analysis packet
-> human-in-the-loop GPT Web analysis
-> report ingestion
-> forecast / backtest / revision
```

## Main Components

- `backend/`: FastAPI backend and domain modules.
- `frontend_web/src/dashboard_v1/`: Dashboard v1 static frontend served by local action server.
- `scripts/`: operational scripts, smoke tests, policy builders, data product refresh hooks.
- `config/`: source policies, taxonomy, schedules, data product registry, storage paths.
- `docs/`: project and module methodology.
- `runtime/`: generated outputs, snapshots, reports, data product manifests, test artifacts. Runtime is local and ignored by Git.

## Dashboard

The Dashboard is not Streamlit. It is served through:

```powershell
cd D:\workspace\FinancialResearch
D:\workspace\envs\financial_research_backend\Scripts\python.exe scripts\run_dashboard_v1_action_server.py --host 127.0.0.1 --port 5188
```

The Dashboard exposes research workspace, data source status, Morningstar token flow, data product panels, report generation, and upload classification.

## Data Product Layer

Data products are explicit, versioned, and manifest-driven. Current examples include:

- A-share/ETF OHLC trusted candidate preview.
- Morningstar returns/holdings/exposure candidate preview.

Data products may be preview-only. Preview products do not imply formal trusted consumption.

## Trusted Consumption Boundary

Formal trusted consumption remains off by default. Current trusted-candidate work is field-level or product-level preview/staging unless explicitly promoted through a later dedicated phase.

## Parse Lab Boundary

Parse Lab is separate. FinancialResearch calls Parse Lab by HTTP only. Parser dependencies are not installed into the FinancialResearch backend environment, and parse_lab must not be modified by FinancialResearch documentation or data-source tasks.

