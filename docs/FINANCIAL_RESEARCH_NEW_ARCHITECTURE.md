# FinancialResearch New Architecture

Generated at: 2026-05-03

## Overview

FinancialResearch is now structured as a modular research platform:

- FastAPI backend
- React frontend
- backend domain modules
- independent Parse Lab PDF parsing service

## FastAPI Backend

Backend entrypoint:

```text
backend/app/main.py
```

Initial health endpoint:

```text
GET /api/health
```

The backend owns business orchestration, task references, quality gates, and module-level APIs.

## React Frontend

Frontend placeholder:

```text
frontend_web/
```

The future React frontend calls only FinancialResearch backend APIs. It must not call Parse Lab directly.

## Backend Modules

Initial modules:

- `financial_report`
- `macro_research`
- `sentiment_analysis`
- `market_data_tracking`
- `research_repository`
- `decision_support`
- `system_tasks`

Modules begin inside the main backend to keep architecture simple while contracts stabilize.

## Parse Lab API Boundary

Parse Lab remains an independent service. It owns:

- PDF parsing
- Routing Policy V1.1
- visual table route
- table intent detection
- cross-page table candidates
- parser runtime details

FinancialResearch backend calls Parse Lab through HTTP:

- submit parse task
- poll task
- read result
- cancel task
- delete task record

FinancialResearch does not import Parse Lab internals and does not call parser binaries.

## NAS / Runtime / Data Relationship

Path responsibilities:

- `runtime`: transient task state and generated execution outputs.
- `data`: durable research data and registries.
- `docs`: design and operational documentation.
- `NAS_ROOT`: optional external durable storage root, configured later if needed.

The skeleton defines paths but does not create large data directories.

## Future Module Expansion

Macro, sentiment, and market data tracking remain backend modules initially.

Split a module into an independent API or worker only when one of these appears:

- heavy dependencies
- long-running ingestion or computation
- real-time collection
- model inference isolation
- independent deployment requirements
- independent scaling requirements

## Financial Report Flow

Initial flow:

1. FinancialResearch frontend calls FinancialResearch backend.
2. FinancialResearch backend submits PDF parsing to Parse Lab.
3. Parse Lab writes parse outputs.
4. FinancialResearch backend records task references and result manifests.
5. FinancialResearch backend runs parse quality gate.
6. Later phases can feed approved outputs into extraction and analysis.

## Legacy Streamlit Lessons

The new architecture intentionally avoids the old Streamlit pattern where UI pages, parser orchestration, task state, logs, and business logic lived in one runtime.

See the detailed review:

```text
docs/STREAMLIT_LEGACY_ISSUES_AND_REFACTOR_LESSONS.md
```

The key architectural consequence is simple: frontend display, backend orchestration, and Parse Lab parser execution remain separate.
